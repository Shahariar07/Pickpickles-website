import logging
import requests
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Persistent connection session to avoid repeated SSL/TLS handshakes
_sf_session = None

# In-memory ultra-fast cache tier for active web server process
_sf_fraud_mem_cache = {}

def get_steadfast_http_session():
    global _sf_session
    if _sf_session is None:
        _sf_session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=15, pool_maxsize=30, max_retries=1)
        _sf_session.mount('https://', adapter)
        _sf_session.mount('http://', adapter)
    return _sf_session


class SteadfastCourierService:
    """
    Steadfast Courier Merchant Developer API Service Client
    Official API Documentation: https://portal.steadfast.com.bd/user/api/guide
    """

    def __init__(self):
        raw_url = getattr(settings, 'STEADFAST_BASE_URL', 'https://portal.packzy.com/api/v1') or 'https://portal.packzy.com/api/v1'
        # Automatically fix unresolvable domain portal.steadfast.com.bd to portal.packzy.com
        raw_url = raw_url.replace('portal.steadfast.com.bd', 'portal.packzy.com')
        self.base_url = raw_url.rstrip('/')
        self.api_key = getattr(settings, 'STEADFAST_API_KEY', '')
        self.secret_key = getattr(settings, 'STEADFAST_SECRET_KEY', '')
        self.session = get_steadfast_http_session()

    def is_configured(self) -> bool:
        """Check if all required Steadfast API credentials are present."""
        return bool(self.api_key and self.secret_key)

    def _get_headers(self) -> dict | None:
        if not self.is_configured():
            return None
        return {
            "Api-Key": self.api_key,
            "Secret-Key": self.secret_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def create_order(self, order) -> dict:
        """
        Create / Dispatch order to Steadfast Courier.
        Endpoint: POST /create_order
        Payload:
          - invoice: Order Number (e.g. PKP-00001)
          - recipient_name: Customer Name
          - recipient_phone: 11-digit Phone (01XXXXXXXXX)
          - recipient_address: Full Address
          - cod_amount: Cash to collect (0 if already paid)
          - note: Special instructions
        """
        if not self.is_configured():
            return {
                "success": False,
                "message": "Steadfast API is not configured. Please add STEADFAST_API_KEY and STEADFAST_SECRET_KEY in settings or environment."
            }

        headers = self._get_headers()
        url = f"{self.base_url}/create_order"

        # 1. Clean Phone number (11 digits: 01XXXXXXXXX)
        clean_phone = ''.join(c for c in str(order.customer_phone or '') if c.isdigit())
        if clean_phone.startswith('880'):
            clean_phone = clean_phone[2:]
        if len(clean_phone) == 10 and clean_phone.startswith('1'):
            clean_phone = f"0{clean_phone}"
        if len(clean_phone) > 11:
            clean_phone = clean_phone[-11:]
        elif len(clean_phone) < 11:
            clean_phone = clean_phone.zfill(11)

        # 2. Recipient Name
        recipient_name = (order.customer_name or 'Valued Customer').strip()
        if len(recipient_name) < 2:
            recipient_name = f"{recipient_name} Customer"

        # 3. Recipient Address
        recipient_address = f"{order.delivery_address}, {order.delivery_city}".strip()
        if len(recipient_address) < 10:
            recipient_address = f"{recipient_address}, Bangladesh"

        # 4. COD Amount
        cod_amount = 0
        if order.payment_status != 'PAID' and (order.payment_status == 'UNPAID' or order.payment_method == 'COD'):
            cod_amount = int(round(order.total_amount))

        # 5. Note / Delivery Instruction
        note = (order.delivery_instruction or order.customer_notes or "Fragile glass jars - Pickpickles - Handle with care").strip()[:250]

        payload = {
            "invoice": str(order.order_number),
            "recipient_name": recipient_name,
            "recipient_phone": clean_phone,
            "recipient_address": recipient_address,
            "cod_amount": cod_amount,
            "note": note,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            data = response.json() if response.content else {}

            if response.status_code == 200 and (data.get('status') == 200 or data.get('success')):
                consignment = data.get('consignment', {})
                consignment_id = consignment.get('consignment_id')
                tracking_code = consignment.get('tracking_code') or str(consignment_id)
                raw_status = consignment.get('status') or 'in_review'

                # Save details onto Order model
                order.courier_provider = 'STEADFAST'
                order.steadfast_consignment_id = str(consignment_id) if consignment_id else None
                order.steadfast_tracking_code = str(tracking_code) if tracking_code else None
                order.steadfast_order_status = str(raw_status)
                order.save(update_fields=['courier_provider', 'steadfast_consignment_id', 'steadfast_tracking_code', 'steadfast_order_status'])

                return {
                    "success": True,
                    "consignment_id": consignment_id,
                    "tracking_code": tracking_code,
                    "message": f"Parcel successfully booked with Steadfast Courier! Tracking: {tracking_code}"
                }
            else:
                err_msg = data.get('message') or data.get('errors') or response.text
                logger.error(f"Steadfast order creation error [{response.status_code}]: {err_msg}")
                return {"success": False, "message": f"Steadfast error ({response.status_code}): {err_msg}"}
        except Exception as e:
            logger.exception(f"Steadfast order creation exception: {str(e)}")
            return {"success": False, "message": f"Connection error to Steadfast: {str(e)}"}

    def get_delivery_status_by_cid(self, consignment_id: str | int) -> dict:
        """
        Fetch delivery status by Consignment ID.
        Endpoint: GET /status_by_cid/{consignment_id}
        """
        if not consignment_id:
            return {"success": False, "message": "Consignment ID is required"}
        headers = self._get_headers()
        if not headers:
            return {"success": False, "message": "Steadfast API is not configured"}

        url = f"{self.base_url}/status_by_cid/{consignment_id}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"success": True, "delivery_status": data.get('delivery_status'), "data": data}
            return {"success": False, "status_code": res.status_code, "message": res.text}
        except Exception as e:
            logger.warning(f"Failed to fetch Steadfast status by CID {consignment_id}: {str(e)}")
            return {"success": False, "message": str(e)}

    def get_delivery_status_by_tracking_code(self, tracking_code: str) -> dict:
        """
        Fetch delivery status by Tracking Code.
        Endpoint: GET /status_by_trackingcode/{tracking_code}
        """
        if not tracking_code:
            return {"success": False, "message": "Tracking code is required"}
        headers = self._get_headers()
        if not headers:
            return {"success": False, "message": "Steadfast API is not configured"}

        url = f"{self.base_url}/status_by_trackingcode/{tracking_code}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"success": True, "delivery_status": data.get('delivery_status'), "data": data}
            return {"success": False, "status_code": res.status_code, "message": res.text}
        except Exception as e:
            logger.warning(f"Failed to fetch Steadfast status by tracking code {tracking_code}: {str(e)}")
            return {"success": False, "message": str(e)}

    def get_delivery_status_by_invoice(self, invoice: str) -> dict:
        """
        Fetch delivery status by Invoice / Order Number.
        Endpoint: GET /status_by_invoice/{invoice}
        """
        if not invoice:
            return {"success": False, "message": "Invoice is required"}
        headers = self._get_headers()
        if not headers:
            return {"success": False, "message": "Steadfast API is not configured"}

        url = f"{self.base_url}/status_by_invoice/{invoice}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"success": True, "delivery_status": data.get('delivery_status'), "data": data}
            return {"success": False, "status_code": res.status_code, "message": res.text}
        except Exception as e:
            logger.warning(f"Failed to fetch Steadfast status by invoice {invoice}: {str(e)}")
            return {"success": False, "message": str(e)}

    def check_fraud(self, phone: str, force_refresh: bool = False) -> dict:
        """
        Check customer delivery history and fraud risk by phone number across Steadfast Courier network.
        Endpoint: GET /fraud_check/{phone}
        """
        if not phone:
            return {"success": False, "message": "Phone number is required"}

        clean_phone = ''.join(c for c in str(phone) if c.isdigit())
        if clean_phone.startswith('880'):
            clean_phone = clean_phone[2:]
        if len(clean_phone) == 10 and clean_phone.startswith('1'):
            clean_phone = f"0{clean_phone}"
        if len(clean_phone) > 11:
            clean_phone = clean_phone[-11:]

        cache_key = f"sf_fraud_v3_{clean_phone}"

        # 1. Tier-1: Process In-Memory Cache (0.001ms instantaneous lookup)
        if not force_refresh and clean_phone in _sf_fraud_mem_cache:
            res = dict(_sf_fraud_mem_cache[clean_phone])
            res['from_cache'] = True
            return res

        # 2. Tier-2: Django Persistent Cache (<2ms)
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                _sf_fraud_mem_cache[clean_phone] = cached
                cached_copy = dict(cached)
                cached_copy['from_cache'] = True
                return cached_copy

        if not self.is_configured():
            return {
                "success": False,
                "message": "Steadfast API is not configured. Please set STEADFAST_API_KEY and STEADFAST_SECRET_KEY in settings or environment."
            }

        headers = self._get_headers()
        url = f"{self.base_url}/fraud_check/{clean_phone}"
        try:
            # Fast timeout of 5 seconds to keep dashboard responsive
            res = self.session.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json() if res.content else {}
                
                # Extract parcel delivery metrics from Steadfast response
                total_parcels = int(data.get('total_parcels') or data.get('total_parcel') or data.get('total_orders') or 0)
                total_delivered = int(data.get('total_delivered') or data.get('delivered') or data.get('total_delivered_parcels') or 0)
                total_cancelled = int(data.get('total_cancelled') or data.get('cancelled') or data.get('total_cancelled_parcels') or data.get('total_returned') or 0)
                
                if total_parcels < (total_delivered + total_cancelled):
                    total_parcels = total_delivered + total_cancelled

                if total_parcels > 0:
                    success_rate = round((total_delivered / total_parcels) * 100, 1)
                else:
                    success_rate = 100.0 if (total_delivered == 0 and total_cancelled == 0) else 0.0

                # Risk classification
                if total_parcels == 0:
                    risk_level = "NEW"
                    risk_title = "⚪ নতুন নম্বর (Steadfast-এ পূর্বের রেকর্ড নেই)"
                    risk_label = "New / Clean"
                    badge_class = "bg-slate-100 text-slate-800 border-slate-300"
                    risk_desc = "Steadfast কুরিয়ার নেটওয়ার্কে এই নম্বরে পূর্বে কোনো পার্সেল ডেলিভারি রেকর্ড পাওয়া যায়নি।"
                elif total_cancelled > 0 and success_rate < 65:
                    risk_level = "HIGH_RISK"
                    risk_title = "🔴 উচ্চ ঝুঁকিপূর্ণ (High Cancellation / Refusal Rate)"
                    risk_label = "High Risk"
                    badge_class = "bg-rose-100 text-rose-800 border-rose-300"
                    risk_desc = f"Steadfast-এ {total_parcels}টি অর্ডারের মধ্যে {total_cancelled}টি বাতিল/ফেরত হয়েছে (ডেলিভারি রেট {success_rate}%)। ক্যাশ অন ডেলিভারিতে পাঠানোর আগে সতর্ক থাকুন।"
                elif total_cancelled > 0 and success_rate < 85:
                    risk_level = "MODERATE"
                    risk_title = "🟡 মাঝারি ঝুঁকি (কিছু রিটার্ন রেকর্ড আছে)"
                    risk_label = "Moderate Risk"
                    badge_class = "bg-amber-100 text-amber-800 border-amber-300"
                    risk_desc = f"Steadfast-এ {total_parcels}টি পার্সেলের মধ্যে {total_delivered}টি ডেলিভার ও {total_cancelled}টি রিটার্ন হয়েছে (সফলতা: {success_rate}%)।"
                else:
                    risk_level = "SAFE"
                    risk_title = "🟢 বিশ্বস্ত প্রাপক (Safe / High Delivery Rate)"
                    risk_label = "Safe / Trusted"
                    badge_class = "bg-emerald-100 text-emerald-800 border-emerald-300"
                    risk_desc = f"Steadfast-এ {total_parcels}টি অর্ডারের মধ্যে {total_delivered}টি সফলভাবে ডেলিভার হয়েছে (সফলতা: {success_rate}%)।"

                result = {
                    "success": True,
                    "phone": clean_phone,
                    "total_parcels": total_parcels,
                    "total_delivered": total_delivered,
                    "total_cancelled": total_cancelled,
                    "success_rate": success_rate,
                    "risk_level": risk_level,
                    "risk_title": risk_title,
                    "risk_label": risk_label,
                    "risk_desc": risk_desc,
                    "badge_class": badge_class,
                    "raw_data": data,
                }

                # Save to both Tier-1 memory cache and Tier-2 Django cache (24 hours TTL)
                _sf_fraud_mem_cache[clean_phone] = result
                try:
                    cache.set(cache_key, result, timeout=86400)
                except Exception:
                    pass

                return result

            elif res.status_code == 429:
                # Steadfast API rate limiting (e.g. max 10 requests reached)
                # If we have a previously cached result, fallback to it
                cached = cache.get(cache_key) or _sf_fraud_mem_cache.get(clean_phone)
                if cached:
                    cached_copy = dict(cached)
                    cached_copy['from_cache'] = True
                    cached_copy['warning'] = "Steadfast API রেট লিমিট অতিক্রান্ত হয়েছে, ক্যাশ করা হিস্ট্রি দেখানো হচ্ছে।"
                    return cached_copy

                return {
                    "success": False,
                    "status_code": 429,
                    "is_rate_limited": True,
                    "message": "Steadfast API-র সাময়িক লিমিট (Rate Limit) অতিক্রান্ত হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।"
                }
            else:
                return {
                    "success": False,
                    "status_code": res.status_code,
                    "message": f"Steadfast API Error ({res.status_code}): {res.text}"
                }
        except requests.exceptions.Timeout:
            logger.warning(f"Steadfast fraud check timed out for {clean_phone}")
            # Fallback to cache on timeout if available
            cached = cache.get(cache_key) or _sf_fraud_mem_cache.get(clean_phone)
            if cached:
                cached_copy = dict(cached)
                cached_copy['from_cache'] = True
                return cached_copy
            return {"success": False, "message": "Steadfast সার্ভার রেসপন্স দিতে দেরি করছে (Timeout)। কিছুক্ষণ পর আবার ট্রাই করুন।"}
        except Exception as e:
            logger.warning(f"Failed to check Steadfast fraud status for {clean_phone}: {str(e)}")
            return {"success": False, "message": f"Steadfast connection error: {str(e)}"}

    def get_balance(self) -> dict:
        """
        Fetch merchant current account balance from Steadfast.
        Endpoint: GET /get_balance
        """
        headers = self._get_headers()
        if not headers:
            return {"success": False, "message": "Steadfast API is not configured"}

        url = f"{self.base_url}/get_balance"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"success": True, "balance": data.get('current_balance'), "data": data}
            return {"success": False, "status_code": res.status_code, "message": res.text}
        except Exception as e:
            logger.warning(f"Failed to fetch Steadfast balance: {str(e)}")
            return {"success": False, "message": str(e)}

    def sync_order_status(self, order) -> str | None:
        """
        Sync live status for an order from Steadfast API and update order status accordingly.
        """
        if not self.is_configured():
            return None

        res = None
        if order.steadfast_consignment_id:
            res = self.get_delivery_status_by_cid(order.steadfast_consignment_id)
        elif order.steadfast_tracking_code:
            res = self.get_delivery_status_by_tracking_code(order.steadfast_tracking_code)
        elif order.order_number:
            res = self.get_delivery_status_by_invoice(order.order_number)

        if not res or not res.get('success'):
            return None

        delivery_status = str(res.get('delivery_status') or '').strip()
        if not delivery_status:
            return None

        order.steadfast_order_status = delivery_status
        clean = delivery_status.lower().replace('-', '_').replace(' ', '_')

        status_map = {
            'in_review': 'CONFIRMED',
            'pending': 'CONFIRMED',
            'picked_up': 'PACKING',
            'received_at_hub': 'PACKING',
            'in_transit': 'OUT_FOR_DELIVERY',
            'hold': 'OUT_FOR_DELIVERY',
            'delivered': 'DELIVERED',
            'delivered_approval_pending': 'DELIVERED',
            'partial_delivered': 'DELIVERED',
            'partial_delivered_approval_pending': 'DELIVERED',
            'cancelled': 'CANCELLED',
            'cancelled_approval_pending': 'CANCELLED',
            'unknown': 'CANCELLED',
        }

        if clean in status_map:
            mapped = status_map[clean]
            if order.order_status != mapped:
                order.order_status = mapped
                if mapped == 'DELIVERED' and order.payment_status == 'UNPAID':
                    order.payment_status = 'PAID'

        order.save(update_fields=['steadfast_order_status', 'order_status', 'payment_status'])
        return delivery_status
