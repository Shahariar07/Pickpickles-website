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


def _get_order_sms_log_path():
    import os
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    return os.path.join(settings.MEDIA_ROOT, 'order_sms_sent.json')


def get_all_order_sms_sent_map() -> dict:
    import os, json
    path = _get_order_sms_log_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_order_sms_sent_statuses(order_number: str) -> set:
    sent_map = get_all_order_sms_sent_map()
    return set(sent_map.get(str(order_number), []))


def _mark_order_sms_sent(order_number: str, status: str):
    import json
    sent_map = get_all_order_sms_sent_map()
    key = str(order_number)
    statuses = list(sent_map.get(key, []))
    if status not in statuses:
        statuses.append(status)
    sent_map[key] = statuses
    try:
        with open(_get_order_sms_log_path(), 'w', encoding='utf-8') as f:
            json.dump(sent_map, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_order_sms_history_path():
    import os
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    return os.path.join(settings.MEDIA_ROOT, 'order_sms_history.json')


def _parse_sent_at_dt(sent_at_str: str):
    from datetime import datetime
    from django.utils import timezone
    raw = (sent_at_str or '').strip()
    if raw:
        for fmt in ('%d %b %Y, %I:%M %p', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
            try:
                dt = datetime.strptime(raw, fmt)
                return timezone.make_aware(dt, timezone.get_current_timezone())
            except Exception:
                continue
    return timezone.now()


def _read_json_sms_history_raw() -> tuple[list, bool]:
    """
    Read combined history from order_sms_history.json and legacy sms_campaign_history.json.
    Returns (entries_list, read_ok) where read_ok is False if the primary JSON file exists
    and failed to parse (so callers never overwrite corrupted/locked files with an empty list).
    """
    import os, json
    history = []
    read_ok = True
    path = _get_order_sms_history_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    history = data
        except Exception:
            read_ok = False

    legacy_path = os.path.join(settings.MEDIA_ROOT, 'sms_campaign_history.json')
    if os.path.exists(legacy_path):
        try:
            with open(legacy_path, 'r', encoding='utf-8') as f:
                legacy = json.load(f)
                if isinstance(legacy, list):
                    existing_sigs = {(h.get('sent_at'), h.get('message'), h.get('sms_type')) for h in history}
                    for item in legacy:
                        sig = (item.get('sent_at'), item.get('message'), 'CAMPAIGN')
                        if sig not in existing_sigs:
                            recs = item.get('recipients') or []
                            history.append({
                                'sent_at': item.get('sent_at', ''),
                                'order_number': '',
                                'customer_name': '',
                                'phone': recs[0].get('phone', '') if len(recs) == 1 else '',
                                'sms_type': 'CAMPAIGN',
                                'sms_type_label': 'Bulk Campaign',
                                'audience_label': item.get('audience_label', ''),
                                'recipient_count': item.get('recipient_count', len(recs)),
                                'recipients': recs,
                                'message': item.get('message', ''),
                                'success': bool(item.get('success')),
                                'status_message': item.get('status_message', ''),
                                'sent_by': item.get('sent_by', ''),
                            })
        except Exception:
            pass
    return history, read_ok


def _sync_json_history_to_db():
    """
    One-time / incremental import from JSON history files into SMSLog DB table
    so previous dates' SMS history is never lost.
    """
    try:
        from django.db import OperationalError, ProgrammingError
        from dashboard.models import SMSLog
        existing_sigs = set(
            SMSLog.objects.values_list('sent_at_display', 'phone', 'sms_type', 'message')
        )
    except Exception:
        return False

    json_entries, _ = _read_json_sms_history_raw()
    if not json_entries:
        return True

    to_create = []
    for item in json_entries:
        sent_at = str(item.get('sent_at') or '').strip()
        phone = str(item.get('phone') or '').strip()
        sms_type = str(item.get('sms_type') or 'PENDING').strip()
        message = str(item.get('message') or '')
        sig = (sent_at, phone, sms_type, message)
        if sig in existing_sigs:
            continue
        existing_sigs.add(sig)
        recs = item.get('recipients') or []
        to_create.append(SMSLog(
            sms_type=sms_type[:32],
            sms_type_label=str(item.get('sms_type_label') or ORDER_SMS_TYPE_LABELS.get(sms_type, sms_type))[:64],
            order_number=str(item.get('order_number') or '')[:64],
            customer_name=str(item.get('customer_name') or '')[:150],
            phone=phone[:40],
            audience_label=str(item.get('audience_label') or '')[:120],
            recipient_count=int(item.get('recipient_count') or (len(recs) if recs else 1)),
            recipients_json=recs,
            message=message,
            success=bool(item.get('success')),
            status_message=str(item.get('status_message') or ''),
            sent_by=str(item.get('sent_by') or '')[:120],
            sent_at_display=sent_at[:64],
            created_at=_parse_sent_at_dt(sent_at),
        ))

    if to_create:
        try:
            SMSLog.objects.bulk_create(to_create)
        except Exception:
            pass
    return True


def get_order_sms_history() -> list:
    if _sync_json_history_to_db():
        try:
            from dashboard.models import SMSLog
            return [log.to_dict() for log in SMSLog.objects.all()]
        except Exception:
            pass
    history, _ = _read_json_sms_history_raw()
    return history


ORDER_SMS_TYPE_LABELS = {
    'PENDING': 'Order Placed',
    'CONFIRMED': 'Order Confirmed',
    'OUT_FOR_DELIVERY': 'Dispatched',
    'REFILL': 'Refill Reminder',
    'CAMPAIGN': 'Bulk Campaign',
}


def _save_sms_history_entry(entry: dict):
    import os, json, tempfile

    # 1. Persist to database (primary, concurrency-safe, unlimited retention)
    try:
        from dashboard.models import SMSLog
        sent_at = str(entry.get('sent_at') or '').strip()
        recs = entry.get('recipients') or []
        SMSLog.objects.create(
            sms_type=str(entry.get('sms_type') or 'PENDING')[:32],
            sms_type_label=str(entry.get('sms_type_label') or '')[:64],
            order_number=str(entry.get('order_number') or '')[:64],
            customer_name=str(entry.get('customer_name') or '')[:150],
            phone=str(entry.get('phone') or '')[:40],
            audience_label=str(entry.get('audience_label') or '')[:120],
            recipient_count=int(entry.get('recipient_count') or (len(recs) if recs else 1)),
            recipients_json=recs,
            message=str(entry.get('message') or ''),
            success=bool(entry.get('success')),
            status_message=str(entry.get('status_message') or ''),
            sent_by=str(entry.get('sent_by') or '')[:120],
            sent_at_display=sent_at[:64],
            created_at=_parse_sent_at_dt(sent_at),
        )
    except Exception:
        pass

    # 2. Mirror atomically to JSON without truncation (never overwrite if read failed)
    history, read_ok = _read_json_sms_history_raw()
    if not read_ok:
        return
    history.insert(0, entry)
    path = _get_order_sms_history_path()
    try:
        dir_name = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(prefix='sms_hist_', suffix='.tmp', dir=dir_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except Exception:
        pass


def _log_order_sms_event(order, sms_type: str, message: str, success: bool, status_message: str = ''):
    from django.utils import timezone
    _save_sms_history_entry({
        'sent_at': timezone.localtime(timezone.now()).strftime('%d %b %Y, %I:%M %p'),
        'order_number': getattr(order, 'order_number', ''),
        'customer_name': (getattr(order, 'customer_name', '') or '').strip(),
        'phone': (getattr(order, 'customer_phone', '') or '').strip(),
        'sms_type': sms_type,
        'sms_type_label': ORDER_SMS_TYPE_LABELS.get(sms_type, sms_type),
        'message': message,
        'success': bool(success),
        'status_message': status_message,
        'recipient_count': 1,
        'recipients': [],
        'audience_label': '',
    })


def log_campaign_sms_event(audience_label: str, recipients: list, message: str, success: bool, status_message: str = '', sent_by: str = ''):
    from django.utils import timezone
    _save_sms_history_entry({
        'sent_at': timezone.localtime(timezone.now()).strftime('%d %b %Y, %I:%M %p'),
        'order_number': '',
        'customer_name': '',
        'phone': recipients[0]['phone'] if len(recipients) == 1 else '',
        'sms_type': 'CAMPAIGN',
        'sms_type_label': 'Bulk Campaign',
        'audience_label': audience_label,
        'recipient_count': len(recipients),
        'recipients': recipients,
        'message': message,
        'success': bool(success),
        'status_message': status_message,
        'sent_by': sent_by,
    })


def send_order_status_sms(order, new_status: str, old_status: str = None, force: bool = False):
    """
    Send a concise 1-SMS notification via BulkSMSBD when an order transitions to
    CONFIRMED or OUT_FOR_DELIVERY (or manually via force=True).
    Records sent status in media/order_sms_sent.json so UI can gray out already-sent buttons.
    """
    if not order or not getattr(order, 'customer_phone', None):
        return {'success': False, 'skipped': True, 'message': 'Missing customer phone.'}
    if not force and new_status == old_status:
        return {'success': False, 'skipped': True, 'message': 'No status change.'}
    if new_status in get_order_sms_sent_statuses(order.order_number):
        return {'success': False, 'skipped': True, 'message': 'SMS already sent and locked for this status.'}
    if not force and new_status == 'CONFIRMED':
        return {'success': False, 'skipped': True, 'message': 'Auto SMS on confirmation is disabled.'}

    total_int = int(round(float(order.total_amount or 0)))
    if new_status == 'PENDING':
        msg = (
            f"Pick Pickles: Order #{order.order_number} placed! "
            f"Total: Tk {total_int}. We will confirm & pack soon. Track: www.pickpickles.xyz/track/"
        )
    elif new_status == 'CONFIRMED':
        msg = (
            f"Pick Pickles: Order #{order.order_number} confirmed! "
            f"Total: Tk {total_int}. Freshly packed for you. Track: www.pickpickles.xyz/track/"
        )
    elif new_status == 'OUT_FOR_DELIVERY':
        pay_text = "Payment: PAID" if getattr(order, 'payment_status', '') == 'PAID' else f"COD: Tk {total_int}"
        msg = (
            f"Pick Pickles: Order #{order.order_number} dispatched! "
            f"{pay_text}. Please refrigerate upon arrival! Track: www.pickpickles.xyz/track/"
        )
    elif force:
        status_label = order.get_order_status_display() if hasattr(order, 'get_order_status_display') else new_status
        msg = (
            f"Pick Pickles: Order #{order.order_number} ({status_label}). "
            f"Total: Tk {total_int}. Track: www.pickpickles.xyz/track/"
        )
    else:
        return {'success': False, 'skipped': True, 'message': 'Status does not trigger auto SMS.'}

    try:
        res = send_bulksmsbd_bulk([order.customer_phone], msg)
        if res.get('success'):
            _mark_order_sms_sent(order.order_number, new_status)
        _log_order_sms_event(order, new_status, msg, bool(res.get('success')), res.get('message', ''))
        return res
    except Exception as exc:
        _log_order_sms_event(order, new_status, msg, False, str(exc))
        return {'success': False, 'skipped': False, 'message': str(exc)}


def send_order_refill_reminder_sms(order):
    """
    Send a 1-SMS refill / repeat order reminder to a past customer's mobile number.
    """
    if not order or not getattr(order, 'customer_phone', None):
        return {'success': False, 'message': 'Customer phone number is missing.'}

    msg = (
        "Pick Pickles: Time for a pickle refill? Enjoy 5% OFF on your next order "
        "with code WINTER5 (Min. 2 jars). Order: www.pickpickles.xyz"
    )
    try:
        res = send_bulksmsbd_bulk([order.customer_phone], msg)
        _log_order_sms_event(order, 'REFILL', msg, bool(res.get('success')), res.get('message', ''))
        return res
    except Exception as exc:
        _log_order_sms_event(order, 'REFILL', msg, False, str(exc))
        return {'success': False, 'message': str(exc)}
