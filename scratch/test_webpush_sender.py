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

from django.contrib.auth import get_user_model
from store.models import Order
from store.webpush_sender import (
    dispatch_order_created_notification,
    send_high_priority_user_notification,
    _deliver_to_subscription,
    EXTENDED_PUSH_TTL_SECONDS
)

User = get_user_model()

class WebPushReliabilityTestCase(unittest.TestCase):
    def setUp(self):
        self.user, _ = User.objects.get_or_create(username='mitu', defaults={'is_staff': True})

    @patch('pywebpush.webpush')
    def test_high_priority_headers_and_ttl(self, mock_webpush):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_webpush.return_value = mock_resp

        push_info = self.user.webpush_info.first()
        self.assertIsNotNone(push_info, "Mitu user must have a test subscription")

        ok, reason = _deliver_to_subscription(
            push_info.subscription,
            payload_str='{"head":"Test","body":"Test"}',
            ttl=EXTENDED_PUSH_TTL_SECONDS,
            urgency='high'
        )

        self.assertTrue(ok)
        self.assertEqual(reason, 'delivered')

        # Verify arguments passed to pywebpush.webpush
        mock_webpush.assert_called_once()
        _, kwargs = mock_webpush.call_args
        self.assertEqual(kwargs.get('ttl'), EXTENDED_PUSH_TTL_SECONDS)
        self.assertEqual(kwargs.get('headers', {}).get('Urgency'), 'high')
        print(f"[TEST PASS] WebPush invoked with TTL={kwargs.get('ttl')}s (72 hours) and Urgency={kwargs.get('headers', {}).get('Urgency')}")

    @patch('store.webpush_sender.send_high_priority_user_notification')
    def test_order_creation_triggers_push(self, mock_send):
        mock_send.return_value = (1, 0)
        
        # Create an order to trigger signals.py
        import time
        order_num = f"PKP-TEST-{int(time.time())}"
        order = Order.objects.create(
            order_number=order_num,
            customer_name="Rahim Mia",
            customer_phone="01711223344",
            delivery_address="Banani, Dhaka",
            delivery_city="Dhaka",
            total_amount=1200.00,
            order_status="PENDING"
        )

        time.sleep(0.5)  # Allow background daemon thread to start

        try:
            self.assertGreaterEqual(mock_send.call_count, 1)
            call_payload = mock_send.call_args[1].get('payload', {})
            self.assertEqual(mock_send.call_args[1].get('urgency'), 'high')
            self.assertEqual(mock_send.call_args[1].get('ttl'), EXTENDED_PUSH_TTL_SECONDS)
            self.assertIn("Rahim Mia", call_payload.get('body', ''))
            print(f"[TEST PASS] Order creation fired background thread with high-priority payload for #{order_num}!")
        finally:
            order.delete()

if __name__ == '__main__':
    unittest.main()
