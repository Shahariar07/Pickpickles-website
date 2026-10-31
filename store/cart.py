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

    def add(self, product, quantity=1, override_quantity=False, variant=None):
        variant = (variant or '').strip()
        cart_key = f"{product.id}_{variant}" if variant else str(product.id)
        display_name = f"{product.name} ({variant})" if variant else product.name

        if cart_key not in self.cart:
            self.cart[cart_key] = {
                'product_id': str(product.id),
                'quantity': 0,
                'price': str(product.price_bdt),
                'name': display_name,
                'variant': variant,
                'weight': product.jar_weight_grams or 600,
                'gross_weight': getattr(product, 'gross_weight_grams', 850) or 850,
                'image': product.primary_image_url,
                'slug': product.slug,
            }
        else:
            # Sync price & naming
            self.cart[cart_key]['price'] = str(product.price_bdt)
            self.cart[cart_key]['name'] = display_name
            self.cart[cart_key]['variant'] = variant
            self.cart[cart_key]['product_id'] = str(product.id)

        if override_quantity:
            self.cart[cart_key]['quantity'] = quantity
        else:
            self.cart[cart_key]['quantity'] += quantity

        # Update weights in session if product weight updated
        self.cart[cart_key]['weight'] = product.jar_weight_grams or 600
        self.cart[cart_key]['gross_weight'] = getattr(product, 'gross_weight_grams', 850) or 850

        if self.cart[cart_key]['quantity'] <= 0:
            self.remove(cart_key)
        else:
            self.save()

    def remove(self, product_or_key):
        if hasattr(product_or_key, 'id'):
            key = str(product_or_key.id)
        else:
            key = str(product_or_key)

        if key in self.cart:
            del self.cart[key]
            self.save()
        else:
            keys_to_remove = [k for k, v in self.cart.items() if k == key or str(v.get('product_id')) == key]
            if keys_to_remove:
                for k in keys_to_remove:
                    del self.cart[k]
                self.save()

    def clear(self):
        del self.session['pickpickles_cart']
        self.save()

    def save(self):
        self.session.modified = True

    def __iter__(self):
        product_ids = list({str(item_data.get('product_id', k.split('_')[0])) for k, item_data in self.cart.items()})
        products = Product.objects.filter(id__in=product_ids)
        product_map = {str(p.id): p for p in products}

        needs_save = False
        for cart_key, item_data in list(self.cart.items()):
            pid = str(item_data.get('product_id', cart_key.split('_')[0]))
            if pid in product_map:
                prod = product_map[pid]
                item = item_data.copy()
                item['key'] = cart_key
                item['product'] = prod
                live_price = prod.price_bdt
                item['price'] = live_price
                item['total_price'] = live_price * item['quantity']
                item['variant'] = item_data.get('variant', '')
                item['name'] = item_data.get('name') or (f"{prod.name} ({item['variant']})" if item['variant'] else prod.name)
                item['weight'] = prod.jar_weight_grams or 600
                item['net_weight'] = prod.jar_weight_grams or 600
                item['gross_weight'] = getattr(prod, 'gross_weight_grams', 850) or 850
                item['total_weight_grams'] = item['gross_weight'] * item['quantity']
                item['total_net_weight_grams'] = item['net_weight'] * item['quantity']
                item['total_gross_weight_grams'] = item['gross_weight'] * item['quantity']
                
                # Sync session if price in session was old
                if str(item_data.get('price')) != str(live_price):
                    self.cart[cart_key]['price'] = str(live_price)
                    needs_save = True

                yield item

        if needs_save:
            self.save()

    def __len__(self):
        return sum(int(item.get('quantity', 0)) for item in self.cart.values())

    def get_subtotal(self):
        product_ids = list({str(item_data.get('product_id', k.split('_')[0])) for k, item_data in self.cart.items()})
        products = Product.objects.filter(id__in=product_ids)
        product_map = {str(p.id): p for p in products}
        total = Decimal('0')
        for cart_key, item in self.cart.items():
            qty = int(item.get('quantity', 0))
            if qty <= 0:
                continue
            pid = str(item.get('product_id', cart_key.split('_')[0]))
            if pid in product_map:
                price = product_map[pid].price_bdt
            else:
                price = Decimal(str(item.get('price', '0')))
            total += price * qty
        return total

    def get_total_net_weight_grams(self):
        product_ids = list({str(item_data.get('product_id', k.split('_')[0])) for k, item_data in self.cart.items()})
        products = Product.objects.filter(id__in=product_ids)
        product_map = {str(p.id): p for p in products}
        
        total_grams = 0
        for cart_key, item in self.cart.items():
            qty = int(item.get('quantity', 0))
            if qty <= 0:
                continue
            pid = str(item.get('product_id', cart_key.split('_')[0]))
            if pid in product_map:
                w = product_map[pid].jar_weight_grams or 600
            else:
                w = int(item.get('weight', 600))
            total_grams += w * qty
        return total_grams

    def get_total_gross_weight_grams(self):
        product_ids = list({str(item_data.get('product_id', k.split('_')[0])) for k, item_data in self.cart.items()})
        products = Product.objects.filter(id__in=product_ids)
        product_map = {str(p.id): p for p in products}
        
        total_grams = 0
        for cart_key, item in self.cart.items():
            qty = int(item.get('quantity', 0))
            if qty <= 0:
                continue
            pid = str(item.get('product_id', cart_key.split('_')[0]))
            if pid in product_map:
                w = getattr(product_map[pid], 'gross_weight_grams', 850) or 850
            else:
                w = int(item.get('gross_weight', 850))
            total_grams += w * qty
        return total_grams

    def get_total_weight_grams(self):
        # Default delivery/parcel weight calculation uses gross weight (850g per jar)
        return self.get_total_gross_weight_grams()

    def get_total_weight_kg(self):
        return round(self.get_total_gross_weight_grams() / 1000.0, 2)

    def get_billing_weight_kg(self):
        total_g = self.get_total_gross_weight_grams()
        if total_g <= 0:
            return 1
        return max(1, math.ceil(total_g / 1000.0))

    def is_free_delivery(self):
        return len(self) >= 6

    def items_needed_for_free_delivery(self):
        return max(0, 6 - len(self))

    def get_delivery_fee(self, zone='INSIDE_DHAKA'):
        return calculate_pathao_delivery_fee(self.get_total_weight_grams(), zone, total_items=len(self))

    def get_total_price(self, zone='INSIDE_DHAKA'):
        return self.get_subtotal() + self.get_delivery_fee(zone)
