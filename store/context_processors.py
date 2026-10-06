import os
import time
from django.conf import settings
from .cart import Cart
from .models import Category


def _get_dynamic_static_version():
    """
    Returns the latest mtime of core static files so browsers instantly
    fetch updated CSS/JS whenever files are uploaded or modified,
    without requiring manual hard refreshes or cache clearing by clients.
    """
    try:
        latest_mtime = 0
        search_dirs = []
        
        # 1. Check STATICFILES_DIRS
        for d in getattr(settings, 'STATICFILES_DIRS', []):
            search_dirs.append(str(d))
            
        # 2. Check STATIC_ROOT
        sroot = getattr(settings, 'STATIC_ROOT', None)
        if sroot:
            search_dirs.append(str(sroot))
            
        # 3. Check BASE_DIR static & staticfiles
        bdir = getattr(settings, 'BASE_DIR', None)
        if bdir:
            search_dirs.append(os.path.join(str(bdir), 'static'))
            search_dirs.append(os.path.join(str(bdir), 'staticfiles'))

        for sdir in search_dirs:
            if not sdir or not os.path.exists(sdir):
                continue
            for fname in ['css/style.css', 'js/main.js']:
                fpath = os.path.join(sdir, fname)
                if os.path.isfile(fpath):
                    mtime = int(os.path.getmtime(fpath))
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        
        if latest_mtime > 0:
            return latest_mtime
    except Exception:
        pass
    return int(time.time())


def cart_context(request):
    static_version = _get_dynamic_static_version()
    meta_pixel_id = getattr(settings, 'META_PIXEL_ID', '')
    google_analytics_id = getattr(settings, 'GOOGLE_ANALYTICS_ID', '')
    cloudflare_turnstile_site_key = getattr(settings, 'CLOUDFLARE_TURNSTILE_SITE_KEY', '')
    
    trash_orders_count = 0
    try:
        if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
            from .models import Order
            trash_orders_count = Order.trash_objects.count()
    except Exception:
        trash_orders_count = 0
        
    auto_whatsapp_url = None
    auto_whatsapp_order_number = None
    if hasattr(request, 'session') and 'auto_whatsapp_url' in request.session:
        auto_whatsapp_url = request.session.pop('auto_whatsapp_url', None)
        auto_whatsapp_order_number = request.session.pop('auto_whatsapp_order_number', None)

    try:
        if not hasattr(request, 'session'):
            return {
                'cart': [],
                'cart_total_items': 0,
                'cart_subtotal': 0,
                'free_delivery_unlocked': False,
                'items_needed_for_free_delivery': 4,
                'site_categories': [],
                'STATIC_VERSION': static_version,
                'META_PIXEL_ID': meta_pixel_id,
                'GOOGLE_ANALYTICS_ID': google_analytics_id,
                'CLOUDFLARE_TURNSTILE_SITE_KEY': cloudflare_turnstile_site_key,
                'global_trash_count': trash_orders_count,
                'auto_whatsapp_url': auto_whatsapp_url,
                'auto_whatsapp_order_number': auto_whatsapp_order_number,
            }
        cart = Cart(request)
        return {
            'cart': cart,
            'cart_total_items': len(cart),
            'cart_subtotal': cart.get_subtotal(),
            'free_delivery_unlocked': cart.is_free_delivery(),
            'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
            'site_categories': Category.objects.all(),
            'STATIC_VERSION': static_version,
            'META_PIXEL_ID': meta_pixel_id,
            'GOOGLE_ANALYTICS_ID': google_analytics_id,
            'CLOUDFLARE_TURNSTILE_SITE_KEY': cloudflare_turnstile_site_key,
            'global_trash_count': trash_orders_count,
            'auto_whatsapp_url': auto_whatsapp_url,
            'auto_whatsapp_order_number': auto_whatsapp_order_number,
        }
    except Exception:
        return {
            'cart': [],
            'cart_total_items': 0,
            'cart_subtotal': 0,
            'free_delivery_unlocked': False,
            'items_needed_for_free_delivery': 4,
            'site_categories': [],
            'STATIC_VERSION': static_version,
            'META_PIXEL_ID': meta_pixel_id,
            'GOOGLE_ANALYTICS_ID': google_analytics_id,
            'CLOUDFLARE_TURNSTILE_SITE_KEY': cloudflare_turnstile_site_key,
            'global_trash_count': trash_orders_count,
            'auto_whatsapp_url': auto_whatsapp_url,
            'auto_whatsapp_order_number': auto_whatsapp_order_number,
        }

