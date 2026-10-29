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


def _read_env_fallback():
    env_vars = {}
    try:
        env_file = os.path.join(settings.BASE_DIR, '.env')
        if os.path.exists(env_file):
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        env_vars[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env_vars


def _execute_meta_purchase(order):
    """Internal function to send Purchase event to Meta Graph API strictly once per order."""
    if _is_order_already_sent(order.order_number):
        logger.info(f"[Meta CAPI] Purchase for Order #{order.order_number} was already sent previously. Skipping duplicate.")
        print(f"[Meta CAPI INFO] Order #{order.order_number} was already sent to Meta. Skipping duplicate.")
        return {'success': True, 'already_sent': True}

    env_fallback = _read_env_fallback()
    pixel_id = (getattr(settings, 'META_PIXEL_ID', '') or env_fallback.get('META_PIXEL_ID', '') or '2165451210680943').strip()
    access_token = (getattr(settings, 'META_CONVERSIONS_API_TOKEN', '') or env_fallback.get('META_CONVERSIONS_API_TOKEN', '')).strip()
    test_event_code = (getattr(settings, 'META_TEST_EVENT_CODE', '') or env_fallback.get('META_TEST_EVENT_CODE', '')).strip()

    if not pixel_id or not access_token:
        logger.warning(f"[Meta CAPI] Skipping Purchase for #{order.order_number}: Missing META_PIXEL_ID or META_CONVERSIONS_API_TOKEN.")
        print(f"[Meta CAPI WARNING] Missing META_PIXEL_ID or META_CONVERSIONS_API_TOKEN in settings!")
        return {'success': False, 'error': 'Missing META_PIXEL_ID or META_CONVERSIONS_API_TOKEN'}

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
        content_ids = []
        for item in order.items.all():
            prod_id = str(item.product.id) if item.product else str(item.product_name)
            content_ids.append(prod_id)
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
            'content_ids': content_ids,
            'num_items': len(contents) or 1
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

        url = f"https://graph.facebook.com/v19.0/{pixel_id}/events"
        print(f"[Meta CAPI] Dispatching Purchase event for Order #{order.order_number} to Meta...")

        # Send live production event (always goes to Overview & Ads Manager)
        live_post_data = {
            'data': [event_payload],
            'access_token': access_token
        }
        response = requests.post(url, json=live_post_data, timeout=6)
        res_json = response.json()

        # Also send with test_event_code if configured in .env so it pops up in Test Events tab immediately
        if test_event_code:
            try:
                test_post_data = {
                    'data': [event_payload],
                    'access_token': access_token,
                    'test_event_code': test_event_code
                }
                requests.post(url, json=test_post_data, timeout=4)
                print(f"[Meta CAPI TEST] Also dispatched with Test Event Code: {test_event_code}")
            except Exception as te:
                logger.warning(f"[Meta CAPI TEST] Failed sending test_event_code copy: {te}")

        if response.status_code == 200 and res_json.get('events_received', 0) > 0:
            print(f"[Meta CAPI SUCCESS] Event received by Meta: {res_json}")
            logger.info(f"[Meta CAPI SUCCESS] Purchase successfully sent for Order #{order.order_number}: {res_json}")
            
            # Record in isolated JSON file (Zero impact on customer or admin notes)
            _mark_order_as_sent(order.order_number, order.total_amount, res_json)
            return {
                'success': True,
                'events_received': res_json.get('events_received', 1),
                'fbtrace_id': res_json.get('fbtrace_id', '')
            }
        else:
            print(f"[Meta CAPI ERROR] Failed response from Meta (Status {response.status_code}): {res_json}")
            logger.error(f"[Meta CAPI ERROR] Error for #{order.order_number}: {res_json}")
            return {'success': False, 'error': str(res_json)}

    except Exception as e:
        print(f"[Meta CAPI EXCEPTION] Error while sending: {e}")
        logger.error(f"[Meta CAPI EXCEPTION] Error for Order #{order.order_number}: {e}")
        return {'success': False, 'error': str(e)}


def build_browser_purchase_payload(order):
    """
    Builds a JSON-serializable dict for firing Browser Meta Pixel fbq('track', 'Purchase')
    with Customer Manual Advanced Matching when an admin confirms an order.
    """
    cleaned_phone = _format_bd_phone(order.customer_phone)
    raw_name = (order.customer_name or '').strip().lower()
    name_parts = raw_name.split()
    fn = name_parts[0] if name_parts else ''
    ln = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
    ct = (order.delivery_city or 'dhaka').strip().lower()
    em = (order.customer_email or '').strip().lower()

    content_ids = []
    contents = []
    num_items = 0
    try:
        for item in order.items.all():
            pid = str(item.product.id) if item.product else str(item.product_name)
            qty = int(item.quantity or 1)
            content_ids.append(pid)
            contents.append({
                'id': pid,
                'quantity': qty,
                'item_price': float(item.unit_price or 0)
            })
            num_items += qty
    except Exception:
        num_items = 1

    return {
        'order_number': str(order.order_number),
        'value': float(order.total_amount or 0),
        'currency': 'BDT',
        'content_ids': content_ids,
        'contents': contents,
        'num_items': num_items or 1,
        'advanced_matching': {
            'em': em,
            'ph': cleaned_phone,
            'fn': fn,
            'ln': ln,
            'ct': ct,
            'country': 'bd',
            'external_id': str(order.order_number).strip().lower()
        }
    }


def send_meta_purchase_event_on_accept(order, request=None):
    """
    Triggered when an admin accepts/confirms an order.
    STRICT ONE-TIME PURCHASE GUARANTEE:
    Checks if this order was already sent to Meta. If already sent, it will NEVER fire again.
    """
    if _is_order_already_sent(order.order_number):
        logger.info(f"[Meta CAPI] Order #{order.order_number} has already been sent to Meta. Skipping duplicate send.")
        print(f"[Meta CAPI INFO] Order #{order.order_number} has already been sent to Meta. Skipping duplicate send.")
        return {'success': True, 'already_sent': True}

    if request is not None and hasattr(request, 'session'):
        try:
            queue = request.session.get('meta_pixel_purchase_events', [])
            if not isinstance(queue, list):
                queue = []
            queue.append(build_browser_purchase_payload(order))
            request.session['meta_pixel_purchase_events'] = queue
            request.session.modified = True
        except Exception as e:
            logger.warning(f"[Meta CAPI] Failed queuing browser purchase event in session: {e}")

    return _execute_meta_purchase(order)
