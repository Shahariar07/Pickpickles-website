import re
import requests
from django.conf import settings

BULKSMSBD_SMS_URL = "http://bulksmsbd.net/api/smsapi"
BULKSMSBD_BALANCE_URL = "http://bulksmsbd.net/api/getBalanceApi"

BULKSMSBD_STATUS_CODES = {
    202: "SMS Submitted Successfully",
    1001: "Invalid Number",
    1002: "Sender ID not correct or disabled",
    1003: "Required fields missing / Contact BulkSMSBD Admin",
    1005: "Internal Error at BulkSMSBD",
    1006: "Balance Validity Not Available",
    1007: "Balance Insufficient",
    1011: "User ID not found",
    1012: "Masking SMS must be sent in Bengali",
    1013: "Sender ID has no Gateway found for this API Key",
    1014: "Sender Type Name not found using this sender by API Key",
    1015: "Sender ID has not found Any Valid Gateway by API Key",
    1016: "Sender Type Name Active Price Info not found",
    1017: "Sender Type Name Price Info not found",
    1018: "Account owner is disabled",
    1019: "Sender type price of this account is disabled",
    1020: "Parent of this account is not found",
    1021: "Parent active sender type price is not found",
    1031: "Account Not Verified — Contact BulkSMSBD Administrator",
    1032: "Server IP Not Whitelisted in BulkSMSBD",
}


def normalize_bd_phone(raw_phone: str):
    """
    Normalize a Bangladeshi mobile number to 13-digit BulkSMSBD format: 8801XXXXXXXXX.
    Returns None if not a valid BD mobile number.
    """
    digits = re.sub(r'\D+', '', str(raw_phone or ''))
    if len(digits) == 11 and digits.startswith('01'):
        digits = '88' + digits
    elif len(digits) == 10 and digits.startswith('1'):
        digits = '880' + digits
    elif len(digits) == 13 and digits.startswith('8801'):
        pass
    elif len(digits) == 14 and digits.startswith('08801'):
        digits = digits[1:]
    else:
        return None

    # Valid BD operator prefixes: 88013..88019
    if len(digits) == 13 and digits.startswith('8801') and digits[4] in '3456789':
        return digits
    return None


def get_bulksmsbd_balance(api_key: str = None):
    """
    Query BulkSMSBD credit balance.
    Returns (success: bool, balance_str: str, message: str).
    """
    key = (api_key or getattr(settings, 'BULKSMSBD_API_KEY', '') or '').strip()
    if not key:
        return False, None, "BulkSMSBD API Key is not configured."

    try:
        resp = requests.get(
            BULKSMSBD_BALANCE_URL,
            params={'api_key': key},
            timeout=10,
        )
        data = {}
        try:
            data = resp.json()
        except Exception:
            return False, None, f"Unexpected response from BulkSMSBD (HTTP {resp.status_code})."

        code = int(data.get('response_code', 0) or 0)
        if code == 202 and 'balance' in data:
            return True, str(data['balance']), "Balance fetched successfully."
        err_msg = data.get('error_message') or BULKSMSBD_STATUS_CODES.get(code) or f"Error code {code}"
        return False, None, f"{err_msg} (Code: {code})"
    except requests.RequestException as exc:
        return False, None, f"Could not reach BulkSMSBD: {exc}"


def send_bulksmsbd_bulk(numbers, message: str, api_key: str = None, sender_id: str = None, chunk_size: int = 100):
    """
    Send an SMS message to a list of BD phone numbers via BulkSMSBD POST API.
    Deduplicates and normalizes all numbers automatically.
    """
    key = (api_key or getattr(settings, 'BULKSMSBD_API_KEY', '') or '').strip()
    sid = (sender_id if sender_id is not None else getattr(settings, 'BULKSMSBD_SENDER_ID', '') or '').strip()
    msg = (message or '').strip()

    if not key:
        return {
            'success': False,
            'sent_count': 0,
            'invalid_count': 0,
            'response_code': 1003,
            'message': 'BulkSMSBD API Key is missing.',
        }
    if not sid:
        return {
            'success': False,
            'sent_count': 0,
            'invalid_count': 0,
            'response_code': 1002,
            'message': 'Approved Sender ID is required (e.g. 880961761XXXX from your BulkSMSBD panel).',
        }
    if not msg:
        return {
            'success': False,
            'sent_count': 0,
            'invalid_count': 0,
            'response_code': 1003,
            'message': 'SMS message body cannot be empty.',
        }

    valid_numbers = []
    seen = set()
    invalid_count = 0
    for raw in numbers:
        norm = normalize_bd_phone(raw)
        if not norm:
            invalid_count += 1
            continue
        if norm not in seen:
            seen.add(norm)
            valid_numbers.append(norm)

    if not valid_numbers:
        return {
            'success': False,
            'sent_count': 0,
            'invalid_count': invalid_count,
            'response_code': 1001,
            'message': 'No valid Bangladeshi mobile numbers found to send.',
        }

    total_sent = 0
    last_code = 202
    errors = []

    for i in range(0, len(valid_numbers), chunk_size):
        chunk = valid_numbers[i:i + chunk_size]
        payload = {
            'api_key': key,
            'type': 'text',
            'number': ','.join(chunk),
            'senderid': sid,
            'message': msg,
        }
        try:
            resp = requests.post(BULKSMSBD_SMS_URL, data=payload, timeout=20)
            try:
                data = resp.json()
            except Exception:
                errors.append(f"HTTP {resp.status_code}: {resp.text[:120]}")
                last_code = resp.status_code
                continue

            code = int(data.get('response_code', 0) or 0)
            last_code = code
            if code == 202:
                total_sent += len(chunk)
            else:
                reason = data.get('error_message') or BULKSMSBD_STATUS_CODES.get(code) or f"Error code {code}"
                errors.append(f"{reason} (Code: {code})")
        except requests.RequestException as exc:
            errors.append(f"Network error: {exc}")
            last_code = 0

    if total_sent > 0 and not errors:
        return {
            'success': True,
            'sent_count': total_sent,
            'invalid_count': invalid_count,
            'response_code': 202,
            'message': f"SMS submitted successfully to {total_sent} recipient(s)!",
        }
    if total_sent > 0 and errors:
        return {
            'success': True,
            'sent_count': total_sent,
            'invalid_count': invalid_count,
            'response_code': last_code,
            'message': f"Partially sent to {total_sent} recipient(s). Some batches failed: {'; '.join(errors)}",
        }
    return {
        'success': False,
        'sent_count': 0,
        'invalid_count': invalid_count,
        'response_code': last_code,
        'message': '; '.join(errors) or 'Failed to send SMS.',
    }
