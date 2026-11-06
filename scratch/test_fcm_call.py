import os
import sys

BASE_DIR = 'H:/My Drive/Pickpickles website'
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from pywebpush import webpush, WebPushException
from webpush.utils import _process_subscription_info

User = get_user_model()
try:
    mitu = User.objects.get(username='mitu')
    push_info = mitu.webpush_info.first()
    if push_info:
        sub = push_info.subscription
        sub_data = _process_subscription_info(sub)
        wp = getattr(settings, 'WEBPUSH_SETTINGS', {})
        print("Testing FCM push with Urgency: high and TTL: 259200...")
        resp = webpush(
            subscription_info=sub_data,
            data='{"head": "Test", "body": "Testing FCM"}',
            ttl=259200,
            headers={'Urgency': 'high'},
            vapid_private_key=wp['VAPID_PRIVATE_KEY'],
            vapid_claims={'sub': 'mailto:' + wp['VAPID_ADMIN_EMAIL']},
            timeout=10
        )
        print("FCM Response Status:", resp.status_code, resp.text)
    else:
        print("No push info found for mitu")
except WebPushException as e:
    print("FCM WebPushException:", getattr(e.response, 'status_code', None), str(e))
except Exception as e:
    print("General Exception:", type(e), str(e))
