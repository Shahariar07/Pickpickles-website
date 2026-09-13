import logging
import requests
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class PathaoCourierService:
    """
    Pathao Courier Merchant Developer API Service Client
    Official API Documentation: https://merchant.pathao.com/courier/developer-api
    """

    def __init__(self):
        self.base_url = getattr(settings, 'PATHAO_BASE_URL', 'https://courier-api.pathao.com').rstrip('/')
        self.client_id = getattr(settings, 'PATHAO_CLIENT_ID', '')
        self.client_secret = getattr(settings, 'PATHAO_CLIENT_SECRET', '')
        self.username = getattr(settings, 'PATHAO_USERNAME', '')
        self.password = getattr(settings, 'PATHAO_PASSWORD', '')
        self.store_id = getattr(settings, 'PATHAO_STORE_ID', '')

    def is_configured(self) -> bool:
        """Check if all required Pathao API credentials are present"""
        return bool(self.client_id and self.client_secret and self.username and self.password)

    def get_token(self) -> str | None:
        """
        Authenticate with Pathao and retrieve access token with in-memory caching.
        Endpoint: POST /aladdin/api/v1/issue-token
        """
        if not self.is_configured():
            return None

        cache_key = 'pathao_merchant_access_token'
        cached_token = cache.get(cache_key)
        if cached_token:
            return cached_token

        url = f"{self.base_url}/aladdin/api/v1/issue-token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                token = data.get('access_token')
                expires_in = data.get('expires_in', 604800)  # Default 7 days
                if token:
                    cache.set(cache_key, token, timeout=max(60, expires_in - 300))
                    return token
            logger.error(f"Pathao issue-token failed [{response.status_code}]: {response.text}")
        except Exception as e:
            logger.exception(f"Error connecting to Pathao issue-token: {str(e)}")

        return None

    def _get_auth_headers(self) -> dict | None:
        token = self.get_token()
        if not token:
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_stores(self) -> list:
        """
        Fetch merchant stores from Pathao.
        Endpoint: GET /aladdin/api/v1/stores
        """
        headers = self._get_auth_headers()
        if not headers:
            return []
        url = f"{self.base_url}/aladdin/api/v1/stores"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json().get('data', {}).get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch Pathao stores: {str(e)}")
        return []

    def calculate_price(self, weight_kg: float, zone: str = 'INSIDE_DHAKA', recipient_city: int = None, recipient_zone: int = None, delivery_type: int = 48) -> Decimal | None:
        """
        Query Pathao Live Price Calculation Endpoint.
        Endpoint: POST /aladdin/api/v1/merchant/price-calculation
        Returns calculated price in BDT Decimal, or None on failure.
        """
        if not self.is_configured() or not self.store_id:
            return None

        # Determine default city & zone ID: Dhaka (1, 1) vs Outside Dhaka (2, 14)
        if not recipient_city:
            if str(zone).upper() in ['INSIDE_DHAKA', 'DHAKA_CITY']:
                recipient_city = 1  # Dhaka
                if not recipient_zone:
                    recipient_zone = 1
            else:
                recipient_city = 2  # Outside Dhaka / Nationwide default
                if not recipient_zone:
                    recipient_zone = 14

        cache_key = f"pathao_price_{weight_kg}_{zone}_{recipient_city}_{recipient_zone}_{delivery_type}"
        cached_price = cache.get(cache_key)
        if cached_price is not None:
            return Decimal(str(cached_price))

        headers = self._get_auth_headers()
        if not headers:
            return None

        url = f"{self.base_url}/aladdin/api/v1/merchant/price-plan"
        payload = {
            "store_id": int(self.store_id) if str(self.store_id).isdigit() else self.store_id,
            "item_type": 2,  # Parcel
            "delivery_type": delivery_type,  # 48 = Normal delivery
            "item_weight": max(0.5, float(weight_kg)),
            "recipient_city": int(recipient_city),
        }
        if recipient_zone:
            payload["recipient_zone"] = int(recipient_zone)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=8)
            if response.status_code == 200:
                data = response.json()
                price_data = data.get('data', {})
                price = price_data.get('final_price') if price_data.get('final_price') is not None else price_data.get('price')
                if price is not None:
                    dec_price = Decimal(str(price))
                    cache.set(cache_key, str(dec_price), timeout=600)  # Cache for 10 mins
                    return dec_price
            logger.warning(f"Pathao price calculation API returned {response.status_code}: {response.text}")
        except Exception as e:
            logger.warning(f"Pathao price calculation failed: {str(e)}")

        return None

    def create_order(self, order) -> dict:
        """
        Create / Dispatch order to Pathao Courier.
        Endpoint: POST /aladdin/api/v1/orders
        Returns dict with status, consignment_id, tracking_code, or error message.
        """
        headers = self._get_auth_headers()
        if not headers:
            return {"success": False, "message": "Pathao API is not configured with valid credentials."}

        if not self.store_id:
            return {"success": False, "message": "PATHAO_STORE_ID is missing from settings."}

        # Calculate COD amount to collect
        collect_amount = 0
        if order.payment_status == 'UNPAID' or order.payment_method == 'COD':
            collect_amount = int(round(order.total_amount))

        url = f"{self.base_url}/aladdin/api/v1/orders"
        
        # 1. Phone number (exactly 11 digits: 01XXXXXXXXX)
        clean_phone = ''.join(c for c in str(order.customer_phone or '') if c.isdigit())
        if clean_phone.startswith('880'):
            clean_phone = clean_phone[2:]
        if len(clean_phone) == 10 and clean_phone.startswith('1'):
            clean_phone = f"0{clean_phone}"
        if len(clean_phone) > 11:
            clean_phone = clean_phone[-11:]
        elif len(clean_phone) < 11:
            clean_phone = clean_phone.zfill(11)

        # 2. Name length (3 to 100 characters)
        recipient_name = (order.customer_name or 'Valued Customer').strip()
        if len(recipient_name) < 3:
            recipient_name = f"{recipient_name} Customer"
        recipient_name = recipient_name[:100]

        # 3. Address length (10 to 220 characters)
        recipient_address = f"{order.delivery_address}, {order.delivery_city}".strip()
        if len(recipient_address) < 10:
            recipient_address = f"{recipient_address}, Bangladesh"
        recipient_address = recipient_address[:220]

        # 4. Weight (0.5 kg to 10.0 kg)
        weight_kg = float(order.total_weight_kg) if hasattr(order, 'total_weight_kg') and order.total_weight_kg else 0.6
        weight_kg = max(0.5, min(10.0, round(weight_kg, 2)))

        recipient_city = 1
        recipient_zone = 1
        if getattr(order, 'delivery_zone', '') == 'OUTSIDE_DHAKA':
            recipient_city = 2
            recipient_zone = 14

        payload = {
            "store_id": int(self.store_id) if str(self.store_id).isdigit() else self.store_id,
            "merchant_order_id": str(order.order_number),
            "recipient_name": recipient_name,
            "recipient_phone": clean_phone,
            "recipient_address": recipient_address,
            "recipient_city": recipient_city,
            "recipient_zone": recipient_zone,
            "amount_to_collect": int(collect_amount),
            "delivery_type": 48,  # 48 for Normal Delivery
            "item_type": 2,       # 2 for Parcel
            "item_quantity": max(1, order.total_items_count if hasattr(order, 'total_items_count') else 1),
            "item_weight": weight_kg,
            "item_description": f"Pickpickles Jar Order #{order.order_number} ({weight_kg}kg)",
            "special_instruction": str(order.customer_notes or "Fragile artisanal glass jars - Handle with care")[:250],
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            data = response.json() if response.content else {}
            if response.status_code in [200, 201] and data.get('type') == 'success':
                res_data = data.get('data', {})
                consignment_id = res_data.get('consignment_id')
                tracking_code = res_data.get('tracking_code') or consignment_id
                
                # Save details onto the Order model
                order.pathao_consignment_id = consignment_id
                order.pathao_tracking_code = tracking_code
                order.pathao_order_status = 'CREATED'
                order.save(update_fields=['pathao_consignment_id', 'pathao_tracking_code', 'pathao_order_status'])
                
                return {
                    "success": True,
                    "consignment_id": consignment_id,
                    "tracking_code": tracking_code,
                    "message": f"Parcel successfully booked with Pathao! Tracking: {tracking_code}"
                }
            else:
                err_msg = data.get('message') or response.text
                return {"success": False, "message": f"Pathao error ({response.status_code}): {err_msg}"}
        except Exception as e:
            logger.exception(f"Pathao order creation exception: {str(e)}")
            return {"success": False, "message": f"Connection error: {str(e)}"}

    def get_order_info(self, consignment_id: str) -> dict:
        """
        Fetch live tracking and delivery status for a consignment from Pathao.
        Endpoint: GET /aladdin/api/v1/orders/{consignment_id}/info
        """
        if not consignment_id:
            return {"success": False, "message": "Consignment ID required"}
        headers = self._get_auth_headers()
        if not headers:
            return {"success": False, "message": "Pathao API is not authenticated"}
        url = f"{self.base_url}/aladdin/api/v1/orders/{consignment_id}/info"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"success": True, "data": data.get('data', {})}
            return {"success": False, "status_code": res.status_code, "message": res.text}
        except Exception as e:
            logger.warning(f"Failed to fetch Pathao consignment info: {str(e)}")
            return {"success": False, "message": str(e)}

    def get_cities(self) -> list:
        """
        Fetch list of cities from Pathao.
        Endpoint: GET /aladdin/api/v1/countries/1/city-list
        """
        headers = self._get_auth_headers()
        if not headers:
            return []
        url = f"{self.base_url}/aladdin/api/v1/countries/1/city-list"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json().get('data', {}).get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch Pathao cities: {str(e)}")
        return []

    def get_zones(self, city_id: int) -> list:
        """
        Fetch list of zones for a city from Pathao.
        Endpoint: GET /aladdin/api/v1/cities/{city_id}/zone-list
        """
        headers = self._get_auth_headers()
        if not headers:
            return []
        url = f"{self.base_url}/aladdin/api/v1/cities/{city_id}/zone-list"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json().get('data', {}).get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch Pathao zones: {str(e)}")
        return []

    def get_areas(self, zone_id: int) -> list:
        """
        Fetch list of areas for a zone from Pathao.
        Endpoint: GET /aladdin/api/v1/zones/{zone_id}/area-list
        """
        headers = self._get_auth_headers()
        if not headers:
            return []
        url = f"{self.base_url}/aladdin/api/v1/zones/{zone_id}/area-list"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json().get('data', {}).get('data', [])
        except Exception as e:
            logger.error(f"Failed to fetch Pathao areas: {str(e)}")
        return []
