"""
Meta Conversions API (CAPI) Service for PickPickles.
Enables server-side event tracking so that the official 'Purchase' event
is sent to Meta ONLY after the admin verifies and accepts/confirms an order.
"""

import hashlib
import json
import logging
import os
import threading
import time
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SENT_ORDERS_FILE = os.path.join(settings.BASE_DIR, 'media', 'meta_capi_sent_orders.json')


def _is_order_already_sent(order_number):
    """Check if Purchase event for this order was already sent to Meta."""
    try:
        if os.path.exists(SENT_ORDERS_FILE):
            with open(SENT_ORDERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return str(order_number) in data
    except Exception as e:
        logger.warning(f"[Meta CAPI] Error checking sent file: {e}")
    return False


def _mark_order_as_sent(order_number, total_amount, meta_response):
    """Record sent order in media/meta_capi_sent_orders.json (No modification to customer or admin notes)."""
    try:
        os.makedirs(os.path.dirname(SENT_ORDERS_FILE), exist_ok=True)
        data = {}
        if os.path.exists(SENT_ORDERS_FILE):
            try:
                with open(SENT_ORDERS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data[str(order_number)] = {
            'sent_at': time.strftime('%Y-%m-%d %I:%M:%S %p'),
            'amount': float(total_amount),
            'events_received': meta_response.get('events_received', 1),
            'fbtrace_id': meta_response.get('fbtrace_id', '')
        }

        with open(SENT_ORDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"[Meta CAPI] Failed to update sent orders file: {e}")


def _sha256(val):
    """Normalize string and return SHA256 hex digest for Meta CAPI privacy hashing."""
    if not val:
        return None
    val_clean = str(val).strip().lower()
    if not val_clean:
        return None
    return hashlib.sha256(val_clean.encode('utf-8')).hexdigest()


def _format_bd_phone(raw_phone):
    """Format Bangladeshi phone number to international 8801XXXXXXXXX digits."""
    if not raw_phone:
        return ''
    digits = ''.join(c for c in str(raw_phone) if c.isdigit())
    if digits.startswith('01') and len(digits) == 11:
        return '88' + digits
    if digits.startswith('8801') and len(digits) == 13:
        return digits
    return digits


def _execute_meta_purchase(order):
    """Internal function to send Purchase event to Meta Graph API."""
    pixel_id = getattr(settings, 'META_PIXEL_ID', '').strip()
    access_token = getattr(settings, 'META_CONVERSIONS_API_TOKEN', '').strip()
    test_event_code = getattr(settings, 'META_TEST_EVENT_CODE', '').strip() or os.environ.get('META_TEST_EVENT_CODE', '').strip()

    if not pixel_id or not access_token:
        logger.warning(f"[Meta CAPI] Skipping Purchase for #{order.order_number}: Missing META_PIXEL_ID or META_CONVERSIONS_API_TOKEN.")
        print(f"[Meta CAPI WARNING] Missing META_PIXEL_ID or META_CONVERSIONS_API_TOKEN in settings!")
        return False

    # Check deduplication flag (Strictly via isolated JSON file, NEVER touch order notes!)
    if _is_order_already_sent(order.order_number):
        logger.info(f"[Meta CAPI] Purchase for Order #{order.order_number} was already sent previously. Skipping duplicate.")
        print(f"[Meta CAPI INFO] Order #{order.order_number} was already sent to Meta. Skipping duplicate.")
        return True

    try:
        # 1. Customer User Data (Hashed with SHA-256 as required by Meta CAPI)
        user_data = {
            'country': [_sha256('bd')],
            'external_id': [_sha256(order.order_number)],
            'client_user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }
        if getattr(order, 'ip_address', None):
            user_data['client_ip_address'] = str(order.ip_address).strip()

        # Email
        if order.customer_email:
            hashed_email = _sha256(order.customer_email)
            if hashed_email:
                user_data['em'] = [hashed_email]

        # Phone
        cleaned_phone = _format_bd_phone(order.customer_phone)
        if cleaned_phone:
            hashed_phone = _sha256(cleaned_phone)
            if hashed_phone:
                user_data['ph'] = [hashed_phone]

        # Name parts
        raw_name = (order.customer_name or '').strip()
        if raw_name:
            parts = raw_name.split()
            if parts:
                hashed_fn = _sha256(parts[0])
                if hashed_fn:
                    user_data['fn'] = [hashed_fn]
                if len(parts) > 1:
                    hashed_ln = _sha256(' '.join(parts[1:]))
                    if hashed_ln:
                        user_data['ln'] = [hashed_ln]

        # City
        if order.delivery_city:
            hashed_city = _sha256(order.delivery_city)
            if hashed_city:
                user_data['ct'] = [hashed_city]

        # 2. Custom Data (Financials & Items)
        contents = []
        for item in order.items.all():
            prod_id = str(item.product.id) if item.product else str(item.product_name)
            contents.append({
                'id': prod_id,
                'quantity': int(item.quantity),
                'item_price': float(item.unit_price)
            })

        custom_data = {
            'currency': 'BDT',
            'value': float(order.total_amount),
            'order_id': order.order_number,
            'content_type': 'product',
            'num_items': len(contents)
        }
        if contents:
            custom_data['contents'] = contents

        # 3. Assemble Meta CAPI Event
        event_payload = {
            'event_name': 'Purchase',
            'event_time': int(time.time()),
            'event_id': order.order_number,
            'action_source': 'website',
            'event_source_url': 'https://www.pickpickles.xyz/checkout/',
            'user_data': user_data,
            'custom_data': custom_data
        }

        post_data = {
            'data': [event_payload],
            'access_token': access_token
        }

        # If a Meta Test Event Code is provided (from Events Manager > Test Events tab), include it for instant real-time live preview!
        if test_event_code:
            post_data['test_event_code'] = test_event_code
            print(f"[Meta CAPI TEST] Using Test Event Code: {test_event_code}")

        url = f"https://graph.facebook.com/v19.0/{pixel_id}/events"
        print(f"[Meta CAPI] Dispatching Purchase event for Order #{order.order_number} to Meta...")

        response = requests.post(url, json=post_data, timeout=12)
        res_json = response.json()

        if response.status_code == 200 and res_json.get('events_received', 0) > 0:
            print(f"[Meta CAPI SUCCESS] Event received by Meta: {res_json}")
            logger.info(f"[Meta CAPI SUCCESS] Purchase successfully sent for Order #{order.order_number}: {res_json}")
            
            # Record in isolated JSON file (Zero impact on customer or admin notes)
            _mark_order_as_sent(order.order_number, order.total_amount, res_json)
            return True
        else:
            print(f"[Meta CAPI ERROR] Failed response from Meta (Status {response.status_code}): {res_json}")
            logger.error(f"[Meta CAPI ERROR] Error for #{order.order_number}: {res_json}")
            return False

    except Exception as e:
        print(f"[Meta CAPI EXCEPTION] Error while sending: {e}")
        logger.error(f"[Meta CAPI EXCEPTION] Error for Order #{order.order_number}: {e}")
        return False


def send_meta_purchase_event_on_accept(order):
    """
    Triggered when an admin accepts/confirms an order.
    Dispatches asynchronous Meta Conversions API Purchase event in a daemon thread.
    """
    t = threading.Thread(target=_execute_meta_purchase, args=(order,), daemon=True)
    t.start()
