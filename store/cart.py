from decimal import Decimal
from django.conf import settings
from .models import Product


class Cart:
    def __init__(self, request):
        self.session = request.session
        cart = self.session.get('pickpickles_cart')
        if not cart:
            cart = self.session['pickpickles_cart'] = {}
        self.cart = cart

    def add(self, product, quantity=1, override_quantity=False):
        product_id = str(product.id)
        if product_id not in self.cart:
            self.cart[product_id] = {
                'quantity': 0,
                'price': str(product.price_bdt),
                'name': product.name,
                'weight': product.jar_weight_grams,
                'image': product.primary_image_url,
                'slug': product.slug,
            }

        if override_quantity:
            self.cart[product_id]['quantity'] = quantity
        else:
            self.cart[product_id]['quantity'] += quantity

        if self.cart[product_id]['quantity'] <= 0:
            self.remove(product)
        else:
            self.save()

    def remove(self, product):
        product_id = str(product.id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def save(self):
        self.session.modified = True

    def clear(self):
        del self.session['pickpickles_cart']
        self.save()

    def __iter__(self):
        product_ids = [k for k in self.cart.keys()]
        products = Product.objects.filter(id__in=product_ids)
        product_map = {str(p.id): p for p in products}

        for product_id, item_data in self.cart.items():
            if product_id in product_map:
                item = item_data.copy()
                item['product'] = product_map[product_id]
                item['price'] = Decimal(str(item_data['price']))
                item['total_price'] = item['price'] * item['quantity']
                yield item

    def __len__(self):
        return sum(int(item.get('quantity', 0)) for item in self.cart.values())

    def get_subtotal(self):
        return sum(Decimal(str(item.get('price', '0'))) * int(item.get('quantity', 0)) for item in self.cart.values())

    def get_delivery_fee(self, zone='INSIDE_DHAKA'):
        return Decimal('130.00')

    def get_total_price(self, zone='INSIDE_DHAKA'):
        return self.get_subtotal() + self.get_delivery_fee(zone)
