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


def clean_and_validate_bd_phone(phone_str):
    """
    Validates and standardizes a Bangladeshi mobile number.
    Valid operators: 013, 014, 015, 016, 017, 018, 019.
    Also rejects obvious dummy/fake phone patterns (e.g. 01700000000, 01712345678).
    Returns:
      (cleaned_phone, error_message)
    """
    if not phone_str:
        return None, "Mobile number is required."
    
    # Remove whitespace, hyphens, parentheses, dots
    cleaned = re.sub(r'[\s\-\(\)\.]', '', str(phone_str).strip())
    
    # Standardize +88 / 88 prefix to local 11-digit format
    if cleaned.startswith('+880'):
        cleaned = cleaned[3:]
    elif cleaned.startswith('880'):
        cleaned = cleaned[2:]
    elif cleaned.startswith('+88'):
        cleaned = cleaned[3:]
    elif cleaned.startswith('88') and len(cleaned) == 13:
        cleaned = cleaned[2:]
        
    # Must be exactly 11 digits starting with valid BD mobile operator (013 - 019)
    if not re.match(r'^01[3-9]\d{8}$', cleaned):
        return None, "Please enter a valid 11-digit Bangladeshi mobile number (e.g. 017XXXXXXXX or 018XXXXXXXX)."

    # Check the subscriber 8 digits (after 01X) for fake/dummy patterns
    subscriber_part = cleaned[3:]
    # Reject 6 or more identical consecutive digits (e.g. 01700000000, 01711111111, 01899999999)
    if re.search(r'(\d)\1{5,}', cleaned):
        return None, "Please enter a real active mobile number (repeated dummy digits are not allowed)."

    # Reject sequential dummy numbers (e.g. 01712345678, 01787654321)
    if any(seq in subscriber_part for seq in FAKE_PHONE_SUBSTRINGS):
        return None, "Please enter your real active mobile number so our delivery rider can reach you."

    # Reject if subscriber part has only 1 or 2 unique digits (e.g. 01712121212)
    if len(set(subscriber_part)) <= 2:
        return None, "Please enter a valid active mobile number."
        
    return cleaned, None


class CheckoutForm(forms.ModelForm):
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
                'maxlength': '15',
                'pattern': r'(?:\+?88)?01[3-9]\d{8}',
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
                'maxlength': '15'
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
        if len(name) < 3:
            raise forms.ValidationError("Please enter your full name (at least 3 characters).")
        # Must contain at least 2 alphabetic characters (English or Bengali)
        alpha_count = sum(1 for ch in name if ch.isalpha())
        if alpha_count < 2:
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
        if len(addr) < 8:
            raise forms.ValidationError("Please enter your complete delivery address (House/Road/Area, at least 8 characters).")
        alpha_count = sum(1 for ch in addr if ch.isalpha())
        if alpha_count < 3 or addr.lower() in FAKE_NAME_EXACT or re.search(r'(.)\1{5,}', addr.lower()):
            raise forms.ValidationError("Please provide a valid, detailed street/area address so the courier can deliver your parcel.")
        return addr

    def clean(self):
        cleaned_data = super().clean()
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
        fields = ['reviewer_name', 'reviewer_location', 'product', 'rating', 'comment']
        widgets = {
            'reviewer_name': forms.TextInput(attrs={
                'class': 'w-full bg-white border border-gray-300 rounded-xl px-4 py-3 text-sm text-gray-900 font-bold placeholder-gray-400 focus:ring-2 focus:ring-emerald-600 focus:border-emerald-600 focus:outline-hidden transition shadow-2xs',
                'placeholder': 'Your Full Name (e.g. Tanvir Ahmed)',
                'required': True
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
                'placeholder': 'Tell us how you enjoyed the pickles (taste, crunchiness, pairing with burgers/rice)...',
                'required': True
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'product' in self.fields:
            self.fields['product'].required = False
            self.fields['product'].empty_label = "🥒 Pickpickles (General Pickle Experience)"
