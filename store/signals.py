import logging
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from webpush import send_user_notification
from .models import Order

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=Order)
def order_created_webpush_notification(sender, instance, created, **kwargs):
    """
    Real-time Web Push notification signal dispatched whenever a new Order is placed.
    Safely notifies all staff and superuser accounts without risking order creation failure.
    """
    if not created:
        return

    try:
        # Find active staff & superuser admin accounts
        admins = User.objects.filter(is_active=True).filter(
            models.Q(is_superuser=True) | models.Q(is_staff=True)
        )

        if not admins.exists():
            return

        order_num = instance.order_number or f"#{instance.pk}"
        customer = instance.customer_name or "New Customer"
        phone = instance.customer_phone or ""
        total_str = f"৳{instance.total_amount:.2f}" if instance.total_amount else ""

        body_parts = [f"Customer: {customer}"]
        if phone:
            body_parts.append(f"Phone: {phone}")
        if total_str:
            body_parts.append(f"Total: {total_str}")

        payload = {
            "head": f"🛒 New Order {order_num} Received!",
            "body": " • ".join(body_parts),
            "icon": "/static/images/icon-192.png",
            "badge": "/static/images/badge-96.png",
            "url": f"/dashboard/order/{order_num}/",
            "tag": f"order-{order_num}"
        }

        for admin in admins:
            try:
                send_user_notification(user=admin, payload=payload, ttl=1000)
            except Exception as notify_err:
                logger.warning(f"Could not send webpush notification to {admin.username}: {notify_err}")

    except Exception as e:
        logger.exception(f"Unexpected error in order_created_webpush_notification: {e}")
