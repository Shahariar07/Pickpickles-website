import os, sys
BASE_DIR = 'H:/My Drive/Pickpickles website'
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()
from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.auth.models import User
from store.models import Review, Product
from dashboard.views import reviews_manager

admin_user = User.objects.filter(is_superuser=True).first()
rf = RequestFactory()

# Create a test review to reject
p = Product.objects.first()
test_rev = Review.objects.create(
    product=p,
    reviewer_name="Spam Bot",
    reviewer_location="Unknown",
    rating=1,
    comment="This is spam",
    is_approved=False
)
rev_id = test_rev.id
print(f"Created test review ID: {rev_id}")

req = rf.post('/dashboard/reviews/', {
    'action': 'reject_review',
    'review_id': str(rev_id)
})
req.user = admin_user
SessionMiddleware(lambda r: None).process_request(req)
MessageMiddleware(lambda r: None).process_request(req)

resp = reviews_manager(req)
print(f"Response status: {resp.status_code}, redirect: {resp.url}")

# Verify it was rejected/deleted
exists = Review.objects.filter(id=rev_id).exists()
print(f"Review {rev_id} exists after rejection: {exists}")
assert not exists, "Review must be deleted after rejection!"
print("TEST PASS: Reject review successfully deleted the review!")
