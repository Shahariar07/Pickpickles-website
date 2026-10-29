import os
import time
import hashlib
import json
from django.conf import settings
from .cart import Cart
from .models import Category


def _get_dynamic_static_version():
    """
    Returns a content hash (MD5) of core static files (CSS & JS) so browsers
    instantly and reliably fetch updated versions whenever code is changed,
    completely immune to filesystem mtime quirks or Cloudflare cache.
    """
    try:
        hasher = hashlib.md5()
        found_any = False
        search_dirs = []
        
        for d in getattr(settings, 'STATICFILES_DIRS', []):
            search_dirs.append(str(d))
            
        sroot = getattr(settings, 'STATIC_ROOT', None)
        if sroot:
            search_dirs.append(str(sroot))
            
        bdir = getattr(settings, 'BASE_DIR', None)
        if bdir:
            search_dirs.append(os.path.join(str(bdir), 'static'))
            search_dirs.append(os.path.join(str(bdir), 'staticfiles'))

        for sdir in search_dirs:
            if not sdir or not os.path.exists(sdir):
                continue
            for fname in ['js/main.js', 'css/style.css']:
                fpath = os.path.join(sdir, fname)
                if os.path.isfile(fpath):
                    with open(fpath, 'rb') as f:
                        hasher.update(f.read())
                    found_any = True
                    
        if found_any:
            return hasher.hexdigest()[:10]
    except Exception:
        pass
    return str(int(time.time()))


