import uuid
from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, default="fa-jar", help_text="FontAwesome icon class name")

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    SPICE_CHOICES = [
        ('MILD', 'Mild & Refreshing 🌿'),
        ('MEDIUM', 'Medium Zest 🌶️'),
        ('HOT', 'Hot & Tangy 🔥'),
        ('NAGA', 'Fire Naga Hot 💣'),
    ]

    CUT_CHOICES = [
        ('SPEARS', 'Spears / Quartered'),
        ('CHIPS', 'Crinkle Cut Chips / Slices'),
        ('WHOLE', 'Whole Pickles'),
        ('RELISH', 'Sweet & Savory Relish'),
    ]

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    tagline = models.CharField(max_length=255, help_text="Catchy tagline, e.g., 'Classic Artisanal Deli Crunch with Garlic & Whole Spices'")
    description = models.TextField()
    flavor_profile = models.CharField(max_length=255, default="Garlic, Bay Leaf, Peppercorn, Mustard Seed")
    pairing_suggestions = models.CharField(max_length=255, default="Smash Burgers, Fried Chicken, Shawarma, Beef Tehari, Biryani, Bhuna Khichuri, Daal-Rice")
    cut_style = models.CharField(max_length=20, choices=CUT_CHOICES, default='CHIPS')
    spice_level = models.CharField(max_length=20, choices=SPICE_CHOICES, default='MILD')
    crunch_rating = models.PositiveSmallIntegerField(default=5, help_text="Rating out of 5")
    jar_weight_grams = models.PositiveIntegerField(default=600, help_text="Weight in grams (e.g. 600g)")
    
    price_bdt = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price in BDT (৳)")
    original_price_bdt = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Strike-through price if on sale")
    
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    image_url = models.CharField(max_length=500, blank=True, help_text="Optional fallback image URL or static asset path")
    
    is_featured = models.BooleanField(default=False)
    is_in_stock = models.BooleanField(default=True)
    stock_count = models.PositiveIntegerField(default=50)
    
    ingredients = models.TextField(default="Fresh Cucumbers, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic, Bay Leaf (Tejpata), Mustard Seeds, Coriander, Black Peppercorn.")
    shelf_life = models.CharField(max_length=150, default="Always keep refrigerated for maximum crunch. Best enjoyed within 1 month.")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def discount_percent(self):
        if self.original_price_bdt and self.original_price_bdt > self.price_bdt:
            saving = self.original_price_bdt - self.price_bdt
            return round((saving / self.original_price_bdt) * 100)
        return 0

    @property
    def average_rating(self):
        approved = self.reviews.filter(is_approved=True)
        if approved.exists():
            avg = approved.aggregate(models.Avg('rating'))['rating__avg']
            return round(avg, 1) if avg else self.crunch_rating
        return self.crunch_rating

    @property
    def reviews_count(self):
        return self.reviews.filter(is_approved=True).count()

    @property
    def primary_image_url(self):
        if self.image:
            return self.image.url
        if self.image_url:
            return self.image_url
        return "/static/images/pickle_default.png"

    def __str__(self):
        return f"{self.name} ({self.jar_weight_grams}g) - ৳{self.price_bdt}"


class ActiveOrderManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllOrderManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset()


class TrashOrderManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=True)


import math
from decimal import Decimal


def calculate_pathao_delivery_fee(weight_grams: int, zone: str = 'INSIDE_DHAKA') -> Decimal:
    """
    Calculates delivery fee based on total weight in grams and delivery zone according to Pathao Courier pricing.
    - Inside Dhaka: Base ৳70 (up to 1kg) + ৳20/extra kg
    - Outside Dhaka / Nationwide: Base ৳130 (up to 1kg) + ৳25/extra kg
    """
    if not weight_grams or weight_grams <= 0:
        weight_grams = 600
        
    weight_kg = weight_grams / 1000.0
    zone = (zone or 'INSIDE_DHAKA').upper()

    # 1. Attempt live Pathao Courier API calculation if credentials configured
    try:
        from store.pathao import PathaoCourierService
        service = PathaoCourierService()
        if service.is_configured():
            api_fee = service.calculate_price(weight_kg=weight_kg, zone=zone)
            if api_fee is not None:
                return api_fee
    except Exception:
        pass

    # 2. Exact Pathao rate card fallback
    billing_weight_kg = max(1, math.ceil(weight_kg))
    extra_kg = max(0, billing_weight_kg - 1)
    
    if zone in ['INSIDE_DHAKA', 'INSIDE_FARIDPUR']:
        base_fee = Decimal('70.00')
        extra_fee_per_kg = Decimal('20.00')
    else:  # OUTSIDE_DHAKA / NATIONWIDE / DHAKA_CITY
        base_fee = Decimal('130.00')
        extra_fee_per_kg = Decimal('25.00')
        
    return base_fee + (Decimal(str(extra_kg)) * extra_fee_per_kg)


