import os
import time
from django.conf import settings
from .cart import Cart
from .models import Category


def _get_dynamic_static_version():
    """
    Returns the latest mtime of core static files so browsers instantly
    fetch updated CSS/JS whenever files are uploaded or modified,
    without requiring manual hard refreshes or cache clearing.
    """
    try:
        latest_mtime = 0
        static_dirs = getattr(settings, 'STATICFILES_DIRS', [])
        for sdir in static_dirs:
            for fname in ['css/style.css', 'js/main.js']:
                fpath = os.path.join(sdir, fname)
                if os.path.exists(fpath):
                    latest_mtime = max(latest_mtime, int(os.path.getmtime(fpath)))
        if latest_mtime > 0:
            return latest_mtime
    except Exception:
        pass
    return int(time.time())


def cart_context(request):
    static_version = _get_dynamic_static_version()
    meta_pixel_id = getattr(settings, 'META_PIXEL_ID', '')
    google_analytics_id = getattr(settings, 'GOOGLE_ANALYTICS_ID', '')
    
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
                'site_categories': [],
                'STATIC_VERSION': static_version,
                'META_PIXEL_ID': meta_pixel_id,
                'GOOGLE_ANALYTICS_ID': google_analytics_id,
                'global_trash_count': trash_orders_count,
                'auto_whatsapp_url': auto_whatsapp_url,
                'auto_whatsapp_order_number': auto_whatsapp_order_number,
            }
        cart = Cart(request)
        return {
            'cart': cart,
            'cart_total_items': len(cart),
            'cart_subtotal': cart.get_subtotal(),
            'site_categories': Category.objects.all(),
            'STATIC_VERSION': static_version,
            'META_PIXEL_ID': meta_pixel_id,
            'GOOGLE_ANALYTICS_ID': google_analytics_id,
            'global_trash_count': trash_orders_count,
            'auto_whatsapp_url': auto_whatsapp_url,
            'auto_whatsapp_order_number': auto_whatsapp_order_number,
        }
    except Exception:
        return {
            'cart': [],
            'cart_total_items': 0,
            'cart_subtotal': 0,
            'site_categories': [],
            'STATIC_VERSION': static_version,
            'META_PIXEL_ID': meta_pixel_id,
            'GOOGLE_ANALYTICS_ID': google_analytics_id,
            'global_trash_count': trash_orders_count,
            'auto_whatsapp_url': auto_whatsapp_url,
            'auto_whatsapp_order_number': auto_whatsapp_order_number,
        }
