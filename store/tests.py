from django.test import TestCase, Client
from django.urls import reverse
from store.models import Category, Product, calculate_pathao_delivery_fee
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
            jar_weight_grams=600,
            is_in_stock=True
        )

    def test_pathao_delivery_fee_calculation(self):
        from django.test import override_settings

        with override_settings(PATHAO_CLIENT_ID=''):
            # Flat ৳150 nationwide across all weights and zones
            self.assertEqual(calculate_pathao_delivery_fee(600, 'INSIDE_DHAKA'), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(600, 'OUTSIDE_DHAKA'), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(1200, 'INSIDE_DHAKA'), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(1200, 'OUTSIDE_DHAKA'), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(1800, 'INSIDE_DHAKA'), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(2400, 'OUTSIDE_DHAKA'), Decimal('150.00'))

    def test_pathao_service_structure(self):
        from store.pathao import PathaoCourierService
        from django.test import override_settings

        with override_settings(PATHAO_CLIENT_ID='', PATHAO_CLIENT_SECRET=''):
            service = PathaoCourierService()
            self.assertFalse(service.is_configured())
            self.assertIsNone(service.calculate_price(1.2))

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
        
        # At PENDING/CONFIRMED stage, stock is NOT deducted yet (physical inventory model)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 50)
        
        # 1. When order is dispatched/shipped to courier (OUT_FOR_DELIVERY) -> Stock is deducted
        adjust_inventory_for_order_status_change(order, 'CONFIRMED', 'OUT_FOR_DELIVERY')
        order.order_status = 'OUT_FOR_DELIVERY'
        order.save()
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 47)
        self.assertTrue(self.product.is_in_stock)

        # Verify StockLog for order dispatch
        from dashboard.models import StockLog
        confirm_log = StockLog.objects.filter(product=self.product, log_type='ORDER_CONFIRMED').first()
        self.assertIsNotNone(confirm_log)
        self.assertEqual(confirm_log.quantity_delta, -3)
        self.assertEqual(confirm_log.previous_stock, 50)
        self.assertEqual(confirm_log.resulting_stock, 47)
        
        # 2. When dispatched order is cancelled -> Stock is restored
        adjust_inventory_for_order_status_change(order, 'OUT_FOR_DELIVERY', 'CANCELLED')
        order.order_status = 'CANCELLED'
        order.save()
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 50)

        # Verify StockLog for order cancellation
        cancel_log = StockLog.objects.filter(product=self.product, log_type='ORDER_CANCELLED').first()
        self.assertIsNotNone(cancel_log)
        self.assertEqual(cancel_log.quantity_delta, 3)
        self.assertEqual(cancel_log.previous_stock, 47)
        self.assertEqual(cancel_log.resulting_stock, 50)

    def test_out_of_stock_product_visible_on_homepage(self):
        # Mark product as out of stock
        self.product.is_in_stock = False
        self.product.stock_count = 0
        self.product.save()

        response = self.client.get(reverse('store:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, "Stock Out")

    def test_out_of_stock_cannot_be_added_to_cart(self):
        self.product.is_in_stock = False
        self.product.stock_count = 0
        self.product.save()

        url = reverse('store:cart_add', args=[self.product.id])
        response = self.client.post(
            f"{url}?format=json",
            {'quantity': 1},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn("out of stock", data['message'].lower())

    def test_steadfast_service_structure(self):
        from store.steadfast import SteadfastCourierService
        from django.test import override_settings

        with override_settings(STEADFAST_API_KEY='', STEADFAST_SECRET_KEY=''):
            service = SteadfastCourierService()
            self.assertFalse(service.is_configured())

    def test_steadfast_order_properties_and_sync(self):
        from store.models import Order
        from unittest.mock import patch

        order = Order.objects.create(
            customer_name='Rahim Uddin',
            customer_phone='01712345678',
            delivery_address='House 12, Road 4, Dhanmondi',
            delivery_city='Dhaka',
            delivery_zone='INSIDE_DHAKA',
            subtotal=Decimal('380.00'),
            delivery_fee=Decimal('150.00'),
            total_amount=Decimal('530.00'),
            payment_method='COD',
            payment_status='UNPAID',
            steadfast_consignment_id='1424107',
            steadfast_tracking_code='15BAEB8A',
            steadfast_order_status='in_review'
        )

        self.assertEqual(order.active_courier, 'STEADFAST')
        self.assertEqual(order.active_courier_name, 'Steadfast Courier')
        self.assertEqual(order.active_consignment_id, '1424107')
        self.assertEqual(order.active_tracking_code, '15BAEB8A')
        self.assertIn('steadfast.com.bd/tracking/15BAEB8A', order.active_tracking_url)

        # Mock Steadfast status response to 'delivered'
        with patch('store.steadfast.SteadfastCourierService.is_configured', return_value=True), \
             patch('store.steadfast.SteadfastCourierService.get_delivery_status_by_cid', return_value={'success': True, 'delivery_status': 'delivered'}):
            status = order.sync_courier_status()
            order.refresh_from_db()
            self.assertEqual(status, 'delivered')
            self.assertEqual(order.order_status, 'DELIVERED')
            self.assertEqual(order.payment_status, 'PAID')

    def test_steadfast_webhook(self):
        from store.models import Order
        import json

        order = Order.objects.create(
            customer_name='Karim Mia',
            customer_phone='01812345678',
            delivery_address='Zindabazar',
            delivery_city='Sylhet',
            delivery_zone='OUTSIDE_DHAKA',
            subtotal=Decimal('760.00'),
            delivery_fee=Decimal('150.00'),
            total_amount=Decimal('910.00'),
            payment_method='COD',
            payment_status='UNPAID',
            steadfast_consignment_id='998877',
            steadfast_tracking_code='SF998877',
            steadfast_order_status='in_transit',
            order_status='OUT_FOR_DELIVERY'
        )

        webhook_url = reverse('store:steadfast_webhook')
        payload = {
            'consignment_id': '998877',
            'invoice': order.order_number,
            'tracking_code': 'SF998877',
            'delivery_status': 'delivered'
        }

        response = self.client.post(webhook_url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['order_status'], 'DELIVERED')
        self.assertEqual(data['payment_status'], 'PAID')

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'DELIVERED')
        self.assertEqual(order.payment_status, 'PAID')
        self.assertEqual(order.steadfast_order_status, 'delivered')