class Order(models.Model):
    ZONE_CHOICES = [
        ('INSIDE_DHAKA', 'Inside Dhaka City'),
        ('OUTSIDE_DHAKA', 'Outside Dhaka (Nationwide)'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('BKASH_ONLINE', 'bKash Direct Online Payment'),
        ('COD', 'Cash on Delivery (COD)'),
        ('BKASH', 'bKash (Send Money / Manual)'),
        ('NAGAD', 'Nagad (Send Money / Manual)'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('UNPAID', 'Unpaid (COD)'),
        ('PENDING_PAYMENT', 'Pending bKash Online Payment'),
        ('PENDING_VERIFICATION', 'Pending Manual Verification'),
        ('PAID', 'Payment Received & Verified'),
        ('REFUNDED', 'Refunded'),
        ('FAILED', 'Payment Failed'),
    ]

    ORDER_STATUS_CHOICES = [
        ('PENDING', 'Pending Confirmation'),
        ('CONFIRMED', 'Order Confirmed & In Queue'),
        ('PACKING', 'Packing Fresh Jars'),
        ('OUT_FOR_DELIVERY', 'Out for Delivery / Shipped via Courier'),
        ('DELIVERED', 'Delivered 🎉'),
        ('CANCELLED', 'Cancelled / Returned'),
    ]

    order_number = models.CharField(max_length=32, unique=True, editable=False)
    
    # Customer Details
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=20)
    customer_email = models.EmailField(blank=True, null=True)
    
    # Address
    delivery_address = models.TextField(help_text="House, Road, Area, Landmark")
    delivery_city = models.CharField(max_length=100, default="Dhaka")
    delivery_zone = models.CharField(max_length=30, choices=ZONE_CHOICES, default='INSIDE_DHAKA')
    
    # Financials in BDT
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=70.00)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Pathao Courier Tracking & Consignment
    pathao_consignment_id = models.CharField(max_length=100, blank=True, null=True, help_text="Pathao Consignment ID")
    pathao_tracking_code = models.CharField(max_length=100, blank=True, null=True, help_text="Pathao Public Tracking Code")
    pathao_order_status = models.CharField(max_length=50, blank=True, null=True, help_text="Status synced from Pathao Courier")
    
    # Payment Info
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, default='BKASH_ONLINE')
    payment_status = models.CharField(max_length=30, choices=PAYMENT_STATUS_CHOICES, default='UNPAID')
    payment_sender_number = models.CharField(max_length=20, blank=True, help_text="Customer bKash/Nagad number")
    payment_trx_id = models.CharField(max_length=100, blank=True, help_text="bKash / Nagad Transaction ID")
    bkash_payment_id = models.CharField(max_length=100, blank=True, null=True, help_text="Official bKash PGW Payment ID")
    
    # Order Status & Management
    order_status = models.CharField(max_length=30, choices=ORDER_STATUS_CHOICES, default='PENDING')
    customer_notes = models.TextField(blank=True, help_text="Customer special request")
    admin_notes = models.TextField(blank=True, help_text="Internal notes / rider info")
    
    # Soft Delete / Safety Fields
    is_deleted = models.BooleanField(default=False, db_index=True, help_text="Soft deleted / moved to trash")
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when moved to trash")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Managers
    objects = ActiveOrderManager()
    all_objects = AllOrderManager()
    trash_objects = TrashOrderManager()

    class Meta:
        ordering = ['-created_at']
        base_manager_name = 'all_objects'

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def save(self, *args, **kwargs):
        if not self.order_number:
            import re
            # Sequential periodical order numbering starting from PKP-00001 (e.g. PKP-00001, PKP-00002, ...)
            existing_pks = Order.all_objects.values_list('order_number', flat=True)
            max_num = 0
            for onum in existing_pks:
                match = re.search(r'^(?:PKP-|order-|ORD-)?0*(\d{1,5})$', str(onum).strip(), re.IGNORECASE)
                if match:
                    try:
                        val = int(match.group(1))
                        if val < 100000:
                            max_num = max(max_num, val)
                    except ValueError:
                        pass
            
            candidate = max_num + 1
            cand_str = f"PKP-{candidate:05d}"
            while Order.all_objects.filter(order_number=cand_str).exists():
                candidate += 1
                cand_str = f"PKP-{candidate:05d}"
            self.order_number = cand_str
        super().save(*args, **kwargs)

    @property
    def total_items_count(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_weight_grams(self):
        return sum(item.jar_weight_grams * item.quantity for item in self.items.all())

    @property
    def total_weight_kg(self):
        return round(self.total_weight_grams / 1000.0, 2)

    @property
    def billing_weight_kg(self):
        return max(1, math.ceil(self.total_weight_grams / 1000.0))

    @property
    def badge_color(self):
        colors = {
            'PENDING': 'bg-amber-100 text-amber-800 border-amber-300',
            'CONFIRMED': 'bg-blue-100 text-blue-800 border-blue-300',
            'PACKING': 'bg-purple-100 text-purple-800 border-purple-300',
            'OUT_FOR_DELIVERY': 'bg-indigo-100 text-indigo-800 border-indigo-300',
            'DELIVERED': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'CANCELLED': 'bg-rose-100 text-rose-800 border-rose-300',
        }
        return colors.get(self.order_status, 'bg-gray-100 text-gray-800')

    @property
    def customer_score(self):
        """
        Calculates customer delivery trust & fraud risk score based on recipient phone order history.
        """
        from django.db.models import Sum
        clean_digits = ''.join(c for c in (self.customer_phone or '') if c.isdigit())
        last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
        if not last_10:
            return {
                'score': 100,
                'rate': '100%',
                'stars': '5.0',
                'total_orders': 1,
                'delivered_count': 0,
                'cancelled_count': 0,
                'returned_count': 0,
                'in_transit_count': 1,
                'total_spent': 0,
                'badge_class': 'bg-emerald-100 text-emerald-800 border-emerald-300',
                'icon': 'fa-solid fa-circle-check text-emerald-600',
                'label': '🟢 Good Client',
                'short_label': '🟢 Verified',
                'risk_level': 'SAFE',
                'risk_title': 'Good / Verified',
                'text': 'Verified Recipient Phone'
            }
        
        all_orders = Order.all_objects.filter(customer_phone__icontains=last_10)
        total = all_orders.count()
        delivered = all_orders.filter(order_status='DELIVERED').count()
        cancelled = all_orders.filter(order_status='CANCELLED').count()
        in_transit = all_orders.filter(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY']).count()
        
        # Check returns from dashboard.OrderReturn or cancelled orders
        try:
            from dashboard.models import OrderReturn
            returned = OrderReturn.objects.filter(order__in=all_orders).count()
        except Exception:
            returned = cancelled

        delivered_orders_sum = all_orders.filter(order_status='DELIVERED').aggregate(total_spent=Sum('total_amount'))['total_spent'] or 0

        common_stats = {
            'total_orders': total,
            'delivered_count': delivered,
            'cancelled_count': cancelled,
            'returned_count': max(returned, cancelled),
            'in_transit_count': in_transit,
            'total_spent': delivered_orders_sum,
        }
        
        if total <= 1:
            return {
                **common_stats,
                'score': 100,
                'rate': '100%',
                'stars': '5.0',
                'badge_class': 'bg-blue-50 text-blue-800 border-blue-200',
                'icon': 'fa-solid fa-user-check text-blue-600',
                'label': 'New Client (1st Order)',
                'short_label': '🔵 New (1st)',
                'risk_level': 'NEW',
                'risk_title': 'New Customer (1st Order)',
                'text': '1st Order on Pickpickles • Verify Address'
            }
        
        success_rate = round((delivered / total) * 100) if total > 0 else 100
        if cancelled == 0 and returned == 0:
            return {
                **common_stats,
                'score': 100,
                'rate': '100%',
                'stars': '5.0',
                'badge_class': 'bg-emerald-50 text-emerald-800 border-emerald-200',
                'icon': 'fa-solid fa-shield-check text-emerald-600',
                'label': f'Safe Client ({total} Orders)',
                'short_label': f'🟢 Safe ({total} Orders)',
                'risk_level': 'GOOD',
                'risk_title': '100% Safe Customer (0 Return)',
                'text': f'{total} Orders • 100% Delivery Success'
            }
        elif success_rate >= 70:
            return {
                **common_stats,
                'score': success_rate,
                'rate': f'{success_rate}%',
                'stars': f'{round(success_rate / 20.0, 1)}',
                'badge_class': 'bg-amber-50 text-amber-900 border-amber-200',
                'icon': 'fa-solid fa-circle-exclamation text-amber-600',
                'label': f'Moderate Risk ({success_rate}%)',
                'short_label': f'🟡 {success_rate}% ({total} Orders)',
                'risk_level': 'MODERATE',
                'risk_title': f'Moderate Risk ({cancelled} Cancellations)',
                'text': f'{delivered} Delivered / {total} Total Orders'
            }
        else:
            return {
                **common_stats,
                'score': success_rate,
                'rate': f'{success_rate}%',
                'stars': f'{round(success_rate / 20.0, 1)}',
                'badge_class': 'bg-rose-50 text-rose-800 border-rose-200',
                'icon': 'fa-solid fa-triangle-exclamation text-rose-600',
                'label': f'Risky Client ({success_rate}%)',
                'short_label': f'🔴 Risky ({success_rate}%)',
                'risk_level': 'RISKY',
                'risk_title': f'High Return Risk ({cancelled} Returned)',
                'text': f'{cancelled} Returned / Cancelled Orders'
            }

    def sync_pathao_status(self):
        """
        Syncs live consignment tracking status from Pathao Courier Developer API and updates order_status.
        """
        if not self.pathao_consignment_id:
            return None
        try:
            from store.pathao import PathaoCourierService
            service = PathaoCourierService()
            if not service.is_configured():
                return None
            res = service.get_order_info(self.pathao_consignment_id)
            if res.get('success') and res.get('data'):
                info = res['data']
                raw_status = str(info.get('order_status') or info.get('delivery_status') or info.get('order_status_slug') or '').strip()
                if raw_status:
                    self.pathao_order_status = raw_status
                    clean = raw_status.lower().replace('-', '_').replace(' ', '_')
                    
                    status_map = {
                        'pending': 'PENDING',
                        'created': 'PENDING',
                        'draft': 'PENDING',
                        'pickup_requested': 'PENDING',
                        'pickup_assigned': 'CONFIRMED',
                        'assigned_for_pickup': 'CONFIRMED',
                        'picked_up': 'PACKING',
                        'received_at_hub': 'PACKING',
                        'in_transit': 'OUT_FOR_DELIVERY',
                        'sent_to_hub': 'OUT_FOR_DELIVERY',
                        'out_for_delivery': 'OUT_FOR_DELIVERY',
                        'assigned_for_delivery': 'OUT_FOR_DELIVERY',
                        'delivered': 'DELIVERED',
                        'partial_delivery': 'DELIVERED',
                        'returned': 'CANCELLED',
                        'return_in_progress': 'CANCELLED',
                        'cancelled': 'CANCELLED',
                        'delivery_failed': 'CANCELLED',
                    }
                    if clean in status_map:
                        mapped = status_map[clean]
                        if self.order_status != mapped:
                            self.order_status = mapped
                            if mapped == 'DELIVERED' and self.payment_status == 'UNPAID':
                                self.payment_status = 'PAID'
                    self.save(update_fields=['pathao_order_status', 'order_status', 'payment_status'])
                    return raw_status
        except Exception:
            pass
        return self.pathao_order_status

    def __str__(self):
        return f"Order #{self.order_number} - {self.customer_name} (৳{self.total_amount})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name='order_items')
    product_name = models.CharField(max_length=200)
    jar_weight_grams = models.PositiveIntegerField(default=600)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    def save(self, *args, **kwargs):
        self.total_price = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}x {self.product_name} in #{self.order.order_number}"


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    reviewer_name = models.CharField(max_length=100)
    reviewer_location = models.CharField(max_length=100, default="Dhaka, BD")
    rating = models.PositiveSmallIntegerField(default=5)
    comment = models.TextField()
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reviewer_name} on {self.product.name} ({self.rating}★)"
