import time
from django.conf import settings
from .cart import Cart
from .models import Category

# Cached server start time for production
_SERVER_START_TIME = int(time.time())


def cart_context(request):
    # Dynamic timestamp in development for instant reload, server start time in production
    static_version = int(time.time()) if getattr(settings, 'DEBUG', False) else _SERVER_START_TIME
    meta_pixel_id = getattr(settings, 'META_PIXEL_ID', '')
    
    try:
        if not hasattr(request, 'session'):
            return {
                'cart': [],
                'cart_total_items': 0,
                'cart_subtotal': 0,
                'site_categories': [],
                'STATIC_VERSION': static_version,
                'META_PIXEL_ID': meta_pixel_id,
            }
        cart = Cart(request)
        return {
            'cart': cart,
            'cart_total_items': len(cart),
            'cart_subtotal': cart.get_subtotal(),
            'site_categories': Category.objects.all(),
            'STATIC_VERSION': static_version,
            'META_PIXEL_ID': meta_pixel_id,
        }
    except Exception:
        return {
            'cart': [],
            'cart_total_items': 0,
            'cart_subtotal': 0,
            'site_categories': [],
            'STATIC_VERSION': static_version,
            'META_PIXEL_ID': meta_pixel_id,
        }
