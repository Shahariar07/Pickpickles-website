"""
Pickpickles High-Reliability Web Push Notification Dispatcher.

Addresses mobile delivery delays, Android Doze mode throttling, and offline dropouts:
1. RFC 8030 'Urgency: high' - Pierces Android Doze Mode and delivers immediate heads-up alerts with sound/vibration.
2. Extended TTL (259,200s / 72 hours) - Guarantees offline phones receive the notification as soon as internet connects.
3. Asynchronous Daemon Thread - Zero delay to customer checkout response.
4. Auto-prunes expired or revoked FCM subscriptions (HTTP 404 / 410).
5. Comprehensive logging for full observability in production.
"""

import json
import logging
import threading
import time
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()

# 72 hours (3 days) in seconds. Standard Web Push maximum is 4 weeks.
# 72h is ideal for e-commerce orders: if admin's phone is off for the weekend,
# all pending orders are delivered immediately when the phone reconnects to internet.
EXTENDED_PUSH_TTL_SECONDS = 259200


def _build_vapid_data():
    """Retrieve VAPID credentials from Django settings."""
    wp_settings = getattr(settings, 'WEBPUSH_SETTINGS', {})
    priv_key = wp_settings.get('VAPID_PRIVATE_KEY')
    admin_email = wp_settings.get('VAPID_ADMIN_EMAIL', 'admin@pickpickles.xyz')
    if priv_key:
        return {
            'vapid_private_key': priv_key,
            'vapid_claims': {'sub': f'mailto:{admin_email}'}
        }
    return {}


def _deliver_to_subscription(subscription, payload_str, ttl, urgency='high'):
    """
    Delivers a Web Push payload to a single SubscriptionInfo instance using pywebpush.
    Applies Urgency: high and long TTL to guarantee prompt delivery on mobile.
    """
    try:
        from pywebpush import webpush, WebPushException
        from webpush.utils import _process_subscription_info
    except ImportError as e:
        logger.error(f"[WebPush] pywebpush or django-webpush missing: {e}")
        return False, 'missing_lib'

    sub_data = _process_subscription_info(subscription)
    vapid_data = _build_vapid_data()
    headers = {
        'Urgency': urgency,
        'Topic': 'pickpickles-order'
    }

    try:
        resp = webpush(
            subscription_info=sub_data,
            data=payload_str,
            ttl=ttl,
            headers=headers,
            timeout=12,
            **vapid_data
        )
        status_code = getattr(resp, 'status_code', None)
        logger.info(f"[WebPush SUCCESS] Subscription ID {subscription.id} (Endpoint: {subscription.endpoint[:45]}...) responded HTTP {status_code}")
        return True, 'delivered'
    except WebPushException as exc:
        status_code = getattr(exc.response, 'status_code', None)
        logger.warning(f"[WebPush WARN] Subscription ID {subscription.id} failed with HTTP {status_code}: {exc}")
        # Clean up stale or invalid endpoints (404 Not Found or 410 Gone)
        if status_code in (404, 410):
            try:
                logger.info(f"[WebPush] Purging expired subscription ID {subscription.id} from database.")
                subscription.delete()
            except Exception as del_err:
                logger.error(f"[WebPush] Error deleting subscription {subscription.id}: {del_err}")
            return False, 'expired_purged'
        return False, f'http_{status_code}'
    except Exception as err:
        logger.error(f"[WebPush ERROR] Subscription ID {subscription.id} exception: {err}")
        return False, 'network_error'


def send_high_priority_user_notification(user, payload, ttl=EXTENDED_PUSH_TTL_SECONDS, urgency='high'):
    """
    Sends a high-priority push notification to all active devices registered to a specific user.
    """
    if not hasattr(user, 'webpush_info'):
        return 0, 0

    payload_str = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    push_infos = list(user.webpush_info.select_related('subscription').all())

    success_count = 0
    fail_count = 0

    for pi in push_infos:
        if not pi.subscription:
            continue
        ok, reason = _deliver_to_subscription(pi.subscription, payload_str, ttl=ttl, urgency=urgency)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    return success_count, fail_count


def _async_notify_admins(payload, order_num):
    """
    Background worker function that finds all admin/staff users and delivers the push alert.
    """
    try:
        admins = User.objects.filter(is_active=True).filter(
            models.Q(is_superuser=True) | models.Q(is_staff=True)
        )
        if not admins.exists():
            logger.info("[WebPush] No active staff/superuser accounts found to notify.")
            return

        total_delivered = 0
        total_failed = 0

        for admin in admins:
            ok_cnt, fail_cnt = send_high_priority_user_notification(
                user=admin,
                payload=payload,
                ttl=EXTENDED_PUSH_TTL_SECONDS,
                urgency='high'
            )
            total_delivered += ok_cnt
            total_failed += fail_cnt

        logger.info(
            f"[WebPush Complete] Order #{order_num}: Dispatched to {admins.count()} admin(s). "
            f"Delivered to {total_delivered} device(s), Failed/Purged {total_failed}."
        )
    except Exception as e:
        logger.exception(f"[WebPush Fatal] Unexpected error in background push dispatch: {e}")


def dispatch_order_created_notification(order):
    """
    Dispatches a high-priority push notification whenever an Order is placed.
    Spawns a daemon background thread so customer checkout has zero latency.
    """
    try:
        order_num = order.order_number or f"#{order.pk}"
        customer = order.customer_name or "New Customer"
        phone = order.customer_phone or ""
        city = order.delivery_city or ""
        total_str = f"৳{order.total_amount:.2f}" if order.total_amount else ""

        body_parts = [f"Customer: {customer}"]
        if phone:
            body_parts.append(f"Phone: {phone}")
        if total_str:
            body_parts.append(f"Total: {total_str}")
        if city:
            body_parts.append(f"Area: {city}")

        # Compute creation timestamp in epoch milliseconds for accurate Android display
        created_dt = order.created_at if hasattr(order, 'created_at') and order.created_at else timezone.now()
        timestamp_ms = int(created_dt.timestamp() * 1000)

        payload = {
            "head": f"🛒 New Order #{order_num} Received!",
            "body": " • ".join(body_parts),
            "icon": "/static/images/icon-192.png",
            "badge": "/static/images/badge-96.png",
            "url": f"/dashboard/order/{order_num}/",
            "tag": f"order-{order_num}",
            "timestamp": timestamp_ms,
            "order_number": str(order_num),
            "priority": "high",
            "vibrate": [300, 100, 300, 100, 400]
        }

        # Spawn background thread
        worker = threading.Thread(
            target=_async_notify_admins,
            args=(payload, order_num),
            daemon=True,
            name=f"WebPushWorker-{order_num}"
        )
        worker.start()

    except Exception as exc:
        logger.exception(f"[WebPush Dispatch Error] Could not initialize push for order: {exc}")
