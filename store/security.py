import json
import urllib.parse
import urllib.request
from django.conf import settings
from django.core.cache import cache
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
    1. Blacklist database check (Phone & IP)
    2. Honeypot automated bot check
    3. Hourly rate limiting per IP and per Phone Number
    
    Returns: (is_allowed: bool, error_message: str | None)
    """
    # 1. Honeypot Bot Check
    honeypot_value = request.POST.get('website_security_token', '').strip()
    if honeypot_value:
        # Automated bots fill hidden form fields
        return False, "Automated submission detected. If you are a customer, please reload and place your order."

    # 2. Clean phone number
    clean_digits = ''.join(c for c in str(phone or '') if c.isdigit())
    last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
    client_ip = get_client_ip(request)

    # 3. Check Blacklist Database
    if last_10 and BlacklistedCustomer.is_phone_blocked(last_10):
        return False, "এই ফোন নম্বরটি থেকে ক্যাশ অন ডেলিভারিতে অর্ডার সাময়িকভাবে স্থগিত করা হয়েছে। অর্ডারের জন্য অনুগ্রহ করে সরাসরি আমাদের হোয়াটসঅ্যাপে যোগাযোগ করুন।"

    if client_ip and BlacklistedCustomer.objects.filter(is_active=True, ip_address=client_ip).exists():
        return False, "আপনার ডিভাইস/নেটওয়ার্ক থেকে অর্ডার সাময়িকভাবে স্থগিত রাখা হয়েছে। অনুগ্রহ করে হোয়াটসঅ্যাপে যোগাযোগ করুন।"

    # 4. Rate Limiting (Max 3 orders / hour per phone, Max 5 orders / hour per IP)
    if last_10:
        phone_cache_key = f"rate_limit_phone_{last_10}"
        phone_orders = cache.get(phone_cache_key, 0)
        if phone_orders >= 4:
            return False, "অল্প সময়ের মধ্যে এই নম্বর থেকে একাধিক অর্ডার গ্রহণ করা হয়েছে। পূর্বের অর্ডারটি কনফার্ম করতে অনুগ্রহ করে আমাদের হোয়াটসঅ্যাপে মেসেজ দিন।"

    if client_ip:
        ip_cache_key = f"rate_limit_ip_{client_ip}"
        ip_orders = cache.get(ip_cache_key, 0)
        if ip_orders >= 6:
            return False, "আপনার আইপি থেকে অল্প সময়ে অতিরিক্ত অর্ডার চেষ্টা করা হয়েছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"

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


def verify_cloudflare_turnstile(request, expected_action="checkout"):
    """
    Canonical server-side siteverify implementation for Cloudflare Turnstile.
    - Validates token presence, format, and length
    - Issues POST to https://challenges.cloudflare.com/turnstile/v0/siteverify
    - Validates success === True and matching action
    """
    secret_key = getattr(settings, 'CLOUDFLARE_TURNSTILE_SECRET_KEY', '')
    if not secret_key:
        return True, None

    turnstile_token = request.POST.get('cf-turnstile-response', '')
    if not turnstile_token or not isinstance(turnstile_token, str):
        return False, "Please complete the Cloudflare security verification before placing order."

    token_clean = turnstile_token.strip()
    if len(token_clean) == 0 or len(token_clean) > 2048:
        return False, "Invalid security token. Please reload and try again."

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

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            if not result.get('success'):
                err_codes = result.get('error-codes', [])
                return False, f"Security verification failed ({', '.join(err_codes) if err_codes else 'unauthorized'}). Please retry."

            # Verify action if present in response
            action = result.get('action')
            if action and expected_action and action != expected_action:
                return False, "Security verification action mismatch. Please reload and try again."

            return True, None

    except Exception as err:
        # If Cloudflare verification endpoint is momentarily unreachable, do not block legitimate customers
        return True, None

