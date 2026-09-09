from django.test import TestCase, Client
from django.urls import reverse
from store.models import Category, Product
from decimal import Decimal


class CartTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name="Classic Crisp", slug="classic-crisp")
        self.product = Product.objects.create(
            name="Classic Garlic Spears",
            slug="classic-garlic-spears",
            category=self.category,
            tagline="Crisp deli pickles",
            description="Garlic and herb spiced spears",
            price_bdt=Decimal("380.00"),
            jar_weight_grams=500,
            is_in_stock=True
        )

    def test_cart_add_ajax(self):
        url = reverse('store:cart_add', args=[self.product.id])
        response = self.client.post(
            f"{url}?format=json",
            {'quantity': 2},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['cart_total_items'], 2)
        self.assertEqual(data['cart_subtotal'], 760.0)

    def test_cart_update_ajax(self):
        # Add item first
        add_url = reverse('store:cart_add', args=[self.product.id])
        self.client.post(add_url, {'quantity': 1})

        # Update increase
        update_url = reverse('store:cart_update_ajax')
        response = self.client.post(
            update_url,
            {'product_id': self.product.id, 'action': 'increase'},
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['item_quantity'], 2)

    def test_stock_deduction_on_order_acceptance(self):
        from store.models import Order
        from dashboard.views import adjust_inventory_for_order_status_change
        
        # Initial stock count is default 50
        self.assertEqual(self.product.stock_count, 50)
        
        # Add 3 jars to cart and checkout
        self.client.post(reverse('store:cart_add', args=[self.product.id]), {'quantity': 3})
        checkout_data = {
            'customer_name': 'Sakib Al Hasan',
            'customer_phone': '01711223344',
            'customer_email': 'sakib@gmail.com',
            'delivery_address': 'House 10, Road 5, Mirpur DOHS',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'COD',
        }
        response = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(response.status_code, 302)
        
        order = Order.objects.latest('created_at')
        self.assertEqual(order.order_status, 'PENDING')
        
        # At PENDING stage, stock is NOT deducted yet
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 50)
        
        # 1. When staff accepts/confirms order -> Stock is deducted
        adjust_inventory_for_order_status_change(order, 'PENDING', 'CONFIRMED')
        order.order_status = 'CONFIRMED'
        order.save()
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 47)
        self.assertTrue(self.product.is_in_stock)
        
        # 2. When order is cancelled -> Stock is restored
        adjust_inventory_for_order_status_change(order, 'CONFIRMED', 'CANCELLED')
        order.order_status = 'CANCELLED'
        order.save()
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 50)