def cart_context(request):
    static_version = _get_dynamic_static_version()
    meta_pixel_id = getattr(settings, 'META_PIXEL_ID', '') or os.environ.get('META_PIXEL_ID', '') or '2165451210680943'
    google_analytics_id = getattr(settings, 'GOOGLE_ANALYTICS_ID', '')
    cloudflare_turnstile_site_key = getattr(settings, 'CLOUDFLARE_TURNSTILE_SITE_KEY', '')
    
    trash_orders_count = 0
    pending_reviews_count = 0
    try:
        if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
            from .models import Order, Review
            trash_orders_count = Order.trash_objects.count()
            pending_reviews_count = Review.objects.filter(is_approved=False).count()
    except Exception:
        trash_orders_count = 0
        pending_reviews_count = 0
        
    auto_whatsapp_url = None
    auto_whatsapp_order_number = None
    if hasattr(request, 'session') and 'auto_whatsapp_url' in request.session:
        auto_whatsapp_url = request.session.pop('auto_whatsapp_url', None)
        auto_whatsapp_order_number = request.session.pop('auto_whatsapp_order_number', None)

    meta_pixel_purchase_events_json = ''
    if hasattr(request, 'session') and 'meta_pixel_purchase_events' in request.session:
        try:
            raw_ev = request.session.pop('meta_pixel_purchase_events', None)
            if raw_ev:
                meta_pixel_purchase_events_json = json.dumps(raw_ev)
        except Exception:
            meta_pixel_purchase_events_json = ''

    meta_adv = {'em': '', 'ph': '', 'fn': '', 'ln': '', 'ct': 'dhaka', 'country': 'bd', 'external_id': ''}
    try:
        if hasattr(request, 'session'):
            sess_adv = request.session.get('meta_advanced_matching')
            if isinstance(sess_adv, dict):
                for k in ('em', 'ph', 'fn', 'ln', 'ct', 'country', 'external_id'):
                    if sess_adv.get(k):
                        meta_adv[k] = str(sess_adv[k]).strip().lower()
            if not meta_adv['external_id']:
                ext_id = request.session.get('meta_external_id')
                if not ext_id:
                    import uuid
                    ext_id = f"pkp_{uuid.uuid4().hex[:12]}"
                    request.session['meta_external_id'] = ext_id
                meta_adv['external_id'] = ext_id
        if not meta_adv['ph']:
            from .models import Order
            from .security import get_client_ip
            visitor_ip = get_client_ip(request)
            recent_order = Order.objects.filter(ip_address=visitor_ip).order_by('-created_at').first() if visitor_ip and visitor_ip not in ('127.0.0.1', '::1', 'localhost') else None
            if not recent_order:
                recent_order = Order.objects.order_by('-created_at').first() if getattr(request, 'user', None) and request.user.is_authenticated else None
            if recent_order:
                raw_ph = ''.join(c for c in str(recent_order.customer_phone or '') if c.isdigit())
                if raw_ph.startswith('01') and len(raw_ph) == 11:
                    raw_ph = '88' + raw_ph
                elif len(raw_ph) == 10 and raw_ph.startswith('1'):
                    raw_ph = '880' + raw_ph
                meta_adv['ph'] = raw_ph
                if recent_order.customer_email:
                    meta_adv['em'] = recent_order.customer_email.strip().lower()
                if recent_order.customer_name:
                    nparts = recent_order.customer_name.strip().lower().split()
                    if nparts:
                        meta_adv['fn'] = nparts[0]
                    if len(nparts) > 1:
                        meta_adv['ln'] = ' '.join(nparts[1:])
                if recent_order.delivery_city:
                    meta_adv['ct'] = recent_order.delivery_city.strip().lower()
                if recent_order.order_number:
                    meta_adv['external_id'] = str(recent_order.order_number).strip()
    except Exception:
        pass

    can_delete = False
    can_edit = False
    can_dispatch = False
    strict_admin_only_delete = True
    strict_admin_only_edit = False
    strict_admin_only_dispatch = False
    try:
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            if user.is_superuser:
                can_delete = True
                can_edit = True
                can_dispatch = True
            else:
                from dashboard.models import DashboardSecurityConfig
                cfg = DashboardSecurityConfig.get_config()
                strict_admin_only_delete = cfg.strict_admin_only_delete
                strict_admin_only_edit = cfg.strict_admin_only_edit
                strict_admin_only_dispatch = cfg.strict_admin_only_dispatch

                profile = getattr(user, 'security_profile', None)

                # Delete permission
                if not cfg.strict_admin_only_delete and cfg.allow_staff_delete_override:
                    if profile and profile.can_delete_records:
                        can_delete = True

                # Edit permission
                if not cfg.strict_admin_only_edit:
                    can_edit = profile.can_edit_records if profile else True

                # Dispatch permission
                if not cfg.strict_admin_only_dispatch:
                    can_dispatch = profile.can_dispatch_courier if profile else True
    except Exception:
        pass

    base_context = {
        'site_categories': Category.objects.all() if 'Category' in locals() or 'Category' in globals() else [],
        'STATIC_VERSION': static_version,
        'META_PIXEL_ID': meta_pixel_id,
        'meta_adv': meta_adv,
        'GOOGLE_ANALYTICS_ID': google_analytics_id,
        'CLOUDFLARE_TURNSTILE_SITE_KEY': cloudflare_turnstile_site_key,
        'global_trash_count': trash_orders_count,
        'pending_reviews_count': pending_reviews_count,
        'auto_whatsapp_url': auto_whatsapp_url,
        'auto_whatsapp_order_number': auto_whatsapp_order_number,
        'meta_pixel_purchase_events_json': meta_pixel_purchase_events_json,
        'can_delete': can_delete,
        'can_edit': can_edit,
        'can_dispatch': can_dispatch,
        'strict_admin_only_delete': strict_admin_only_delete,
        'strict_admin_only_edit': strict_admin_only_edit,
        'strict_admin_only_dispatch': strict_admin_only_dispatch,
        'is_admin_user': bool(getattr(request, 'user', None) and request.user.is_authenticated and request.user.is_superuser),
    }

    try:
        if not hasattr(request, 'session'):
            return {
                'cart': [],
                'cart_total_items': 0,
                'cart_subtotal': 0,
                'free_delivery_unlocked': False,
                'items_needed_for_free_delivery': 6,
                **base_context,
            }
        cart = Cart(request)
        return {
            'cart': cart,
            'cart_total_items': len(cart),
            'cart_subtotal': cart.get_subtotal(),
            'free_delivery_unlocked': cart.is_free_delivery(),
            'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
            **base_context,
        }
    except Exception:
        return {
            'cart': [],
            'cart_total_items': 0,
            'cart_subtotal': 0,
            'free_delivery_unlocked': False,
            'items_needed_for_free_delivery': 6,
            **base_context,
        }
