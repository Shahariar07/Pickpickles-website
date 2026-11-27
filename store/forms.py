import re
# pyrefly: ignore[missing-import]
from django import forms
from .models import Order, Review


FAKE_PHONE_SUBSTRINGS = (
    '1234567',
    '2345678',
    '3456789',
    '4567890',
    '9876543',
    '8765432',
    '7654321',
    '6543210',
    '0123456',
)

FAKE_NAME_EXACT = {
    'test', 'testing', 'tester', 'asdf', 'asdfg', 'qwerty', 'fake',
    'abc', 'abcd', 'xyz', 'none', 'null', 'admin', 'user', 'unknown',
    'na', 'n/a', 'xxx', 'zzz', 'aaa', 'bbb'
}


_BANGLA_DIGIT_MAP = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')


def _count_letter_chars(text: str) -> int:
    """Count alphabetic characters including Bengali vowel signs & combining marks."""
    return sum(1 for ch in (text or '') if ch.isalpha() or ('\u0980' <= ch <= '\u09FF'))


def clean_and_validate_bd_phone(phone_str):
    """
    Validates and standardizes a Bangladeshi mobile number.
    Supports English & Bangla numerals (০-৯), autofill spaces/hyphens/Unicode marks,
    +880 / 880 / 00880 / +88001 prefixes, and 10-digit 1[3-9]XXXXXXXX entries.
    Valid operators: 013, 014, 015, 016, 017, 018, 019.
    Returns:
      (cleaned_phone, error_message)
    """
    if not phone_str:
        return None, "Mobile number is required."

    # Convert Bangla numerals (০-৯) to ASCII digits (0-9) and strip invisible Unicode marks
    normalized = str(phone_str).translate(_BANGLA_DIGIT_MAP).strip()
    normalized = re.sub(r'[\u200b-\u200f\u202a-\u202e\u2066-\u2069]', '', normalized)

    # Reject if unexpected alphabetic letters are present
    if re.search(r'[A-Za-z\u0985-\u09df]', normalized):
        return None, "Please enter a valid 11-digit Bangladeshi mobile number (e.g. 017XXXXXXXX)."

    # Remove whitespace, hyphens, parentheses, dots
    cleaned = re.sub(r'[\s\-\(\)\.]', '', normalized)

    # Reject non-Bangladesh international '+' prefixes (e.g. +1 US numbers)
    if cleaned.startswith('+') and not (cleaned.startswith('+88') or cleaned.startswith('+01')):
        return None, "Please enter a valid Bangladeshi mobile number starting with 01XXXXXXXXX."

    cleaned = cleaned.lstrip('+')

    # Standardize 00880 / 88001 / 880 / 88 / 10-digit 1XXXXXXXXX to 11-digit 01XXXXXXXXX
    if cleaned.startswith('00880') and len(cleaned) == 15:
        cleaned = cleaned[4:]
    elif cleaned.startswith('88001') and len(cleaned) == 14:
        cleaned = '0' + cleaned[4:]
    elif cleaned.startswith('880') and len(cleaned) == 13:
        cleaned = cleaned[2:]
    elif cleaned.startswith('88') and len(cleaned) == 13:
        cleaned = cleaned[2:]
    elif re.match(r'^1[3-9]\d{8}$', cleaned):
        cleaned = '0' + cleaned

    # Must be exactly 11 digits starting with valid BD mobile operator (013 - 019)
    if not re.match(r'^01[3-9]\d{8}$', cleaned):
        return None, "Please enter a valid 11-digit Bangladeshi mobile number (e.g. 017XXXXXXXX or 018XXXXXXXX)."

    # Check the subscriber 8 digits (after 01X) for obvious dummy patterns
    subscriber_part = cleaned[3:]
    # Reject 7 or more identical consecutive digits (e.g. 01700000000, 01711111111)
    if re.search(r'(\d)\1{6,}', cleaned) or len(set(subscriber_part)) <= 1:
        return None, "Please enter a real active mobile number (repeated dummy digits are not allowed)."

    # Reject sequential dummy numbers (e.g. 01712345678, 01787654321)
    if any(seq in subscriber_part for seq in FAKE_PHONE_SUBSTRINGS):
        return None, "Please enter your real active mobile number so our delivery rider can reach you."

    return cleaned, None


class CheckoutForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'customer_email' in self.fields:
            self.fields['customer_email'].required = False
        if 'delivery_city' in self.fields:
            self.fields['delivery_city'].required = False
        if 'delivery_zone' in self.fields:
            self.fields['delivery_zone'].required = False

    class Meta:
        model = Order
        fields = [
            'customer_name',
            'customer_phone',
            'customer_email',
            'delivery_address',
            'delivery_city',
            'delivery_zone',
            'payment_method',
            'payment_sender_number',
            'payment_trx_id',
            'customer_notes',
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Your Full Name (e.g. Tanvir Ahmed)',
                'required': True,
                'id': 'customer_name'
            }),
            'customer_phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '01XXXXXXXXX',
                'required': True,
                'id': 'customer_phone',
                'type': 'tel',
                'maxlength': '24',
                'title': 'Please enter a valid 11-digit Bangladeshi mobile number (e.g. 017XXXXXXXX)'
            }),
            'customer_email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'name@example.com (Optional for invoice)',
                'id': 'customer_email'
            }),
            'delivery_address': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': 'House #, Road #, Sector/Area, Landmark (e.g. House 14, Road 5, Dhanmondi)',
                'required': True,
                'id': 'delivery_address'
            }),
            'delivery_city': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'City / District (e.g. Dhaka, Chattogram)',
                'required': True,
                'id': 'delivery_city'
            }),
            'delivery_zone': forms.Select(attrs={
                'class': 'form-select',
                'id': 'delivery_zone'
            }),
            'payment_method': forms.RadioSelect(attrs={
                'class': 'payment-radio',
                'id': 'payment_method'
            }),
            'payment_sender_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'bKash number used to send money (01XXXXXXXXX)',
                'id': 'payment_sender_number',
                'type': 'tel',
                'maxlength': '24'
            }),
            'payment_trx_id': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. 9BKT78291X',
                'id': 'payment_trx_id'
            }),
            'customer_notes': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': 'Special requests for our kitchen or packaging team (e.g. gift note for a friend, extra safe bubble wrap, or specific packaging instructions)...',
                'id': 'customer_notes'
            }),
        }

    def clean_customer_name(self):
        name = (self.cleaned_data.get('customer_name') or '').strip()
        if len(name) < 2:
            raise forms.ValidationError("Please enter your full name.")
        if _count_letter_chars(name) < 2:
            raise forms.ValidationError("Please enter a valid name using letters.")
        if name.lower() in FAKE_NAME_EXACT or re.search(r'(.)\1{4,}', name.lower()):
            raise forms.ValidationError("Please enter your real full name for delivery.")
        return name

    def clean_customer_phone(self):
        raw_phone = self.cleaned_data.get('customer_phone')
        cleaned_phone, error = clean_and_validate_bd_phone(raw_phone)
        if error:
            raise forms.ValidationError(error)
        return cleaned_phone

    def clean_delivery_address(self):
        addr = (self.cleaned_data.get('delivery_address') or '').strip()
        if len(addr) < 4:
            raise forms.ValidationError("Please enter your delivery address (Area / Road / House).")
        if _count_letter_chars(addr) < 2 or addr.lower() in FAKE_NAME_EXACT or re.search(r'(.)\1{5,}', addr.lower()):
            raise forms.ValidationError("Please provide a valid street or area address so the courier can deliver your parcel.")
        return addr

    def clean(self):
        cleaned_data = super().clean()
        
        # Auto-detect delivery zone and city from delivery address
        addr = cleaned_data.get('delivery_address')
        if addr:
            from .models import detect_dhaka_and_city
            auto_zone, auto_city = detect_dhaka_and_city(addr)
            if not cleaned_data.get('delivery_zone'):
                cleaned_data['delivery_zone'] = auto_zone
            if not cleaned_data.get('delivery_city') or cleaned_data.get('delivery_city') in ('Dhaka', 'Outside Dhaka'):
                cleaned_data['delivery_city'] = auto_city
        else:
            if not cleaned_data.get('delivery_zone'):
                cleaned_data['delivery_zone'] = 'INSIDE_DHAKA'
            if not cleaned_data.get('delivery_city'):
                cleaned_data['delivery_city'] = 'Dhaka'

        payment_method = cleaned_data.get('payment_method')
        sender_number = (cleaned_data.get('payment_sender_number') or '').strip()
        trx_id = (cleaned_data.get('payment_trx_id') or '').strip().upper()

        # Validate MFS payment details
        if payment_method == 'BKASH':
            cleaned_sender, sender_err = clean_and_validate_bd_phone(sender_number)
            if sender_err:
                self.add_error('payment_sender_number', sender_err)
            else:
                cleaned_data['payment_sender_number'] = cleaned_sender
                
            if not trx_id or len(trx_id) < 6 or len(trx_id) > 25:
                self.add_error('payment_trx_id', 'Please enter a valid bKash Transaction ID (TrxID).')
            elif not re.match(r'^[A-Z0-9]+$', trx_id) or len(set(trx_id)) <= 2 or trx_id in ('123456', '1234567', '12345678', 'ABCDEF'):
                self.add_error('payment_trx_id', 'Invalid bKash Transaction ID format. Please check your bKash SMS/App.')
            elif Order.all_objects.filter(payment_trx_id__iexact=trx_id).exists():
                self.add_error('payment_trx_id', 'This bKash Transaction ID (TrxID) has already been used for another order.')
            else:
                cleaned_data['payment_trx_id'] = trx_id

        return cleaned_data


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['reviewer_name', 'reviewer_phone', 'reviewer_location', 'product', 'rating', 'comment']
        widgets = {
            'reviewer_name': forms.TextInput(attrs={
                'class': 'w-full bg-white border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 font-bold placeholder-gray-400 focus:ring-2 focus:ring-emerald-600 focus:border-emerald-600 focus:outline-hidden transition shadow-2xs',
                'placeholder': 'Your Full Name (e.g. Tanvir Ahmed)',
                'required': True
            }),
            'reviewer_phone': forms.TextInput(attrs={
                'class': 'w-full bg-white border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 font-bold placeholder-gray-400 focus:ring-2 focus:ring-emerald-600 focus:border-emerald-600 focus:outline-hidden transition shadow-2xs',
                'placeholder': 'Phone Number (e.g. 017XXXXXXXX)',
                'required': True,
                'type': 'tel',
            }),
            'reviewer_location': forms.TextInput(attrs={
                'class': 'w-full bg-white border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 font-semibold placeholder-gray-400 focus:ring-2 focus:ring-emerald-600 focus:border-emerald-600 focus:outline-hidden transition shadow-2xs',
                'placeholder': 'City or Area (e.g. Gulshan, Dhaka)'
            }),
            'product': forms.Select(attrs={
                'class': 'w-full bg-white border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 font-semibold focus:ring-2 focus:ring-emerald-600 focus:border-emerald-600 focus:outline-hidden transition cursor-pointer shadow-2xs'
            }),
            'rating': forms.Select(choices=[
                (5, '⭐⭐⭐⭐⭐ — 5.0 (Super Crunchy & Delicious)'),
                (4, '⭐⭐⭐⭐ — 4.0 (Really Good)'),
                (3, '⭐⭐⭐ — 3.0 (Average)'),
                (2, '⭐⭐ — 2.0 (Needs Improvement)'),
                (1, '⭐ — 1.0 (Did not like it)')
            ], attrs={
                'class': 'w-full bg-white border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 font-bold focus:ring-2 focus:ring-emerald-600 focus:border-emerald-600 focus:outline-hidden transition cursor-pointer shadow-2xs'
            }),
            'comment': forms.Textarea(attrs={
                'class': 'w-full bg-white border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 font-medium placeholder-gray-400 focus:ring-2 focus:ring-emerald-600 focus:border-emerald-600 focus:outline-hidden transition shadow-2xs',
                'rows': 3,
                'placeholder': 'Tell us how you enjoyed the pickles (crunchiness, taste, spice level, food pairings)...',
                'required': True
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'product' in self.fields:
            self.fields['product'].required = False
            self.fields['product'].empty_label = "🥒 All Pickles (General Pickpickles Experience)"
        if 'reviewer_phone' in self.fields:
            self.fields['reviewer_phone'].required = True

    def clean_reviewer_phone(self):
        phone = (self.cleaned_data.get('reviewer_phone') or '').strip()
        digits = ''.join(c for c in phone if c.isdigit())
        if len(digits) < 10:
            raise forms.ValidationError("Please enter a valid phone number (at least 10-11 digits, e.g. 017XXXXXXXX).")

        last10 = digits[-10:]
        from django.db.models import Q
        from .models import Order

        verified_phones = (
            Order.objects.filter(is_deleted=False)
            .filter(Q(order_status__in=['OUT_FOR_DELIVERY', 'DELIVERED']) | Q(payment_status='PAID'))
            .exclude(order_status='CANCELLED')
            .values_list('customer_phone', flat=True)
        )
        is_verified_buyer = any(
            ''.join(c for c in str(p or '') if c.isdigit())[-10:] == last10
            for p in verified_phones
            if len(''.join(c for c in str(p or '') if c.isdigit())) >= 10
        )
        if not is_verified_buyer:
            raise forms.ValidationError(
                "শুধুমাত্র আমাদের আসল কাস্টমাররাই (যাদের অর্ডার শিপড বা ডেলিভার্ড হয়েছে) রিভিউ দিতে পারবেন। "
                "অর্ডার করার সময় ব্যবহৃত ফোন নম্বরটি দিন। (Only verified Pickpickles customers can submit a review.)"
            )
        return phone

    def clean(self):
        cleaned_data = super().clean()
        phone = (cleaned_data.get('reviewer_phone') or '').strip()
        product = cleaned_data.get('product')
        digits = ''.join(c for c in phone if c.isdigit())
        if len(digits) >= 10:
            last10 = digits[-10:]
            qs = Review.objects.filter(product=product)
            for existing_phone in qs.values_list('reviewer_phone', flat=True):
                ex_digits = ''.join(c for c in str(existing_phone or '') if c.isdigit())
                if len(ex_digits) >= 10 and ex_digits[-10:] == last10:
                    raise forms.ValidationError(
                        "এই নম্বর থেকে এই প্রোডাক্টের জন্য ইতিমধ্যেই একটি রিভিউ জমা দেওয়া হয়েছে। (You have already submitted a review for this selection.)"
                    )
        return cleaned_data
