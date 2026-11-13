from django.test import TestCase, Client, override_settings
from django.core.cache import cache
from django.urls import reverse
from django.contrib.auth.models import User
from decimal import Decimal
from unittest.mock import patch
from store.models import PromotionSetting


class OfferManagerDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@pickpickles.com',
            password='testpassword123'
        )
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@pickpickles.com',
            password='testpassword123',
            is_staff=True
        )
        self.view_only_user = User.objects.create_user(
            username='mitu',
            email='mitu@pickpickles.com',
            password='testpassword123',
            is_staff=True
        )

    def test_anonymous_redirected_to_login(self):
        res = self.client.get(reverse('dashboard:offer_manager'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('dashboard:login'), res.url)

    def test_superuser_can_access_offer_manager(self):
        self.client.login(username='admin', password='testpassword123')
        res = self.client.get(reverse('dashboard:offer_manager'))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'dashboard/offer_manager.html')
        self.assertContains(res, 'Offers & Campaign Manager')

    def test_superuser_can_save_offer_settings(self):
        self.client.login(username='admin', password='testpassword123')
        post_data = {
            'is_active': '1',
            'campaign_name': 'Ramadan Special Offer',
            'hero_badge_enabled': '1',
            'hero_badge_text': '🌙 3 Jars Flat ৳120 OFF',
            'announcement_bar_enabled': '1',
            'announcement_bar_text': '🌙 Ramadan Festival: 3 Jars Flat ৳120 OFF!',
            'bundle_discount_enabled': '1',
            'bundle_min_jars': '3',
            'bundle_discount_amount': '120.00',
            'bundle_discount_label': 'Ramadan 3-Jar ৳120 OFF',
            'bundle_apply_mode': 'EXACT',
            'standard_delivery_fee': '150.00',
            'free_delivery_enabled': '1',
            'free_delivery_min_jars': '5',
            'delivery_notice_text': 'Flat ৳150 nationwide delivery across Bangladesh.',
        }
        res = self.client.post(reverse('dashboard:offer_manager'), post_data)
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('dashboard:offer_manager'))

        promo = PromotionSetting.get_settings()
        self.assertTrue(promo.is_active)
        self.assertEqual(promo.campaign_name, 'Ramadan Special Offer')
        self.assertEqual(promo.hero_badge_text, '🌙 3 Jars Flat ৳120 OFF')
        self.assertTrue(promo.hero_badge_enabled)
        self.assertEqual(promo.announcement_bar_text, '🌙 Ramadan Festival: 3 Jars Flat ৳120 OFF!')
        self.assertTrue(promo.bundle_discount_enabled)
        self.assertEqual(promo.bundle_min_jars, 3)
        self.assertEqual(promo.bundle_discount_amount, Decimal('120.00'))
        self.assertEqual(promo.bundle_apply_mode, 'EXACT')
        self.assertTrue(promo.free_delivery_enabled)
        self.assertEqual(promo.free_delivery_min_jars, 5)

    def test_view_only_user_cannot_save_settings(self):
        self.client.login(username='mitu', password='testpassword123')
        post_data = {
            'is_active': '0',
            'campaign_name': 'Hacked',
        }
        res = self.client.post(reverse('dashboard:offer_manager'), post_data)
        self.assertEqual(res.status_code, 302)
        
        promo = PromotionSetting.get_settings()
        self.assertNotEqual(promo.campaign_name, 'Hacked')

    def test_coupon_management_in_dashboard(self):
        from store.models import Coupon
        self.client.login(username='admin', password='testpassword123')

        # 1. Create Coupon
        create_data = {
            'action': 'create_coupon',
            'coupon_code': 'RAMADAN70',
            'discount_type': 'FIXED',
            'discount_value': '70.00',
            'min_jars': '2',
            'min_subtotal': '500.00',
            'usage_limit': '50',
            'is_active': '1',
        }
        res = self.client.post(reverse('dashboard:offer_manager'), create_data)
        self.assertEqual(res.status_code, 302)
        coupon = Coupon.objects.get(code='RAMADAN70')
        self.assertEqual(coupon.discount_value, Decimal('70.00'))
        self.assertEqual(coupon.min_jars, 2)
        self.assertEqual(coupon.min_subtotal, Decimal('500.00'))
        self.assertEqual(coupon.usage_limit, 50)
        self.assertTrue(coupon.is_active)

        # 2. Toggle Coupon (Deactivate)
        res_toggle = self.client.post(reverse('dashboard:offer_manager'), {
            'action': 'toggle_coupon',
            'coupon_id': str(coupon.id)
        })
        self.assertEqual(res_toggle.status_code, 302)
        coupon.refresh_from_db()
        self.assertFalse(coupon.is_active)

        # 3. Delete Coupon
        res_del = self.client.post(reverse('dashboard:offer_manager'), {
            'action': 'delete_coupon',
            'coupon_id': str(coupon.id)
        })
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(Coupon.objects.filter(code='RAMADAN70').exists())


