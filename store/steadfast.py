import logging
import requests
from decimal import Decimal
from django.conf import settings

logger = logging.getLogger(__name__)


class SteadfastCourierService:
    """
    Steadfast Courier Merchant Developer API Service Client
    Official API Documentation: https://portal.steadfast.com.bd/user/api/guide
    """

    def __init__(self):
        self.base_url = getattr(settings, 'STEADFAST_BASE_URL', 'https://portal.packzy.com/api/v1').rstrip('/')
        self.api_key = getattr(settings, 'STEADFAST_API_KEY', '')
        self.secret_key = getattr(settings, 'STEADFAST_SECRET_KEY', '')

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
