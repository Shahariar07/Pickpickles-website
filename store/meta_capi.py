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
TRACKING_KEYS_FILE = os.path.join(settings.BASE_DIR, 'media', 'meta_order_tracking.json')
_tracking_lock = threading.Lock()


def record_order_tracking_keys(order, request):
    """
    Saves customer's exact Meta Match Keys (fbp, fbc, mobile User-Agent, real IP)
    at checkout time. Stored persistently in media/meta_order_tracking.json keyed
    by order_number so when admin confirms the order, the Purchase CAPI event
    is dispatched with high Event Match Quality (EMQ).
    """
    if not order or not getattr(order, 'order_number', None):
        return
    try:
        order_num = str(order.order_number).strip()

        # 1. Extract fbp (Browser ID)
        fbp = (
            (request.POST.get('meta_fbp') if hasattr(request, 'POST') else '') or
            (request.COOKIES.get('_fbp') if hasattr(request, 'COOKIES') else '') or
            (request.session.get('meta_fbp') if hasattr(request, 'session') else '') or ''
        ).strip()

        # 2. Extract fbc (Click ID)
        fbc = (
            (request.POST.get('meta_fbc') if hasattr(request, 'POST') else '') or
            (request.COOKIES.get('_fbc') if hasattr(request, 'COOKIES') else '') or
            (request.session.get('meta_fbc') if hasattr(request, 'session') else '') or ''
        ).strip()

        # If no fbc but fbclid exists, build standard fbc format: fb.1.<timestamp>.<fbclid>
        if not fbc:
            fbclid = (
                (request.GET.get('fbclid') if hasattr(request, 'GET') else '') or
                (request.POST.get('meta_fbclid') if hasattr(request, 'POST') else '') or
                (request.session.get('meta_fbclid') if hasattr(request, 'session') else '') or ''
            ).strip()
            if fbclid:
                fbc = f"fb.1.{int(time.time())}.{fbclid}"

        # 3. Extract customer's real device User-Agent
        client_ua = ''
        if hasattr(request, 'META'):
            client_ua = (request.META.get('HTTP_USER_AGENT') or '').strip()

        # 4. Extract customer's real IP address
        client_ip = ''
        try:
            from store.security import get_client_ip
            client_ip = get_client_ip(request)
        except Exception:
            if hasattr(request, 'META'):
                client_ip = request.META.get('REMOTE_ADDR', '')

        tracking_payload = {
            'fbp': fbp,
            'fbc': fbc,
            'client_user_agent': client_ua,
            'client_ip_address': client_ip,
            'recorded_at': time.strftime('%Y-%m-%d %I:%M:%S %p'),
        }

        with _tracking_lock:
            os.makedirs(os.path.dirname(TRACKING_KEYS_FILE), exist_ok=True)
            existing_data = {}
            if os.path.exists(TRACKING_KEYS_FILE):
                try:
                    with open(TRACKING_KEYS_FILE, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except Exception:
                    existing_data = {}

            existing_data[order_num] = tracking_payload
            with open(TRACKING_KEYS_FILE, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, indent=2)

        logger.info(f"[Meta CAPI] Recorded tracking keys for #{order_num}: fbp={'yes' if fbp else 'no'}, fbc={'yes' if fbc else 'no'}, ip={'yes' if client_ip else 'no'}")
    except Exception as e:
        logger.warning(f"[Meta CAPI] Failed recording order tracking keys for #{getattr(order, 'order_number', 'unknown')}: {e}")


def get_order_tracking_keys(order_number):
    """Retrieve saved tracking keys for this order."""
    try:
        if os.path.exists(TRACKING_KEYS_FILE):
            with open(TRACKING_KEYS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(str(order_number), {})
    except Exception as e:
        logger.warning(f"[Meta CAPI] Error reading tracking file: {e}")
    return {}


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


def get_order_meta_sent_status(order_number):
    """Retrieve sent details if Purchase event for this order was sent to Meta."""
    try:
        if os.path.exists(SENT_ORDERS_FILE):
            with open(SENT_ORDERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(str(order_number))
    except Exception as e:
        logger.warning(f"[Meta CAPI] Error checking sent file: {e}")
    return None


def _execute_meta_purchase(order, force=False):
    """Internal function to send Purchase event to Meta Graph API strictly once per order unless forced."""
    if not force and _is_order_already_sent(order.order_number):
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
        # Load recorded tracking keys for this specific customer
        tracking = get_order_tracking_keys(order.order_number)

        # 1. Customer User Data (Hashed with SHA-256 where required by Meta CAPI)
        user_data = {
            'country': [_sha256('bd')],
            'external_id': [_sha256(order.order_number)],
        }

        # Match Key: Browser ID (fbp) - Unhashed
        fbp_val = tracking.get('fbp')
        if fbp_val:
            user_data['fbp'] = str(fbp_val).strip()

        # Match Key: Click ID (fbc) - Unhashed
        fbc_val = tracking.get('fbc')
        if fbc_val:
            user_data['fbc'] = str(fbc_val).strip()

        # Match Key: Client User Agent - Unhashed
        # 95%+ of traffic is mobile Android/iPhone in Bangladesh
        client_ua = tracking.get('client_user_agent')
        if client_ua:
            user_data['client_user_agent'] = str(client_ua).strip()
        else:
            user_data['client_user_agent'] = 'Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36'

        # Match Key: Real Client IP Address - Unhashed
        client_ip = tracking.get('client_ip_address') or getattr(order, 'ip_address', None)
        if client_ip:
            user_data['client_ip_address'] = str(client_ip).strip()

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

        # 2. Custom Data (Financials & Items with Catalog Content ID match)
        contents = []
        content_ids = []
        for item in order.items.all():
            prod_id = item.product.catalog_id if item.product else str(item.product_name)
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
            pid = item.product.catalog_id if item.product else str(item.product_name)
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

    adv_matching = {
        'em': em,
        'ph': cleaned_phone,
        'fn': fn,
        'ln': ln,
        'ct': ct,
        'country': 'bd',
        'external_id': str(order.order_number).strip().lower()
    }
    try:
        tracking = get_order_tracking_keys(order.order_number)
        if tracking.get('fbp'):
            adv_matching['fbp'] = str(tracking['fbp']).strip()
        if tracking.get('fbc'):
            adv_matching['fbc'] = str(tracking['fbc']).strip()
    except Exception:
        pass

    return {
        'order_number': str(order.order_number),
        'value': float(order.total_amount or 0),
        'currency': 'BDT',
        'content_ids': content_ids,
        'contents': contents,
        'num_items': num_items or 1,
        'advanced_matching': adv_matching
    }


def send_meta_purchase_event_on_accept(order, request=None, force=False):
    """
    Triggered when an admin accepts/confirms an order.
    STRICT ONE-TIME PURCHASE GUARANTEE:
    Checks if this order was already sent to Meta. If already sent, it will NEVER fire again unless force=True.
    """
    if not force and _is_order_already_sent(order.order_number):
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

    return _execute_meta_purchase(order, force=force)


def send_meta_view_content_capi(request, product, event_id):
    """
    Dispatches a high-fidelity 'ViewContent' event to Meta Conversions API (CAPI)
    asynchronously in a background daemon thread, paired with the browser-side eventID.
    Includes maximum customer match keys (IP, User-Agent, fbp, fbc, external_id,
    and phone/email/name when known from session, cookie, or profile).
    """
    def _worker():
        try:
            env_fallback = _read_env_fallback()
            pixel_id = (getattr(settings, 'META_PIXEL_ID', '') or env_fallback.get('META_PIXEL_ID', '') or '2165451210680943').strip()
            access_token = (getattr(settings, 'META_CONVERSIONS_API_TOKEN', '') or env_fallback.get('META_CONVERSIONS_API_TOKEN', '')).strip()
            if not pixel_id or not access_token:
                return

            # Extract user IP & Agent
            client_ip = (
                request.META.get('HTTP_CF_CONNECTING_IP') or
                request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or
                request.META.get('REMOTE_ADDR', '')
            ).strip()
            client_ua = request.META.get('HTTP_USER_AGENT', '').strip() or 'Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36'

            # Extract cookies / session match keys
            fbp = (request.COOKIES.get('_fbp') or (request.session.get('meta_fbp') if hasattr(request, 'session') else '') or '').strip()
            fbc = (request.COOKIES.get('_fbc') or (request.session.get('meta_fbc') if hasattr(request, 'session') else '') or '').strip()
            if not fbc and hasattr(request, 'GET') and request.GET.get('fbclid'):
                fbc = f"fb.1.{int(time.time())}.{request.GET.get('fbclid').strip()}"

            # Known customer info from session or authenticated user
            user_data = {
                'country': [_sha256('bd')],
                'client_ip_address': client_ip,
                'client_user_agent': client_ua,
            }
            if fbp:
                user_data['fbp'] = fbp
            if fbc:
                user_data['fbc'] = fbc

            session_meta = getattr(request, 'session', {})
            known_phone = session_meta.get('customer_phone') or session_meta.get('meta_ph') or ''
            known_email = session_meta.get('customer_email') or session_meta.get('meta_em') or (request.user.email if getattr(request, 'user', None) and request.user.is_authenticated else '')
            known_name = session_meta.get('customer_name') or session_meta.get('meta_fn') or ''
            known_city = session_meta.get('customer_city') or session_meta.get('meta_ct') or 'dhaka'
            external_id = session_meta.get('visitor_id') or session_meta.get('meta_external_id') or ''

            if known_phone:
                formatted_ph = _format_bd_phone(known_phone)
                if formatted_ph:
                    user_data['ph'] = [_sha256(formatted_ph)]
            if known_email:
                user_data['em'] = [_sha256(known_email)]
            if known_name:
                parts = str(known_name).strip().split()
                if parts:
                    user_data['fn'] = [_sha256(parts[0])]
                    if len(parts) > 1:
                        user_data['ln'] = [_sha256(' '.join(parts[1:]))]
            if known_city:
                user_data['ct'] = [_sha256(known_city)]
                user_data['st'] = [_sha256(known_city)]
            if external_id:
                user_data['external_id'] = [_sha256(external_id)]

            prod_price = float(product.price_bdt) if hasattr(product, 'price_bdt') else 0.0

            payload = {
                'data': [{
                    'event_name': 'ViewContent',
                    'event_time': int(time.time()),
                    'event_id': str(event_id),
                    'event_source_url': request.build_absolute_uri(),
                    'action_source': 'website',
                    'user_data': user_data,
                    'custom_data': {
                        'content_name': str(product.name),
                        'content_ids': [str(getattr(product, 'catalog_id', product.id))],
                        'content_type': 'product',
                        'value': prod_price,
                        'currency': 'BDT'
                    }
                }]
            }

            test_event_code = (getattr(settings, 'META_TEST_EVENT_CODE', '') or env_fallback.get('META_TEST_EVENT_CODE', '')).strip()
            if test_event_code:
                payload['test_event_code'] = test_event_code

            url = f"https://graph.facebook.com/v19.0/{pixel_id}/events?access_token={access_token}"
            requests.post(url, json=payload, timeout=4)
        except Exception as e:
            logger.debug(f"[Meta CAPI ViewContent] Async send failed: {e}")

    threading.Thread(target=_worker, daemon=True).start()
