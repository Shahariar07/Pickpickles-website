import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Order
from .webpush_sender import dispatch_order_created_notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Order)
def order_created_webpush_notification(sender, instance, created, **kwargs):
    """
    Real-time high-reliability Web Push notification signal dispatched whenever a new Order is placed.
    Uses Urgency: high (RFC 8030) and 72-hour TTL so mobile devices receive alerts reliably even after
    being offline or in Android Doze mode.
    """
    if not created:
        return

    try:
        dispatch_order_created_notification(instance)
    except Exception as e:
        logger.exception(f"Unexpected error in order_created_webpush_notification: {e}")
