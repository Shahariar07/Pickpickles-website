from django import forms
from .models import Order, Review


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
                'type': 'tel'
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
                'placeholder': 'bKash number used to send money',
                'id': 'payment_sender_number'
            }),
            'payment_trx_id': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. 9BKT78291X',
                'id': 'payment_trx_id'
            }),
            'customer_notes': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 2,
                'placeholder': 'Any special delivery instructions or requests? (Optional)',
                'id': 'customer_notes'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        customer_phone = (cleaned_data.get('customer_phone') or '').strip()
        payment_method = cleaned_data.get('payment_method')
        sender_number = (cleaned_data.get('payment_sender_number') or '').strip()
        trx_id = (cleaned_data.get('payment_trx_id') or '').strip()

        # Validate main customer phone
        if customer_phone:
            if len(customer_phone) < 11 or not customer_phone.replace('+', '').isdigit():
                self.add_error('customer_phone', 'Mobile number is not valid.')

        # Validate MFS payment details
        if payment_method == 'BKASH':
            if not sender_number or len(sender_number) < 11 or not sender_number.replace('+', '').isdigit():
                self.add_error('payment_sender_number', 'Mobile number is not valid.')
                
            if not trx_id or len(trx_id) < 6:
                self.add_error('payment_trx_id', 'Transaction ID is not valid.')

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
