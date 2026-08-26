from .cart import Cart
from .models import Category


def cart_context(request):
    cart = Cart(request)
    return {
        'cart': cart,
        'cart_total_items': len(cart),
        'cart_subtotal': cart.get_subtotal(),
        'site_categories': Category.objects.all(),
    }
