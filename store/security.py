import json
from datetime import timedelta
import urllib.parse
import urllib.request
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from dashboard.models import BlacklistedCustomer


def get_client_ip(request):
    """
    Extracts the real client IP address considering Cloudflare, reverse proxies, and direct connections.
    """
    # Cloudflare sends the real visitor IP in HTTP_CF_CONNECTING_IP
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP')
    if cf_ip:
        return cf_ip.strip()

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()

    return request.META.get('REMOTE_ADDR', '').strip()


def check_rate_limit_and_blacklist(request, phone):
    """
    Multi-layered security verification before accepting an order:
    1. Honeypot automated bot check
    2. Blacklist database check (Phone & IP)
    3. Database-level duplicate cooldown (5 min) & active PENDING order cap (max 2)
    4. Repeat order-refuser COD protection (2+ cancelled orders with 0 delivered)
    5. Hourly rate limiting per IP and per Phone Number
    
    Returns: (is_allowed: bool, error_message: str | None)
    """
    # 1. Honeypot Bot Check
    honeypot_value = request.POST.get('website_security_token', '').strip()
    if honeypot_value:
        return False, "Automated submission detected. If you are a customer, please reload and place your order."

    # 2. Clean phone number
    clean_digits = ''.join(c for c in str(phone or '') if c.isdigit())
    last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
    client_ip = get_client_ip(request)
    payment_method = (request.POST.get('payment_method') or 'COD').strip().upper()

    # 3. Check Blacklist Database
    if last_10 and BlacklistedCustomer.is_phone_blocked(last_10):
        return False, "Cash on Delivery orders are currently restricted for this mobile number. Please contact us directly on WhatsApp to place your order."

    if client_ip and BlacklistedCustomer.objects.filter(is_active=True, ip_address=client_ip).exists():
        return False, "Orders from your network/device are temporarily restricted. Please contact our support team on WhatsApp."

    # 4. Database-Level Duplicate Order Cooldown & Repeat-Refuser Protection
    try:
        from dashboard.models import DashboardSecurityConfig
        sec_cfg = DashboardSecurityConfig.get_config()
    except Exception:
        sec_cfg = None

    cooldown_mins = int(sec_cfg.order_duplicate_cooldown_minutes if sec_cfg is not None else getattr(settings, 'ORDER_DUPLICATE_COOLDOWN_MINUTES', 5))
    max_pending_per_phone = int(sec_cfg.order_max_active_pending_per_phone if sec_cfg is not None else getattr(settings, 'ORDER_MAX_ACTIVE_PENDING_PER_PHONE', 2))
    cod_cancel_threshold = int(sec_cfg.order_cod_cancel_block_threshold if sec_cfg is not None else getattr(settings, 'ORDER_COD_CANCEL_BLOCK_THRESHOLD', 2))
    max_phone_hourly = int(sec_cfg.order_rate_limit_per_phone_hourly if sec_cfg is not None else getattr(settings, 'ORDER_RATE_LIMIT_PER_PHONE_HOURLY', 3))
    max_ip_hourly = int(sec_cfg.order_rate_limit_per_ip_hourly if sec_cfg is not None else getattr(settings, 'ORDER_RATE_LIMIT_PER_IP_HOURLY', 5))

    if last_10:
        from store.models import Order
        now = timezone.now()
        recent_cutoff = now - timedelta(minutes=cooldown_mins)

        customer_orders = Order.objects.filter(customer_phone__icontains=last_10)

        # 4a. Block rapid duplicate submissions within cooldown window
        if cooldown_mins > 0 and customer_orders.filter(created_at__gte=recent_cutoff).exclude(order_status='CANCELLED').exists():
            return False, f"We just received an order from this mobile number a few minutes ago! Please wait {cooldown_mins} minutes or message us on WhatsApp if you need to modify your order."

        # 4b. Block if customer already has >= max unconfirmed PENDING orders in queue
        if max_pending_per_phone > 0 and customer_orders.filter(order_status='PENDING').count() >= max_pending_per_phone:
            return False, f"You already have {max_pending_per_phone} pending orders awaiting confirmation. Our team will call you shortly to confirm them, or reach us on WhatsApp."

        # 4c. Auto-protect against repeat COD order refusers
        if payment_method == 'COD' and cod_cancel_threshold > 0:
            delivered_cnt = customer_orders.filter(order_status='DELIVERED').count()
            cancelled_cnt = customer_orders.filter(order_status='CANCELLED').count()
            if delivered_cnt == 0 and cancelled_cnt >= cod_cancel_threshold:
                return False, "Due to multiple previously cancelled Cash on Delivery orders on this number, please select bKash Advance Payment or contact us on WhatsApp to confirm your order."

    # 5. Cache Rate Limiting
    if last_10 and max_phone_hourly > 0:
        phone_cache_key = f"rate_limit_phone_{last_10}"
        phone_orders = cache.get(phone_cache_key, 0)
        if phone_orders >= max_phone_hourly:
            return False, "Multiple orders have been placed from this number recently. Please contact us on WhatsApp to confirm your existing order."

    if client_ip and max_ip_hourly > 0:
        ip_cache_key = f"rate_limit_ip_{client_ip}"
        ip_orders = cache.get(ip_cache_key, 0)
        if ip_orders >= max_ip_hourly:
            return False, "Too many order attempts from your connection in a short period. Please try again after a while."

    return True, None


