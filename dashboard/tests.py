from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from decimal import Decimal
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
