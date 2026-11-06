import os
import sys
import json
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
from store.meta_capi import (
    record_order_tracking_keys,
    get_order_tracking_keys,
    _execute_meta_purchase,
    send_meta_purchase_event_on_accept,
    TRACKING_KEYS_FILE,
    SENT_ORDERS_FILE
)

class MetaTrackingTestCase(unittest.TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        # Find or create a test category & product
        self.category, _ = Category.objects.get_or_create(
            slug='test-pickles',
            defaults={'name': 'Test Pickles'}
        )
        self.product, _ = Product.objects.get_or_create(
            slug='test-chili-pickle',
            defaults={
                'name': 'Test Naga Chili Pickle',
                'category': self.category,
                'price_bdt': 350.00,
                'stock_count': 50,
                'is_in_stock': True,
                'jar_weight_grams': 400
            }
        )

    def test_record_and_get_tracking_keys(self):
        test_order_num = "TEST-ORDER-TRACKING-001"
        order_mock = MagicMock()
        order_mock.order_number = test_order_num

        req = self.rf.post('/checkout/', {
            'meta_fbp': 'fb.1.1712345678.11223344',
            'meta_fbc': 'fb.1.1712345678.IwARtestclickid123',
        }, HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 Chrome/124.0.0.0',
           HTTP_CF_CONNECTING_IP='103.205.180.50')

        # Add session
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(req)
        req.session.save()

        record_order_tracking_keys(order_mock, req)

        keys = get_order_tracking_keys(test_order_num)
        self.assertEqual(keys.get('fbp'), 'fb.1.1712345678.11223344')
        self.assertEqual(keys.get('fbc'), 'fb.1.1712345678.IwARtestclickid123')
        self.assertIn('Android 14', keys.get('client_user_agent', ''))
        self.assertEqual(keys.get('client_ip_address'), '103.205.180.50')
        print("[TEST PASS] record_order_tracking_keys saved all Meta match keys correctly!")

    @patch('store.meta_capi.requests.post')
    def test_meta_purchase_payload_contains_all_match_keys(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'events_received': 1, 'fbtrace_id': 'TEST_TRACE_123'}
        mock_post.return_value = mock_resp

        test_order_num = "TEST-ORDER-TRACKING-002"
        order_mock = MagicMock()
        order_mock.order_number = test_order_num
        order_mock.customer_name = "Rahim Uddin"
        order_mock.customer_phone = "01712345678"
        order_mock.customer_email = "rahim@example.com"
        order_mock.delivery_city = "Dhaka"
        order_mock.total_amount = 850.00
        order_mock.items.all.return_value = []

        # Record match keys for this order first
        req = self.rf.post('/checkout/', {
            'meta_fbp': 'fb.1.99887766.443322',
            'meta_fbc': 'fb.1.99887766.IwARfacebookclickid789',
        }, HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15',
           HTTP_CF_CONNECTING_IP='103.145.120.90')

        record_order_tracking_keys(order_mock, req)

        # Trigger execute meta purchase
        result = _execute_meta_purchase(order_mock, force=True)
        self.assertTrue(result.get('success'))

        # Inspect the post payload sent to Meta
        args, kwargs = mock_post.call_args
        sent_json = kwargs.get('json', {})
        self.assertIn('data', sent_json)
        event = sent_json['data'][0]

        self.assertEqual(event['event_name'], 'Purchase')
        self.assertEqual(event['event_id'], test_order_num)
        
        user_data = event['user_data']
        # Check match keys
        self.assertEqual(user_data.get('fbp'), 'fb.1.99887766.443322')
        self.assertEqual(user_data.get('fbc'), 'fb.1.99887766.IwARfacebookclickid789')
        self.assertIn('iPhone OS 17_4', user_data.get('client_user_agent'))
        self.assertEqual(user_data.get('client_ip_address'), '103.145.120.90')

        # Check hashed user fields
        self.assertIn('ph', user_data)
        self.assertIn('fn', user_data)
        self.assertIn('ln', user_data)
        self.assertIn('ct', user_data)
        self.assertIn('em', user_data)
        self.assertIn('external_id', user_data)
        self.assertIn('country', user_data)

        print("[TEST PASS] _execute_meta_purchase constructed 100% matched payload with fbp, fbc, mobile UA, IP, and hashed phone/name/city/email!")

if __name__ == '__main__':
    unittest.main()
