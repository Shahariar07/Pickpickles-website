import os
import sys
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = 'H:/My Drive/Pickpickles website'
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from store.models import Order, Product, Category
from store.views import checkout
from store.cart import Cart
from store.meta_capi import get_order_tracking_keys, send_meta_purchase_event_on_accept

class CheckoutMetaFlowTestCase(unittest.TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.category, _ = Category.objects.get_or_create(slug='test-meta-cat', defaults={'name': 'Test Meta Cat'})
        self.product, _ = Product.objects.get_or_create(
            slug='test-meta-jar',
            defaults={
                'name': 'Test Meta Mango Pickle',
                'category': self.category,
                'price_bdt': 320.00,
                'stock_count': 100,
                'is_in_stock': True,
                'jar_weight_grams': 400
            }
        )

    @patch('store.meta_capi.requests.post')
    def test_full_checkout_and_admin_confirm_meta_flow(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'events_received': 1, 'fbtrace_id': 'MOCK_FBTRACE_999'}
        mock_post.return_value = mock_resp

        # 1. Simulate customer arriving at checkout with item in cart & meta tracking cookies/params
        import time
        unique_phone = f"0171{int(time.time()) % 10000000:07d}"
        req = self.rf.post('/checkout/', {
            'customer_name': 'Kamrul Hasan',
            'customer_phone': unique_phone,
            'customer_email': 'kamrul@gmail.com',
            'delivery_address': 'Road 4, House 12, Mirpur 10, Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'payment_method': 'COD',
            'meta_fbp': 'fb.1.1712000000.999888',
            'meta_fbc': 'fb.1.1712000000.IwARclickfromad999',
            'cf-turnstile-response': '', # smart fallback
        }, HTTP_HOST='127.0.0.1',
           HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36',
           HTTP_CF_CONNECTING_IP='103.205.71.12')

        # Add session and messages
        session_mw = SessionMiddleware(lambda r: None)
        session_mw.process_request(req)
        messages_mw = MessageMiddleware(lambda r: None)
        messages_mw.process_request(req)

        # Add item to cart
        cart = Cart(req)
        cart.add(product=self.product, quantity=2)
        req.session.save()

        # Submit checkout
        resp = checkout(req)
        self.assertEqual(resp.status_code, 302)
        redirect_url = resp.url
        self.assertIn('/order/success/', redirect_url)

        # Verify that Meta was NOT called during checkout (Strictly NO Purchase event on checkout!)
        meta_calls_during_checkout = [c for c in mock_post.mock_calls if 'graph.facebook.com' in str(c)]
        self.assertEqual(len(meta_calls_during_checkout), 0, "Meta Purchase event MUST NOT fire on checkout page!")

        # Retrieve the newly created order
        order_num = redirect_url.rstrip('/').split('/')[-1]
        order = Order.objects.get(order_number=order_num)
        self.assertEqual(order.order_status, 'PENDING')

        # Verify tracking keys were recorded persistently in media/meta_order_tracking.json
        keys = get_order_tracking_keys(order_num)
        self.assertEqual(keys.get('fbp'), 'fb.1.1712000000.999888')
        self.assertEqual(keys.get('fbc'), 'fb.1.1712000000.IwARclickfromad999')
        self.assertIn('SM-A546E', keys.get('client_user_agent'))
        self.assertEqual(keys.get('client_ip_address'), '103.205.71.12')
        print(f"\n[FLOW TEST PASS] Order #{order_num} saved as PENDING. Tracking keys recorded safely. Zero fake events sent to Meta.")

        # 2. Simulate Admin confirming the order in Dashboard
        # Now the admin triggers send_meta_purchase_event_on_accept
        res = send_meta_purchase_event_on_accept(order, force=True)
        self.assertTrue(res.get('success'))

        # Verify Meta Graph API was called now with the customer's Match Keys
        meta_calls_after_confirm = [c for c in mock_post.mock_calls if 'graph.facebook.com' in str(c)]
        self.assertGreaterEqual(len(meta_calls_after_confirm), 1)
        # Find the call args to graph.facebook.com
        meta_kwargs = [c.kwargs for c in mock_post.mock_calls if 'graph.facebook.com' in str(c) and 'json' in c.kwargs][0]
        sent_json = meta_kwargs['json']
        user_data = sent_json['data'][0]['user_data']

        self.assertEqual(user_data.get('fbp'), 'fb.1.1712000000.999888')
        self.assertEqual(user_data.get('fbc'), 'fb.1.1712000000.IwARclickfromad999')
        self.assertIn('SM-A546E', user_data.get('client_user_agent'))
        self.assertEqual(user_data.get('client_ip_address'), '103.205.71.12')

        # Verify Catalog Content ID match
        custom_data = sent_json['data'][0]['custom_data']
        expected_catalog_id = f"JAR-{self.product.id}"
        self.assertIn(expected_catalog_id, custom_data.get('content_ids', []))
        self.assertEqual(custom_data.get('contents', [])[0]['id'], expected_catalog_id)
        print(f"[FLOW TEST PASS] Verified content_ids matches Meta Catalog retailer_id ({expected_catalog_id})!")

        print(f"[FLOW TEST PASS] Admin confirm dispatched Purchase with 100% matched customer keys to Meta CAPI!\n")

    def tearDown(self):
        try:
            if hasattr(self, 'order') and self.order:
                self.order.delete()
        except Exception:
            pass
        try:
            if hasattr(self, 'product') and self.product and self.product.id not in range(1, 26):
                self.product.delete()
        except Exception:
            pass
        try:
            if hasattr(self, 'category') and self.category and self.category.slug == 'test-meta-cat':
                self.category.delete()
        except Exception:
            pass

if __name__ == '__main__':
    unittest.main()
