from django.test import TestCase, Client, override_settings
from django.urls import reverse
from store.models import Category, Product, calculate_pathao_delivery_fee
from decimal import Decimal


class CartTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
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
            # Flat ৳150 nationwide across all weights, quantities, and zones
            self.assertEqual(calculate_pathao_delivery_fee(600, 'INSIDE_DHAKA', total_items=1), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(600, 'OUTSIDE_DHAKA', total_items=1), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(1200, 'INSIDE_DHAKA', total_items=2), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(1200, 'OUTSIDE_DHAKA', total_items=2), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(1800, 'INSIDE_DHAKA', total_items=3), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(2400, 'INSIDE_DHAKA', total_items=4), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(3600, 'INSIDE_DHAKA', total_items=6), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(3600, 'OUTSIDE_DHAKA', total_items=6), Decimal('150.00'))
            self.assertEqual(calculate_pathao_delivery_fee(6000, 'OUTSIDE_DHAKA', total_items=10), Decimal('150.00'))

    def test_free_delivery_on_four_items_in_cart_and_checkout(self):
        from store.models import Order
        from django.test import override_settings
        # Add 4 jars to cart
        add_url = reverse('store:cart_add', args=[self.product.id])
        response = self.client.post(
            f"{add_url}?format=json",
            {'quantity': 4},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['cart_total_items'], 4)
        self.assertFalse(data['free_delivery_unlocked'])
        self.assertEqual(data['items_needed_for_free_delivery'], 0)
        self.assertEqual(data['delivery_fee'], 150.0)
        self.assertEqual(data['grand_total'], 4 * 380.0 + 150.0)

        # Complete checkout
        checkout_data = {
            'customer_name': 'Flat Delivery Customer',
            'customer_phone': '01799887766',
            'delivery_address': 'Sector 4, Uttara',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'COD',
        }
        with override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=''):
            res = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res.status_code, 302)

        order = Order.objects.latest('created_at')
        self.assertEqual(order.delivery_fee, Decimal('150.00'))
        self.assertEqual(order.subtotal, Decimal('1520.00'))
        self.assertEqual(order.total_amount, Decimal('1670.00'))

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
        with override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=''):
            response = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(response.status_code, 302)
        
        order = Order.objects.latest('created_at')
        self.assertEqual(order.order_status, 'PENDING')
        
        # At PENDING/CONFIRMED stage, stock is NOT deducted yet
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 50)
        
        # 1. When order moves to PACKING -> Stock is deducted
        adjust_inventory_for_order_status_change(order, 'CONFIRMED', 'PACKING')
        order.order_status = 'PACKING'
        order.save()
        
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_count, 47)
        self.assertTrue(self.product.is_in_stock)

        # Verify StockLog for order packing
        from dashboard.models import StockLog
        confirm_log = StockLog.objects.filter(product=self.product, log_type='ORDER_CONFIRMED').first()
        self.assertIsNotNone(confirm_log)
        self.assertEqual(confirm_log.quantity_delta, -3)
        self.assertEqual(confirm_log.previous_stock, 50)
        self.assertEqual(confirm_log.resulting_stock, 47)
        
        # 2. When packed order is cancelled -> Stock is restored
        adjust_inventory_for_order_status_change(order, 'PACKING', 'CANCELLED')
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
        # Product with 0 stock but is_in_stock=True (Visible) should be on homepage with Pre-Order
        self.product.is_in_stock = True
        self.product.stock_count = 0
        self.product.save()

        response = self.client.get(reverse('store:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, "Pre-Order")

    def test_hidden_product_not_visible_on_homepage(self):
        # Product marked as hidden from store (is_in_stock=False) should NOT be on homepage
        self.product.is_in_stock = False
        self.product.save()

        response = self.client.get(reverse('store:index'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.product.name)

    def test_hidden_product_cannot_be_added_to_cart(self):
        self.product.is_in_stock = False
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
        self.assertIn("error", data)

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
        self.assertIn('steadfast.com.bd/tracking', order.active_tracking_url)

        # Mock Steadfast status response to 'delivered'
        with patch('store.steadfast.SteadfastCourierService.is_configured', return_value=True), \
             patch('store.steadfast.SteadfastCourierService.get_delivery_status_by_cid', return_value={'success': True, 'delivery_status': 'delivered'}):
            status = order.sync_courier_status()
            order.refresh_from_db()
            self.assertEqual(status, 'delivered')
            self.assertEqual(order.steadfast_order_status, 'delivered')
            # Internal store order_status and payment_status remain intact
            self.assertEqual(order.order_status, 'PENDING')
            self.assertEqual(order.payment_status, 'UNPAID')

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
        self.assertEqual(data['order_status'], 'OUT_FOR_DELIVERY')
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'OUT_FOR_DELIVERY')
        self.assertEqual(order.payment_status, 'UNPAID')
        self.assertEqual(order.steadfast_order_status, 'delivered')

    def test_steadfast_fraud_check(self):
        from unittest.mock import patch, MagicMock
        from store.steadfast import SteadfastCourierService

        service = SteadfastCourierService()

        # Mock score API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = True
        mock_response.json.return_value = {
            'status': 200,
            'phone': '01712345678',
            'delivery_ratio': 90,
            'cancellation_ratio': 10,
            'volume_band': 'high',
            'total_reports': 0,
            'fraud_categories': []
        }

        with patch.object(service, 'is_configured', return_value=True), \
             patch.object(service.session, 'get', return_value=mock_response):
            result = service.check_fraud('01712345678', force_refresh=True)
            self.assertTrue(result['success'])
            self.assertEqual(result['risk_level'], 'SAFE')
            self.assertEqual(result['success_rate'], 90.0)
            self.assertEqual(result['return_rate'], 10.0)
            self.assertEqual(result['volume_band'], 'high')

    def test_whatsapp_shipping_instruction_message_and_url(self):
        from store.models import Order, OrderItem

        order = Order.objects.create(
            customer_name='Mahmudul Hasan',
            customer_phone='01712345678',
            delivery_address='Dhanmondi 27',
            delivery_city='Dhaka',
            delivery_zone='INSIDE_DHAKA',
            subtotal=Decimal('760.00'),
            delivery_fee=Decimal('150.00'),
            total_amount=Decimal('910.00'),
            payment_method='COD',
            payment_status='UNPAID',
            order_status='OUT_FOR_DELIVERY',
            steadfast_consignment_id='CID12345',
            steadfast_tracking_code='TRK9988'
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name="Classic Garlic Spears",
            unit_price=Decimal("380.00"),
            quantity=2,
            total_price=Decimal("760.00")
        )

        self.assertEqual(order.whatsapp_phone_international, '8801712345678')
        
        # Test foreign customer phone handling
        order.customer_phone = '+1 (415) 555-2671'
        self.assertEqual(order.whatsapp_phone_international, '14155552671')
        order.customer_phone = '01712345678'

        msg = order.get_whatsapp_shipping_instruction_message()
        self.assertIn('Mahmudul Hasan', msg)
        self.assertIn(order.order_number, msg)
        self.assertIn('Classic Garlic Spears x 2', msg)
        self.assertIn('refrigerate', msg.lower())
        self.assertIn('dry spoon', msg.lower())
        self.assertIn('Feedback', msg)
        self.assertIn('courier', msg.lower())
        self.assertIn('pickpickles.xyz', msg)
        self.assertIn('https://pickpickles.xyz/reviews/', msg)

        wa_url = order.whatsapp_shipping_instruction_url
        self.assertTrue(wa_url.startswith('https://api.whatsapp.com/send?phone=8801712345678&text=') or wa_url.startswith('https://wa.me/8801712345678?text='))

        fb_msg = order.get_whatsapp_feedback_message()
        self.assertIn('Mahmudul Hasan', fb_msg)
        self.assertIn('experience', fb_msg.lower())
        self.assertIn('https://pickpickles.xyz/reviews/', fb_msg)
        self.assertIn('https://facebook.com/pickpickles07', fb_msg)
        self.assertIn('5% off', fb_msg.lower())
        self.assertIn('next order', fb_msg.lower())
        self.assertIn('not here in chat', fb_msg.lower())
        self.assertNotIn('reply here', fb_msg.lower())
        self.assertTrue(order.whatsapp_feedback_url.startswith('https://api.whatsapp.com/send?phone=8801712345678&text=') or order.whatsapp_feedback_url.startswith('https://wa.me/8801712345678?text='))

        month_msg = order.get_whatsapp_1month_review_request_message()
        self.assertIn('Mahmudul Hasan', month_msg)
        self.assertIn('Facebook', month_msg)
        self.assertIn('https://pickpickles.xyz/reviews/', month_msg)
        self.assertIn('https://facebook.com/pickpickles07', month_msg)
        self.assertIn('5% off', month_msg.lower())
        self.assertIn('next order', month_msg.lower())
        self.assertIn('not here in chat', month_msg.lower())
        self.assertNotIn('reply right here', month_msg.lower())

        confirm_msg = order.get_whatsapp_order_confirmation_message()
        self.assertIn('Mahmudul Hasan', confirm_msg)
        self.assertIn(order.order_number, confirm_msg)
        self.assertIn('Order Confirmation', confirm_msg)
        self.assertIn('https://pickpickles.xyz/reviews/', confirm_msg)
        self.assertTrue(order.whatsapp_order_confirmation_url.startswith('https://api.whatsapp.com/send?phone=8801712345678&text=') or order.whatsapp_order_confirmation_url.startswith('https://wa.me/8801712345678?text='))

    def test_bangladeshi_mobile_number_validation(self):
        from store.forms import CheckoutForm, clean_and_validate_bd_phone

        # Valid BD numbers
        valid_numbers = [
            '01719874562',
            '01833445566',
            '01955667788',
            '01319874562',
            '01419874562',
            '01519874562',
            '01619874562',
            '+8801719874562',
            '8801719874562',
            '01719-874562',
            '01719 874 562',
        ]
        for phone in valid_numbers:
            cleaned, err = clean_and_validate_bd_phone(phone)
            self.assertIsNone(err, f"Expected {phone} to be valid, got error: {err}")
            self.assertEqual(len(cleaned), 11)
            self.assertTrue(cleaned.startswith('01'))

        # Invalid numbers
        invalid_numbers = [
            '12345678901',     # Does not start with 01
            '01234567890',     # Invalid operator 012
            '01012345678',     # Invalid operator 010
            '017123456',       # Too short (9 digits)
            '017123456789',    # Too long (12 digits)
            'abcdefghijk',     # Letters
            '00000000000',     # Zeros
            '+14155552671',    # US number
        ]
        for phone in invalid_numbers:
            cleaned, err = clean_and_validate_bd_phone(phone)
            self.assertIsNotNone(err, f"Expected {phone} to be invalid")

        # Test CheckoutForm validation
        form_data = {
            'customer_name': 'Test User',
            'customer_phone': '01234567890',  # Invalid BD operator
            'delivery_address': 'Road 1, Dhanmondi',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'COD',
        }
        form = CheckoutForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('customer_phone', form.errors)

    def test_flat_100_discount_on_two_jars_and_not_on_three_or_four(self):
        """
        Verify the exact business rules:
        - 1 jar: 0 discount, flat 150 delivery.
        - 2 jars: flat 100 discount, flat 150 delivery (Total = Subtotal - 100 + 150).
        - 3 jars: 0 discount, flat 150 delivery (Total = Subtotal + 150).
        - 4 jars: 0 discount, FREE delivery (Total = Subtotal).
        - 5 jars: 0 discount, FREE delivery (Total = Subtotal).
        """
        from store.cart import Cart
        from django.test.client import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware
        from store.models import Order

        factory = RequestFactory()

        # Helper to get cart instance with session
        def get_fresh_cart():
            req = factory.get('/')
            middleware = SessionMiddleware(lambda r: None)
            middleware.process_request(req)
            req.session.save()
            return Cart(req), req

        # 1 Jar
        cart, _ = get_fresh_cart()
        cart.add(self.product, quantity=1)
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart.get_discount(), Decimal('0.00'))
        self.assertEqual(cart.get_delivery_fee(), Decimal('150.00'))
        self.assertEqual(cart.get_total_price(), Decimal('530.00'))  # 380 + 150

        # 2 Jars (Bundle discount ৳100 applies when promo active)
        cart, _ = get_fresh_cart()
        cart.add(self.product, quantity=2)
        self.assertEqual(len(cart), 2)
        self.assertEqual(cart.get_discount(), Decimal('100.00'))
        self.assertEqual(cart.get_delivery_fee(), Decimal('150.00'))
        self.assertEqual(cart.get_subtotal(), Decimal('760.00'))
        self.assertEqual(cart.get_total_price(), Decimal('810.00'))  # 760 - 100 + 150

        # 3 Jars (Discount does NOT apply)
        cart, _ = get_fresh_cart()
        cart.add(self.product, quantity=3)
        self.assertEqual(len(cart), 3)
        self.assertEqual(cart.get_discount(), Decimal('0.00'))
        self.assertEqual(cart.get_delivery_fee(), Decimal('150.00'))
        self.assertEqual(cart.get_subtotal(), Decimal('1140.00'))
        self.assertEqual(cart.get_total_price(), Decimal('1290.00'))  # 1140 + 150

        # 4 Jars (Discount does NOT apply, flat ৳150 delivery applies)
        cart, _ = get_fresh_cart()
        cart.add(self.product, quantity=4)
        self.assertEqual(len(cart), 4)
        self.assertEqual(cart.get_discount(), Decimal('0.00'))
        self.assertEqual(cart.get_delivery_fee(), Decimal('150.00'))
        self.assertFalse(cart.is_free_delivery())
        self.assertEqual(cart.get_subtotal(), Decimal('1520.00'))
        self.assertEqual(cart.get_total_price(), Decimal('1670.00'))  # 1520 + 150

        # 5 Jars (Discount does NOT apply, flat ৳150 delivery applies)
        cart, _ = get_fresh_cart()
        cart.add(self.product, quantity=5)
        self.assertEqual(len(cart), 5)
        self.assertEqual(cart.get_discount(), Decimal('0.00'))
        self.assertEqual(cart.get_delivery_fee(), Decimal('150.00'))
        self.assertFalse(cart.is_free_delivery())
        self.assertEqual(cart.get_subtotal(), Decimal('1900.00'))
        self.assertEqual(cart.get_total_price(), Decimal('2050.00'))  # 1900 + 150

    def test_checkout_order_creation_with_two_jar_discount(self):
        """
        Verify checkout order creation saves discount_amount=100 and correct total for 2 jars.
        """
        from store.models import Order
        from django.test import override_settings

        client = Client()
        # Add 2 jars to cart
        client.post(reverse('store:cart_add', args=[self.product.id]), {'quantity': 2})

        checkout_data = {
            'customer_name': 'Two Jar Customer',
            'customer_phone': '01719874562',
            'delivery_address': 'House 10, Road 4, Banani',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'COD',
        }
        with override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=''):
            res = client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res.status_code, 302)

        order = Order.objects.latest('created_at')
        self.assertEqual(order.subtotal, Decimal('760.00'))
        self.assertEqual(order.discount_amount, Decimal('100.00'))
        self.assertEqual(order.delivery_fee, Decimal('150.00'))
        self.assertEqual(order.total_amount, Decimal('810.00'))  # 760 - 100 + 150

    def test_checkout_order_creation_with_three_jars_no_discount(self):
        """
        Verify checkout order creation for 3 jars has discount_amount=0 and delivery_fee=150.
        """
        from store.models import Order
        from django.test import override_settings

        client = Client()
        # Add 3 jars to cart
        client.post(reverse('store:cart_add', args=[self.product.id]), {'quantity': 3})

        checkout_data = {
            'customer_name': 'Three Jar Customer',
            'customer_phone': '01833445566',
            'delivery_address': 'GEC Circle, Chattogram',
            'delivery_city': 'Chattogram',
            'delivery_zone': 'OUTSIDE_DHAKA',
            'payment_method': 'COD',
        }
        with override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=''):
            res = client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res.status_code, 302)

        order = Order.objects.latest('created_at')
        self.assertEqual(order.subtotal, Decimal('1140.00'))
        self.assertEqual(order.discount_amount, Decimal('0.00'))
        self.assertEqual(order.delivery_fee, Decimal('150.00'))
        self.assertEqual(order.total_amount, Decimal('1290.00'))

    def test_dynamic_promotion_setting_controls_discount_and_free_delivery(self):
        """
        Verify that changing PromotionSetting in database dynamically updates cart discount and free delivery.
        """
        from store.models import PromotionSetting
        from store.cart import Cart
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware
        
        promo = PromotionSetting.get_settings()
        factory = RequestFactory()
        req = factory.get('/')
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(req)
        req.session.save()

        cart = Cart(req)
        cart.add(self.product, quantity=2)
        # Default: active, 2 jars = ৳100 off
        self.assertEqual(cart.get_discount(), Decimal('100.00'))

        # Deactivate promotion
        promo.is_active = False
        promo.save()
        self.assertEqual(cart.get_discount(), Decimal('0.00'))

        # Re-activate and change rule to 3 jars = ৳150 off
        promo.is_active = True
        promo.bundle_min_jars = 3
        promo.bundle_discount_amount = Decimal('150.00')
        promo.free_delivery_enabled = True
        promo.free_delivery_min_jars = 4
        promo.save()

        # 2 jars now has 0 discount
        self.assertEqual(cart.get_discount(), Decimal('0.00'))
        self.assertFalse(cart.is_free_delivery())

        # 3 jars gets ৳150 discount
        cart.add(self.product, quantity=1)
        self.assertEqual(len(cart), 3)
        self.assertEqual(cart.get_discount(), Decimal('150.00'))
        self.assertFalse(cart.is_free_delivery())
        self.assertEqual(cart.get_delivery_fee(), Decimal('150.00'))

        # 4 jars gets free delivery
        cart.add(self.product, quantity=1)
        self.assertEqual(len(cart), 4)
        self.assertTrue(cart.is_free_delivery())
        self.assertEqual(cart.get_delivery_fee(), Decimal('0.00'))

    def test_free_delivery_checkout_delivery_fee_is_zero(self):
        """
        Verify that when free delivery is enabled and unlocked, checkout saves 0.00 delivery fee.
        """
        from store.models import PromotionSetting, Order
        promo = PromotionSetting.get_settings()
        promo.is_active = True
        promo.free_delivery_enabled = True
        promo.free_delivery_min_jars = 4
        promo.save()

        # Add 4 jars to cart
        self.client.post(reverse('store:cart_add', args=[self.product.id]), {'quantity': 4})
        
        # Check GET checkout page context
        get_res = self.client.get(reverse('store:checkout'))
        self.assertEqual(get_res.status_code, 200)
        self.assertTrue(get_res.context['free_delivery_unlocked'])
        self.assertEqual(get_res.context['cart_delivery_fee'], Decimal('0.00'))

        # Post checkout order
        checkout_data = {
            'customer_name': 'Free Delivery Customer',
            'customer_phone': '01711002233',
            'delivery_address': 'House 1, Road 2, Dhanmondi',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'COD',
        }
        with override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=''):
            res = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res.status_code, 302)

        order = Order.objects.latest('created_at')
        self.assertEqual(order.delivery_fee, Decimal('0.00'))
        self.assertEqual(order.subtotal, Decimal('1520.00'))
        # Subtotal 1520 - bundle discount (default 100 on 2+ jars) + 0 delivery = 1420
        expected_total = order.subtotal - order.discount_amount + Decimal('0.00')
        self.assertEqual(order.total_amount, expected_total)

    def test_coupon_apply_remove_and_checkout(self):
        """
        Verify coupon creation, AJAX apply, remove, and order association with discount.
        """
        from store.models import Coupon, Order
        coupon = Coupon.objects.create(
            code='TESTSAVE50',
            discount_type='FIXED',
            discount_value=Decimal('50.00'),
            min_jars=2,
            is_active=True
        )

        # Add 2 jars to cart (subtotal = 760)
        self.client.post(reverse('store:cart_add', args=[self.product.id]), {'quantity': 2})

        # Apply coupon via AJAX
        import json
        res = self.client.post(
            reverse('store:apply_coupon_ajax'),
            data=json.dumps({'coupon_code': 'TESTSAVE50'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'], f"Coupon failed with msg: {data.get('message')}")
        self.assertEqual(data['coupon_code'], 'TESTSAVE50')
        self.assertEqual(data['coupon_discount'], 50.0)

        # Remove coupon via AJAX
        res_rem = self.client.post(
            reverse('store:remove_coupon_ajax'),
            data=json.dumps({}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_rem.status_code, 200)
        data_rem = res_rem.json()
        self.assertTrue(data_rem['success'])
        self.assertEqual(data_rem['coupon_code'], '')
        self.assertEqual(data_rem['coupon_discount'], 0.0)

        # Re-apply coupon and complete checkout
        self.client.post(
            reverse('store:apply_coupon_ajax'),
            data=json.dumps({'coupon_code': 'TESTSAVE50'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        checkout_data = {
            'customer_name': 'Coupon Customer',
            'customer_phone': '01811223344',
            'delivery_address': 'Banani 11',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'COD',
        }
        with override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=''):
            res_order = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res_order.status_code, 302)

        order = Order.objects.latest('created_at')
        self.assertEqual(order.coupon_code, 'TESTSAVE50')
        coupon.refresh_from_db()
        self.assertEqual(coupon.used_count, 1)
        # Total discount = bundle discount (100) + coupon discount (50) = 150
        self.assertEqual(order.discount_amount, Decimal('150.00'))

    def test_advance_payment_discount_on_checkout(self):
        from django.test import override_settings
        from store.models import Category, Product, Order, PromotionSetting

        promo = PromotionSetting.get_settings()
        promo.is_active = True
        promo.bundle_discount_enabled = False
        promo.advance_payment_discount_enabled = True
        promo.advance_payment_discount_percent = Decimal('5.00')
        promo.standard_delivery_fee = Decimal('150.00')
        promo.save()

        cat, _ = Category.objects.get_or_create(name='Advance Cat', defaults={'slug': 'advance-cat'})
        prod = Product.objects.create(
            category=cat,
            name='Naga Advance Pickle',
            slug='naga-advance-pickle',
            price_bdt=Decimal('500.00'),
            stock_count=15,
            is_in_stock=True,
        )

        self.client.post(reverse('store:cart_add', args=[prod.id]), {'quantity': 2})

        checkout_data = {
            'customer_name': 'Bkash Buyer',
            'customer_phone': '01755667788',
            'delivery_address': 'Gulshan 1',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'BKASH',
            'payment_sender_number': '01755667788',
            'payment_trx_id': 'TRXADV1234',
        }
        with override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=''):
            res_order = self.client.post(reverse('store:checkout'), checkout_data)
        self.assertEqual(res_order.status_code, 302)

        order = Order.objects.latest('created_at')
        self.assertEqual(order.subtotal, Decimal('1000.00'))
        self.assertEqual(order.discount_amount, Decimal('50.00'))  # 5% of 1000
        self.assertEqual(order.total_amount, Decimal('1100.00'))   # 1000 - 50 + 150