def record_successful_order_rate(request, phone):
    """
    Records an order placement to enforce hourly rate limiting.
    """
    clean_digits = ''.join(c for c in str(phone or '') if c.isdigit())
    last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
    client_ip = get_client_ip(request)

    if last_10:
        phone_cache_key = f"rate_limit_phone_{last_10}"
        current = cache.get(phone_cache_key, 0)
        cache.set(phone_cache_key, current + 1, timeout=3600)  # 1 hour window

    if client_ip:
        ip_cache_key = f"rate_limit_ip_{client_ip}"
        current = cache.get(ip_cache_key, 0)
        cache.set(ip_cache_key, current + 1, timeout=3600)  # 1 hour window


def check_review_rate_limit(request):
    """
    Prevents automated spam bots from flooding public reviews (Max 3 reviews per hour per IP).
    """
    honeypot_value = request.POST.get('website_security_token', '').strip()
    if honeypot_value:
        return False, "Automated submission detected."

    try:
        from dashboard.models import DashboardSecurityConfig
        sec_cfg = DashboardSecurityConfig.get_config()
        max_review_hourly = int(sec_cfg.review_rate_limit_per_ip_hourly)
    except Exception:
        max_review_hourly = int(getattr(settings, 'REVIEW_RATE_LIMIT_PER_IP_HOURLY', 3))
    client_ip = get_client_ip(request)
    if client_ip and max_review_hourly > 0:
        review_cache_key = f"rate_limit_review_ip_{client_ip}"
        submitted_count = cache.get(review_cache_key, 0)
        if submitted_count >= max_review_hourly:
            return False, "You have submitted multiple reviews recently. Please wait a while before submitting another review."
    return True, None


def record_review_submission(request):
    """
    Records a public review submission per IP for rate limiting (1 hour window).
    """
    client_ip = get_client_ip(request)
    if client_ip:
        review_cache_key = f"rate_limit_review_ip_{client_ip}"
        current = cache.get(review_cache_key, 0)
        cache.set(review_cache_key, current + 1, timeout=3600)


def verify_cloudflare_turnstile(request, expected_action="checkout"):
    """
    Server-side Cloudflare Turnstile verification with Smart Graceful Fallback.
    - If token is provided, strictly validates it with Cloudflare API.
    - If Cloudflare token is missing (e.g. slow mobile network, script blocker),
      falls back gracefully to Honeypot trap so paying human customers are NEVER blocked!
    """
    secret_key = getattr(settings, 'CLOUDFLARE_TURNSTILE_SECRET_KEY', '')
    if not secret_key:
        return True, None

    # Check invisible honeypot first
    honeypot = request.POST.get('website_security_token', '').strip()
    if honeypot:
        return False, "Automated submission detected."

    turnstile_token = request.POST.get('cf-turnstile-response', '')
    # Graceful fallback: If customer's mobile browser blocked or delayed Cloudflare,
    # do NOT block human customers who filled out legitimate order/review details!
    if not turnstile_token or not isinstance(turnstile_token, str):
        return True, None

    token_clean = turnstile_token.strip()
    if len(token_clean) == 0 or len(token_clean) > 2048:
        return True, None

    try:
        url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
        payload = urllib.parse.urlencode({
            'secret': secret_key,
            'response': token_clean,
            'remoteip': get_client_ip(request)
        }).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Pickpickles-Turnstile/1.0'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            if not result.get('success'):
                err_codes = result.get('error-codes', [])
                # If explicit fake token from malicious bot
                if 'invalid-input-response' in err_codes:
                    return False, "Security check failed. Please refresh and try again."
                return True, None

            # Verify action if present in response
            action = result.get('action')
            if action and expected_action and action != expected_action:
                return False, "Security verification action mismatch. Please reload and try again."

            return True, None

    except Exception:
        # If Cloudflare verification endpoint is momentarily unreachable, never block customers
        return True, None