@override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY='')
class DashboardLoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.login_url = reverse('dashboard:login')
        self.staff_user = User.objects.create_user(
            username='manager',
            email='manager@pickpickles.com',
            password='correct-password-123',
            is_staff=True,
        )

    def tearDown(self):
        cache.clear()

    def test_failed_attempts_warning_and_lockout_after_five_attempts(self):
        res_get = self.client.get(self.login_url)
        self.assertEqual(res_get.status_code, 200)
        self.assertFalse(res_get.context['is_locked'])
        self.assertEqual(res_get.context['failed_attempts'], 0)
        self.assertEqual(res_get.context['remaining_attempts'], 5)

        for attempt in range(1, 5):
            res = self.client.post(self.login_url, {
                'username': 'manager',
                'password': 'wrong-password',
            })
            self.assertEqual(res.status_code, 200)
            self.assertFalse(res.context['is_locked'])
            self.assertEqual(res.context['failed_attempts'], attempt)
            self.assertEqual(res.context['remaining_attempts'], 5 - attempt)
            self.assertEqual(res.context['max_attempts'], 5)
            self.assertContains(res, f'{5 - attempt} left')

        # 4th attempt should show Final Attempt Remaining
        self.assertContains(res, 'Final Attempt Remaining')

        # Subsequent GET preserves failed attempt warning
        res_get_warn = self.client.get(self.login_url)
        self.assertEqual(res_get_warn.context['failed_attempts'], 4)
        self.assertEqual(res_get_warn.context['remaining_attempts'], 1)

        # 5th failed attempt triggers 15-minute lockout immediately
        res_lock = self.client.post(self.login_url, {
            'username': 'manager',
            'password': 'wrong-password',
        })
        self.assertEqual(res_lock.status_code, 200)
        self.assertTrue(res_lock.context['is_locked'])
        self.assertEqual(res_lock.context['failed_attempts'], 5)
        self.assertEqual(res_lock.context['remaining_attempts'], 0)
        self.assertEqual(res_lock.context['remaining_lock_minutes'], 15)
        self.assertGreater(res_lock.context['remaining_lock_seconds'], 890)
        self.assertContains(res_lock, 'Security Lockout Active')

        # Even valid credentials cannot bypass active lockout
        res_blocked = self.client.post(self.login_url, {
            'username': 'manager',
            'password': 'correct-password-123',
        })
        self.assertEqual(res_blocked.status_code, 200)
        self.assertTrue(res_blocked.context['is_locked'])

    def test_valid_login_clears_failed_attempt_counter(self):
        self.client.post(self.login_url, {'username': 'manager', 'password': 'wrong-password'})
        self.client.post(self.login_url, {'username': 'manager', 'password': 'wrong-password'})

        res_ok = self.client.post(self.login_url, {
            'username': 'manager',
            'password': 'correct-password-123',
        }, follow=True)
        self.assertRedirects(res_ok, reverse('dashboard:index'))
        self.assertNotContains(res_ok, 'Invalid credentials')
        self.assertNotContains(res_ok, 'Too many failed login attempts')

        self.client.logout()
        res_after = self.client.get(self.login_url)
        self.assertEqual(res_after.context['failed_attempts'], 0)
        self.assertFalse(res_after.context['is_locked'])

    @patch('store.security.verify_cloudflare_turnstile', return_value=(False, 'Verification failed'))
    def test_turnstile_error_displayed_in_context(self, _mock_verify):
        res = self.client.post(self.login_url, {
            'username': 'manager',
            'password': 'correct-password-123',
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['turnstile_error'], 'Verification failed')
        self.assertContains(res, 'Verification failed')


class ManualOrderOfferAndCouponTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='admin_manual',
            email='admin_manual@pickpickles.com',
            password='testpassword123',
        )
        self.client.login(username='admin_manual', password='testpassword123')
        from store.models import Category, Product
        self.category = Category.objects.create(name='Pickles', slug='pickles')
        self.product = Product.objects.create(
            category=self.category,
            name='Garlic Pickle',
            slug='garlic-pickle-manual',
            price_bdt=Decimal('450.00'),
            stock_count=20,
            jar_weight_grams=600,
        )

    def test_manual_order_respects_offer_toggle_and_applies_coupon(self):
        from store.models import Coupon, Order

        promo = PromotionSetting.get_settings()
        promo.is_active = True
        promo.bundle_discount_enabled = True
        promo.bundle_min_jars = 2
        promo.bundle_discount_amount = Decimal('100.00')
        promo.bundle_apply_mode = 'EXACT'
        promo.standard_delivery_fee = Decimal('150.00')
        promo.free_delivery_enabled = True
        promo.free_delivery_min_jars = 4
        promo.save()

        coupon = Coupon.objects.create(
            code='MANUAL50',
            discount_type='FIXED',
            discount_value=Decimal('50.00'),
            min_jars=2,
            is_active=True,
        )

        # 1. Orders list renders live offer config and active coupons for manual modal
        res_list = self.client.get(reverse('dashboard:orders'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, 'MANUAL50')
        self.assertIn('manual_offer_config_json', res_list.context)

        # 2. Manual order with 2 jars + active offer + coupon
        res_create = self.client.post(reverse('dashboard:create_manual_order'), {
            'customer_name': 'Test Buyer',
            'customer_phone': '01711112222',
            'delivery_address': 'Mirpur 10',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'product_id': [str(self.product.id)],
            'quantity': ['2'],
            'coupon_code': 'manual50',
            'apply_offers_present': '1',
            'apply_offers': '1',
        })
        self.assertEqual(res_create.status_code, 302)
        order1 = Order.objects.order_by('-id').first()
        self.assertEqual(order1.subtotal, Decimal('900.00'))
        self.assertEqual(order1.discount_amount, Decimal('150.00'))  # 100 bundle + 50 coupon
        self.assertEqual(order1.coupon_code, 'MANUAL50')
        self.assertEqual(order1.delivery_fee, Decimal('150.00'))
        self.assertEqual(order1.total_amount, Decimal('900.00'))
        coupon.refresh_from_db()
        self.assertEqual(coupon.used_count, 1)

        # 3. When bundle offer is turned OFF in Offer Manager, 2-jar order gets 0 bundle discount
        promo.bundle_discount_enabled = False
        promo.save()
        res_off = self.client.post(reverse('dashboard:create_manual_order'), {
            'customer_name': 'Test Buyer 2',
            'customer_phone': '01711113333',
            'delivery_address': 'Dhanmondi',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'product_id': [str(self.product.id)],
            'quantity': ['2'],
        })
        self.assertEqual(res_off.status_code, 302)
        order2 = Order.objects.order_by('-id').first()
        self.assertEqual(order2.discount_amount, Decimal('0.00'))
        self.assertEqual(order2.total_amount, Decimal('1050.00'))

        # 4. Advance Payment (BKASH) gets 5% discount in manual order too
        promo.advance_payment_discount_enabled = True
        promo.advance_payment_discount_percent = Decimal('5.00')
        promo.save()
        res_adv = self.client.post(reverse('dashboard:create_manual_order'), {
            'customer_name': 'Advance Buyer',
            'customer_phone': '01711114444',
            'delivery_address': 'Uttara 7',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'BKASH',
            'product_id': [str(self.product.id)],
            'quantity': ['2'],
            'apply_offers_present': '1',
            'apply_offers': '1',
        })
        self.assertEqual(res_adv.status_code, 302)
        order_adv = Order.objects.order_by('-id').first()
        self.assertEqual(order_adv.discount_amount, Decimal('45.00'))  # 5% of 900.00
        self.assertEqual(order_adv.total_amount, Decimal('1005.00'))  # 900 - 45 + 150

        # 5. Offer manager saves advance payment offer toggle & percent
        res_offer = self.client.post(reverse('dashboard:offer_manager'), {
            'is_active': '1',
            'campaign_name': 'Advance Campaign',
            'bundle_min_jars': '2',
            'bundle_discount_amount': '100',
            'bundle_apply_mode': 'EXACT',
            'standard_delivery_fee': '150',
            'free_delivery_min_jars': '4',
            'advance_payment_discount_enabled': '1',
            'advance_payment_discount_percent': '5',
            'advance_payment_discount_label': '5% Advance Payment OFF',
        })
        self.assertEqual(res_offer.status_code, 302)
        promo.refresh_from_db()
        self.assertTrue(promo.advance_payment_discount_enabled)
        self.assertEqual(promo.advance_payment_discount_percent, Decimal('5.00'))

    def test_dashboard_index_shows_jars_sold_and_queue_jars(self):
        """Dashboard KPI tiles display accurate delivered (sold) jars & active queue jars, excluding cancelled/deleted."""
        from store.models import Order, OrderItem
        # Create orders: 1 DELIVERED (3 jars), 1 PENDING UNPAID (2 jars), 1 CANCELLED (5 jars), 1 SOFT-DELETED (4 jars)
        o_del = Order.objects.create(
            customer_name='Delivered Buyer',
            customer_phone='01710000001',
            delivery_address='Dhaka',
            delivery_city='Dhaka',
            order_status='DELIVERED',
            subtotal=Decimal('1350.00'),
            delivery_fee=Decimal('150.00'),
            total_amount=Decimal('1500.00'),
        )
        OrderItem.objects.create(order=o_del, product=self.product, product_name=self.product.name, quantity=3, unit_price=Decimal('450.00'), total_price=Decimal('1350.00'))

        o_queue = Order.objects.create(
            customer_name='Queue Buyer',
            customer_phone='01710000002',
            delivery_address='Dhaka',
            delivery_city='Dhaka',
            order_status='PENDING',
            payment_status='UNPAID',
            subtotal=Decimal('900.00'),
            delivery_fee=Decimal('150.00'),
            total_amount=Decimal('1050.00'),
        )
        OrderItem.objects.create(order=o_queue, product=self.product, product_name=self.product.name, quantity=2, unit_price=Decimal('450.00'), total_price=Decimal('900.00'))

        o_cancel = Order.objects.create(
            customer_name='Cancelled Buyer',
            customer_phone='01710000003',
            delivery_address='Dhaka',
            delivery_city='Dhaka',
            order_status='CANCELLED',
            payment_status='PAID',
            subtotal=Decimal('2250.00'),
            delivery_fee=Decimal('0.00'),
            total_amount=Decimal('2250.00'),
        )
        OrderItem.objects.create(order=o_cancel, product=self.product, product_name=self.product.name, quantity=5, unit_price=Decimal('450.00'), total_price=Decimal('2250.00'))

        o_deleted = Order.objects.create(
            customer_name='Deleted Buyer',
            customer_phone='01710000004',
            delivery_address='Dhaka',
            delivery_city='Dhaka',
            order_status='DELIVERED',
            is_deleted=True,
            subtotal=Decimal('1800.00'),
            delivery_fee=Decimal('0.00'),
            total_amount=Decimal('1800.00'),
        )
        OrderItem.objects.create(order=o_deleted, product=self.product, product_name=self.product.name, quantity=4, unit_price=Decimal('450.00'), total_price=Decimal('1800.00'))

        res = self.client.get(reverse('dashboard:index'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['delivered_jars_sold'], 3)
        self.assertEqual(res.context['pipeline_jars_sold'], 2)
        self.assertEqual(res.context['total_jars_sold'], 5)
        self.assertContains(res, 'Total Jars Sold')
        self.assertContains(res, 'In Queue')
