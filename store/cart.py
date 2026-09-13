import math
from decimal import Decimal
from django.conf import settings
from .models import Product, calculate_pathao_delivery_fee


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
                'weight': product.jar_weight_grams or 600,
                'image': product.primary_image_url,
                'slug': product.slug,
            }

        if override_quantity:
            self.cart[product_id]['quantity'] = quantity
        else:
            self.cart[product_id]['quantity'] += quantity

        # Update weight in session if product weight updated
        self.cart[product_id]['weight'] = product.jar_weight_grams or 600

        if self.cart[product_id]['quantity'] <= 0:
            self.remove(product)
        else:
            self.save()

    def remove(self, product):
        product_id = str(product.id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def clear(self):
        del self.session['pickpickles_cart']
        self.save()

    def save(self):
        self.session.modified = True

    def __iter__(self):
        product_ids = [k for k in self.cart.keys()]
        products = Product.objects.filter(id__in=product_ids)
        product_map = {str(p.id): p for p in products}

        for product_id, item_data in self.cart.items():
            if product_id in product_map:
                prod = product_map[product_id]
                item = item_data.copy()
                item['product'] = prod
                item['price'] = Decimal(str(item_data['price']))
                item['total_price'] = item['price'] * item['quantity']
                item['weight'] = prod.jar_weight_grams or 600
                item['total_weight_grams'] = item['weight'] * item['quantity']
                yield item

    def __len__(self):
        return sum(int(item.get('quantity', 0)) for item in self.cart.values())

    def get_subtotal(self):
        return sum(Decimal(str(item.get('price', '0'))) * int(item.get('quantity', 0)) for item in self.cart.values())

    def get_total_weight_grams(self):
        product_ids = [k for k in self.cart.keys()]
        products = Product.objects.filter(id__in=product_ids)
        product_map = {str(p.id): p for p in products}
        
        total_grams = 0
        for product_id, item in self.cart.items():
            qty = int(item.get('quantity', 0))
            if qty <= 0:
                continue
            if product_id in product_map:
                w = product_map[product_id].jar_weight_grams or 600
            else:
                w = int(item.get('weight', 600))
            total_grams += w * qty
        return total_grams

    def get_total_weight_kg(self):
        return round(self.get_total_weight_grams() / 1000.0, 2)

    def get_billing_weight_kg(self):
        total_g = self.get_total_weight_grams()
        if total_g <= 0:
            return 1
        return max(1, math.ceil(total_g / 1000.0))

    def get_delivery_fee(self, zone='INSIDE_DHAKA'):
        return calculate_pathao_delivery_fee(self.get_total_weight_grams(), zone)

    def get_total_price(self, zone='INSIDE_DHAKA'):
        return self.get_subtotal() + self.get_delivery_fee(zone)
