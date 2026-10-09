import os
import uuid
from django.conf import settings
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
    pairing_suggestions = models.CharField(max_length=255, default="Smash Burgers, Fried Chicken, Shawarma, Beef Tehari, Biryani, Bhuna Khichuri, Steamed Rice")
    cut_style = models.CharField(max_length=20, choices=CUT_CHOICES, default='CHIPS')
    spice_level = models.CharField(max_length=20, choices=SPICE_CHOICES, default='MILD')
    crunch_rating = models.PositiveSmallIntegerField(default=5, help_text="Rating out of 5")
    jar_weight_grams = models.PositiveIntegerField(default=600, help_text="Net Weight in grams (e.g. 600g)")
    gross_weight_grams = models.PositiveIntegerField(default=850, help_text="Gross weight for delivery in grams (e.g. 850g)")
    
    price_bdt = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price in BDT (৳)")
    original_price_bdt = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Strike-through price if on sale")
    
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    image_url = models.CharField(max_length=500, blank=True, help_text="Optional fallback image URL or static asset path")
    
    is_featured = models.BooleanField(default=False, db_index=True)
    is_in_stock = models.BooleanField(default=True, db_index=True)
    stock_count = models.PositiveIntegerField(default=50, db_index=True)
    min_stock_threshold = models.PositiveIntegerField(default=15, help_text="Alert if stock falls below this number")
    target_stock_level = models.PositiveIntegerField(default=50, help_text="Ideal target inventory quantity")
    
    ingredients = models.TextField(default="Fresh Cucumbers, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic, Bay Leaf (Tejpata), Mustard Seeds, Coriander, Black Peppercorn.")
    shelf_life = models.CharField(max_length=150, default="Always keep refrigerated for maximum crunch. Best enjoyed within 2 months.")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', 'name']
        indexes = [
            models.Index(fields=['stock_count', 'name']),
            models.Index(fields=['-is_featured', 'name']),
            models.Index(fields=['is_in_stock']),
        ]


    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def ordered_demand_count(self):
        """Total quantity demanded across all active unfulfilled orders."""
        if hasattr(self, '_computed_demand'):
            return self._computed_demand
        if not hasattr(self, '_cached_demand'):
            self._cached_demand = self.order_items.filter(
                order__is_deleted=False,
                order__order_status__in=['PENDING', 'CONFIRMED', 'PACKING']
            ).aggregate(models.Sum('quantity'))['quantity__sum'] or 0
        return self._cached_demand

    @property
    def needed_stock(self):
        """Exact quantity deficit needed according to active customer orders."""
        if hasattr(self, '_computed_needed'):
            return self._computed_needed
        return max(0, self.ordered_demand_count - self.stock_count)

    @property
    def is_low_stock(self):
        """True if there is an active order shortage or product is out of stock."""
        if hasattr(self, '_computed_is_low'):
            return self._computed_is_low
        return self.needed_stock > 0 or (self.stock_count == 0 and not self.is_in_stock)

    @property
    def is_critical_stock(self):
        """True if there are active customer orders waiting but physical stock is 0."""
        if hasattr(self, '_computed_is_crit'):
            return self._computed_is_crit
        return self.stock_count == 0 and self.ordered_demand_count > 0

    @property
    def stock_percentage(self):
        if self.ordered_demand_count > 0:
            pct = round((self.stock_count / self.ordered_demand_count) * 100)
            return min(100, max(0, pct))
        return 100 if self.stock_count > 0 else 0


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
        # 1. Check self.image if file actually exists on disk
        if self.image and self.image.name:
            try:
                local_path = os.path.join(settings.MEDIA_ROOT, self.image.name)
                if os.path.exists(local_path):
                    ts = int(os.path.getmtime(local_path))
                    url = self.image.url
                    separator = '&' if '?' in url else '?'
                    return f"{url}{separator}v={ts}"
            except Exception:
                pass

        # 2. Check self.image_url
        if self.image_url and self.image_url.strip():
            url = self.image_url.strip()
            if url.startswith('/media/'):
                rel_path = url.replace('/media/', '').split('?')[0]
                local_path = os.path.join(settings.MEDIA_ROOT, rel_path)
                if os.path.exists(local_path):
                    ts = int(os.path.getmtime(local_path))
                    separator = '&' if '?' in url else '?'
                    return f"{url.split('?')[0]}{separator}v={ts}"
            elif url.startswith('http://') or url.startswith('https://') or url.startswith('/static/'):
                return url

        # 3. Fallback: Check media/products/ matching slug
        if self.slug:
            for ext in ['.webp', '.jpg', '.png', '.jpeg']:
                rel_path = f"products/{self.slug}{ext}"
                local_path = os.path.join(settings.MEDIA_ROOT, rel_path)
                if os.path.exists(local_path):
                    ts = int(os.path.getmtime(local_path))
                    return f"/media/{rel_path}?v={ts}"

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


def calculate_pathao_delivery_fee(weight_grams: int = 600, zone: str = 'INSIDE_DHAKA', total_items: int = 1) -> Decimal:
    """
    Calculates delivery fee.
    Special Offer: Order 4 or more items and get FREE delivery!
    Otherwise: Flat ৳150 nationwide across Bangladesh (Inside & Outside Dhaka).
    """
    if total_items >= 4:
        return Decimal('0.00')
    return Decimal('150.00')


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
    customer_phone = models.CharField(max_length=20, db_index=True)
    customer_email = models.EmailField(blank=True, null=True)
    
    # Address
    delivery_address = models.TextField(help_text="House, Road, Area, Landmark")
    delivery_city = models.CharField(max_length=100, default="Dhaka")
    delivery_zone = models.CharField(max_length=30, choices=ZONE_CHOICES, default='INSIDE_DHAKA', db_index=True)
    
    # Financials in BDT
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=150.00)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Courier Integration (Pathao & Steadfast)
    COURIER_CHOICES = [
        ('PATHAO', 'Pathao Courier'),
        ('STEADFAST', 'Steadfast Courier'),
    ]
    courier_provider = models.CharField(max_length=30, choices=COURIER_CHOICES, default='PATHAO', blank=True, null=True)

    # Pathao Courier Tracking & Consignment
    pathao_consignment_id = models.CharField(max_length=100, blank=True, null=True, help_text="Pathao Consignment ID")
    pathao_tracking_code = models.CharField(max_length=100, blank=True, null=True, help_text="Pathao Public Tracking Code")
    pathao_order_status = models.CharField(max_length=50, blank=True, null=True, help_text="Status synced from Pathao Courier")

    # Steadfast Courier Tracking & Consignment
    steadfast_consignment_id = models.CharField(max_length=100, blank=True, null=True, help_text="Steadfast Consignment ID")
    steadfast_tracking_code = models.CharField(max_length=100, blank=True, null=True, help_text="Steadfast Public Tracking Code")
    steadfast_order_status = models.CharField(max_length=50, blank=True, null=True, help_text="Status synced from Steadfast Courier")
    
    # Payment Info
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, default='BKASH_ONLINE', db_index=True)
    payment_status = models.CharField(max_length=30, choices=PAYMENT_STATUS_CHOICES, default='UNPAID', db_index=True)
    payment_sender_number = models.CharField(max_length=20, blank=True, help_text="Customer bKash/Nagad number")
    payment_trx_id = models.CharField(max_length=100, blank=True, help_text="bKash / Nagad Transaction ID")
    bkash_payment_id = models.CharField(max_length=100, blank=True, null=True, help_text="Official bKash PGW Payment ID")
    
    # Order Status & Management
    order_status = models.CharField(max_length=30, choices=ORDER_STATUS_CHOICES, default='PENDING', db_index=True)
    customer_notes = models.TextField(blank=True, help_text="Customer special request")
    admin_notes = models.TextField(blank=True, help_text="Internal notes / rider info")
    
    # Soft Delete / Safety Fields
    is_deleted = models.BooleanField(default=False, db_index=True, help_text="Soft deleted / moved to trash")
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when moved to trash")
    
    # Status Timestamps for Precise Financial & Analytics Reporting
    confirmed_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Timestamp when order was confirmed")
    delivered_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Timestamp when parcel was delivered to customer")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Managers
    objects = ActiveOrderManager()
    all_objects = AllOrderManager()
    trash_objects = TrashOrderManager()

    class Meta:
        ordering = ['-created_at']
        base_manager_name = 'all_objects'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['order_status', '-created_at']),
            models.Index(fields=['customer_phone']),
            models.Index(fields=['is_deleted', 'order_status']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['delivery_zone']),
            models.Index(fields=['delivered_at']),
            models.Index(fields=['confirmed_at']),
        ]


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
        from django.utils import timezone
        now = timezone.now()

        # Auto-record confirmed_at when order moves to confirmed or later stages
        if self.order_status in ['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED']:
            if not self.confirmed_at:
                self.confirmed_at = now
        elif self.order_status in ['PENDING', 'CANCELLED'] and not self.id:
            self.confirmed_at = None

        # Auto-record delivered_at when order status reaches DELIVERED
        if self.order_status == 'DELIVERED':
            if not self.delivered_at:
                self.delivered_at = now
            if self.payment_status == 'UNPAID':
                self.payment_status = 'PAID'
        elif self.order_status in ['PENDING', 'CANCELLED'] and self.delivered_at:
            self.delivered_at = None

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

        # Synchronize customer instruction and delivery instruction
        clean_cust_notes = (self.customer_notes or '').strip()
        clean_admin_notes = (self.admin_notes or '').strip()
        if clean_cust_notes and not clean_admin_notes:
            self.admin_notes = clean_cust_notes
        elif clean_admin_notes and not clean_cust_notes:
            self.customer_notes = clean_admin_notes
        elif clean_cust_notes:
            self.customer_notes = clean_cust_notes
            self.admin_notes = clean_cust_notes

        super().save(*args, **kwargs)

    @property
    def delivery_instruction(self):
        """
        Unified Customer and Delivery Instruction.
        """
        return (self.customer_notes or self.admin_notes or '').strip()


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
            'PENDING': 'bg-amber-50 text-amber-900 border-amber-300 ring-1 ring-amber-400/20',
            'CONFIRMED': 'bg-blue-50 text-blue-900 border-blue-300 ring-1 ring-blue-400/20',
            'PACKING': 'bg-purple-50 text-purple-900 border-purple-300 ring-1 ring-purple-400/20',
            'OUT_FOR_DELIVERY': 'bg-indigo-50 text-indigo-900 border-indigo-300 ring-1 ring-indigo-400/20',
            'DELIVERED': 'bg-emerald-50 text-emerald-900 border-emerald-300 ring-1 ring-emerald-400/20',
            'CANCELLED': 'bg-rose-50 text-rose-900 border-rose-300 ring-1 ring-rose-400/20',
        }
        return colors.get(self.order_status, 'bg-gray-100 text-gray-800 border-gray-300')

    @property
    def status_icon(self):
        """
        Returns FontAwesome icon class with matching color for the order status.
        """
        icons = {
            'PENDING': 'fa-solid fa-clock text-amber-600',
            'CONFIRMED': 'fa-solid fa-circle-check text-blue-600',
            'PACKING': 'fa-solid fa-box-open text-purple-600',
            'OUT_FOR_DELIVERY': 'fa-solid fa-truck-fast text-indigo-600',
            'DELIVERED': 'fa-solid fa-circle-check text-emerald-600',
            'CANCELLED': 'fa-solid fa-circle-xmark text-rose-600',
        }
        return icons.get(self.order_status, 'fa-solid fa-circle-question text-gray-500')

    @property
    def status_icon_pure(self):
        """
        Returns bare FontAwesome icon class without color classes.
        """
        icons = {
            'PENDING': 'fa-solid fa-clock',
            'CONFIRMED': 'fa-solid fa-circle-check',
            'PACKING': 'fa-solid fa-box-open',
            'OUT_FOR_DELIVERY': 'fa-solid fa-truck-fast',
            'DELIVERED': 'fa-solid fa-circle-check',
            'CANCELLED': 'fa-solid fa-circle-xmark',
        }
        return icons.get(self.order_status, 'fa-solid fa-circle-question')

    @property
    def status_dot_class(self):
        dots = {
            'PENDING': 'bg-amber-500',
            'CONFIRMED': 'bg-blue-500',
            'PACKING': 'bg-purple-500',
            'OUT_FOR_DELIVERY': 'bg-indigo-500',
            'DELIVERED': 'bg-emerald-500',
            'CANCELLED': 'bg-rose-500',
        }
        return dots.get(self.order_status, 'bg-gray-400')

    @property
    def status_emoji(self):
        emojis = {
            'PENDING': '🟡',
            'CONFIRMED': '🔵',
            'PACKING': '📦',
            'OUT_FOR_DELIVERY': '🚚',
            'DELIVERED': '🟢',
            'CANCELLED': '🔴',
        }
        return emojis.get(self.order_status, '⚪')

    @property
    def status_select_class(self):
        """
        Distinct vibrant background, text, and border styling for the dropdown selector itself based on status.
        """
        classes = {
            'PENDING': 'bg-amber-100 text-amber-950 border-amber-400 hover:bg-amber-200/90 focus:ring-amber-400',
            'CONFIRMED': 'bg-blue-100 text-blue-950 border-blue-400 hover:bg-blue-200/90 focus:ring-blue-400',
            'PACKING': 'bg-purple-100 text-purple-950 border-purple-400 hover:bg-purple-200/90 focus:ring-purple-400',
            'OUT_FOR_DELIVERY': 'bg-indigo-100 text-indigo-950 border-indigo-400 hover:bg-indigo-200/90 focus:ring-indigo-400',
            'DELIVERED': 'bg-emerald-100 text-emerald-950 border-emerald-400 hover:bg-emerald-200/90 focus:ring-emerald-400',
            'CANCELLED': 'bg-rose-100 text-rose-950 border-rose-400 hover:bg-rose-200/90 focus:ring-rose-400',
        }
        return classes.get(self.order_status, 'bg-gray-100 text-gray-900 border-gray-300')



    @property
    def customer_score(self):
        """
        Calculates customer delivery trust & fraud risk score based on recipient phone order history.
        """
        from django.db.models import Sum
        clean_digits = ''.join(c for c in (self.customer_phone or '') if c.isdigit())
        last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits

        # 0. Check if customer is manually blacklisted / blocked in the system
        if last_10:
            try:
                from dashboard.models import BlacklistedCustomer
                if BlacklistedCustomer.is_phone_blocked(last_10):
                    return {
                        'score': 0,
                        'rate': '0%',
                        'stars': '0.0',
                        'total_orders': 1,
                        'delivered_count': 0,
                        'cancelled_count': 1,
                        'returned_count': 1,
                        'in_transit_count': 0,
                        'total_spent': 0,
                        'courier_fault_count': 0,
                        'badge_class': 'bg-rose-600 text-white border-rose-700 shadow-xs font-black',
                        'icon': 'fa-solid fa-ban text-white',
                        'label': '🚫 Blacklisted Spammer',
                        'short_label': '🚫 Blocked',
                        'risk_level': 'BLACKLISTED',
                        'risk_title': '🚫 Blacklisted Spammer (অর্ডার নিষিদ্ধ)',
                        'text': 'This phone number is actively blacklisted / blocked in store settings'
                    }
            except Exception:
                pass

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
                'courier_fault_count': 0,
                'badge_class': 'bg-emerald-100 text-emerald-800 border-emerald-300',
                'icon': 'fa-solid fa-circle-check text-emerald-600',
                'label': '🟢 Good Client',
                'short_label': '🟢 Verified',
                'risk_level': 'SAFE',
                'risk_title': 'Good / Verified',
                'text': 'Verified Recipient Phone'
            }
        
        all_orders = Order.all_objects.filter(customer_phone__icontains=last_10)
        
        # Check returns and identify courier/merchant faults vs customer rejections
        non_customer_fault_reasons = {'COURIER_DELAY', 'DAMAGED_IN_TRANSIT', 'COURIER_FAULT', 'WRONG_ITEM'}
        courier_fault_order_ids = set()
        customer_returns_count = 0
        try:
            from dashboard.models import OrderReturn
            returns_qs = OrderReturn.objects.filter(order__in=all_orders)
            courier_fault_order_ids = set(
                returns_qs.filter(return_reason__in=non_customer_fault_reasons).values_list('order_id', flat=True)
            )
            customer_returns_count = returns_qs.exclude(return_reason__in=non_customer_fault_reasons).count()
        except Exception:
            pass

        # Also identify orders where notes explicitly state courier issues
        courier_keywords = ['courier delay', 'damaged in transit', 'courier fault', 'courier rto', 'lost by courier', 'courier return']
        for o in all_orders.filter(order_status='CANCELLED'):
            note = (o.admin_notes or '').lower()
            if any(kw in note for kw in courier_keywords):
                courier_fault_order_ids.add(o.id)

        courier_fault_count = len(courier_fault_order_ids)

        # Countable orders for customer: EXCLUDE courier-fault cancelled/returned orders completely!
        # Only customer's valid orders and customer-initiated cancellations/returns are counted.
        countable_orders = all_orders.exclude(id__in=courier_fault_order_ids)
        total = countable_orders.count()
        if total == 0:
            total = 1  # Base minimum for the active customer interaction

        delivered = countable_orders.filter(order_status='DELIVERED').count()
        in_transit = countable_orders.filter(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY']).count()
        customer_cancelled = countable_orders.filter(order_status='CANCELLED').count()
        total_cancelled_all = all_orders.filter(order_status='CANCELLED').count()
        
        # Effective rejections attributable to customer
        effective_customer_rejections = max(customer_returns_count, customer_cancelled)
        
        delivered_orders_sum = countable_orders.filter(order_status='DELIVERED').aggregate(total_spent=Sum('total_amount'))['total_spent'] or 0

        common_stats = {
            'total_orders': total,
            'delivered_count': delivered,
            'cancelled_count': customer_cancelled,
            'total_cancelled_all': total_cancelled_all,
            'returned_count': effective_customer_rejections,
            'courier_fault_count': courier_fault_count,
            'in_transit_count': in_transit,
            'total_spent': delivered_orders_sum,
        }
        
        if total <= 1:
            courier_note = f" • Prior {courier_fault_count} courier issue(s) excluded" if courier_fault_count > 0 else ""
            if effective_customer_rejections == 0:
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
                    'text': f'1st Order on Pickpickles • Verify Address{courier_note}'
                }
            else:
                return {
                    **common_stats,
                    'score': 0,
                    'rate': '0%',
                    'stars': '1.0',
                    'badge_class': 'bg-rose-50 text-rose-800 border-rose-200',
                    'icon': 'fa-solid fa-triangle-exclamation text-rose-600',
                    'label': 'Refused Order',
                    'short_label': '🔴 Refused',
                    'risk_level': 'RISKY',
                    'risk_title': 'Customer Refused Delivery',
                    'text': 'Customer deliberately refused delivery'
                }
        
        # Calculate success rate based on countable orders
        success_rate = round((delivered / total) * 100) if total > 0 else 100
        if success_rate > 100:
            success_rate = 100

        if effective_customer_rejections == 0:
            courier_note = f" (Excluded {courier_fault_count} Courier RTO)" if courier_fault_count > 0 else ""
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
                'risk_title': f'100% Safe Customer ({total} Orders • 0 Customer Refusals){courier_note}',
                'text': f'{total} Orders • 0 Customer Rejections{courier_note}'
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
                'risk_title': f'Moderate Risk ({effective_customer_rejections} Customer Cancellations)',
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
                'risk_title': f'High Return Risk ({effective_customer_rejections} Customer Refusals)',
                'text': f'{effective_customer_rejections} Customer Rejections / {total} Orders'
            }

    @property
    def active_courier(self):
        """Returns the courier used for this order: 'STEADFAST', 'PATHAO', or None."""
        if self.steadfast_consignment_id or self.courier_provider == 'STEADFAST':
            return 'STEADFAST'
        if self.pathao_consignment_id or self.courier_provider == 'PATHAO':
            return 'PATHAO'
        return None

    @property
    def active_courier_name(self):
        if self.active_courier == 'STEADFAST':
            return 'Steadfast Courier'
        if self.active_courier == 'PATHAO':
            return 'Pathao Courier'
        return 'Not Dispatched'

    @property
    def active_consignment_id(self):
        if self.active_courier == 'STEADFAST':
            return self.steadfast_consignment_id
        return self.pathao_consignment_id

    @property
    def active_tracking_code(self):
        if self.active_courier == 'STEADFAST':
            return self.steadfast_tracking_code or self.steadfast_consignment_id
        return self.pathao_tracking_code or self.pathao_consignment_id

    @property
    def active_courier_status(self):
        if self.active_courier == 'STEADFAST':
            return self.steadfast_order_status
        return self.pathao_order_status

    @property
    def active_tracking_url(self):
        if self.active_courier == 'STEADFAST':
            code = self.steadfast_tracking_code or self.steadfast_consignment_id
            return f"https://steadfast.com.bd/tracking/{code}" if code else "https://steadfast.com.bd/tracking"
        elif self.active_courier == 'PATHAO':
            cid = self.pathao_consignment_id
            return f"https://merchant.pathao.com/tracking?consignment_id={cid}" if cid else "https://merchant.pathao.com/tracking"
        return None

    @property
    def whatsapp_phone_international(self):
        """
        Formats customer phone into standard WhatsApp format (8801XXXXXXXXX).
        """
        digits = ''.join(c for c in (self.customer_phone or '') if c.isdigit())
        if not digits:
            return ''
        if digits.startswith('880'):
            return digits
        if digits.startswith('0'):
            return f"88{digits}"
        if len(digits) == 10 and digits.startswith('1'):
            return f"880{digits}"
        if len(digits) >= 10:
            return f"880{digits[-10:]}"
        return f"880{digits}"

    def get_whatsapp_shipping_instruction_message(self):
        """
        Generates a concise, polite & professional WhatsApp message with order dispatch details,
        key storage tips, and general review options.
        """
        items_list = []
        for itm in self.items.all():
            items_list.append(f"🥒 {itm.product_name} x {itm.quantity}")
        items_text = "\n".join(items_list) if items_list else "🥒 Pickpickles Homemade Jars"

        payment_line = "✅ *পেমেন্ট:* পরিশোধিত (Paid)" if self.payment_status == 'PAID' else f"💵 *ক্যাশ অন ডেলিভারি (COD):* ৳{self.total_amount}"

        msg = f"""🥒 *Pickpickles — অর্ডার প্রেরণের আপডেট* 🚚✨

প্রিয় *{self.customer_name}*,

আপনার Pickpickles অর্ডার *#{self.order_number}* যত্নসহকারে প্রস্তুত করে কুরিয়ারের মাধ্যমে আপনার ঠিকানায় পাঠিয়ে দেওয়া হয়েছে।

📋 *অর্ডারের সারসংক্ষেপ:*
{items_text}
{payment_line}

🧊 *সংরক্ষণের বিশেষ অনুরোধ:*
• পার্সেলটি হাতে পাওয়া মাত্রই নরমাল ফ্রিজে রেখে দিন (সর্বোচ্চ ফ্রেশনেস ও ক্রাঞ্চিনেসের জন্য)।
• জার থেকে নেওয়ার সময় সবসময় পরিষ্কার ও শুকনো চামচ ব্যবহার করুন।

⭐ *আপনার মূল্যবান মতামত (Review & Feedback):*
পিকল টেস্ট করার পর আপনার অভিজ্ঞতা ও রিভিউ আমাদের সাথে শেয়ার করতে পারেন:
• 💬 এই মেসেজে সরাসরি রিপ্লাই দিয়ে রেটিং বা মতামত জানাতে পারেন
• 🌐 ওয়েবসাইটে: https://pickpickles.xyz
• 📘 ফেসবুক পেজে: https://facebook.com/pickpickles07

আপনার সন্তুষ্টিই আমাদের প্রধান লক্ষ্য। 💚

আন্তরিক ধন্যবাদ,
*টিম Pickpickles*
🌐 pickpickles.xyz | 📞 01794271523"""
        return msg.strip()

    @property
    def whatsapp_shipping_instruction_url(self):
        """
        Generates direct WhatsApp API web link to send storage guidelines and feedback request to customer.
        """
        import urllib.parse
        phone = self.whatsapp_phone_international
        if not phone:
            return ''
        text = self.get_whatsapp_shipping_instruction_message()
        encoded_text = urllib.parse.quote(text)
        return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_text}"

    def get_whatsapp_feedback_message(self):
        """
        Generates an elegant, respectful feedback request message with general review options.
        """
        msg = f"""🥒 *Pickpickles — আপনার অনুভূতি ও মতামত* ⭐✨

প্রিয় *{self.customer_name}*,

আশা করি ভালো আছেন। Pickpickles থেকে নেওয়া আমাদের হোমমেড পিকল আশা করি সঠিকভাবে হাতে পেয়েছেন এবং উপভোগ করছেন।

আমাদের পিকলের স্বাদ ও সার্ভিস সম্পর্কে আপনার কেমন অভিজ্ঞতা হলো? যেকোনো একটি মাধ্যমে আপনার মূল্যবান রিভিউ জানাতে পারেন:

• 💬 এই মেসেজে সরাসরি রিপ্লাই দিয়ে
• 🌐 আমাদের ওয়েবসাইটে: https://pickpickles.xyz
• 📘 আমাদের ফেসবুক পেজে: https://facebook.com/pickpickles07

একটি ক্ষুদ্র উদ্যোগ হিসেবে আপনাদের প্রতিটি রিভিউ আমাদের অনুপ্রাণিত করে। 💚

আন্তরিক ধন্যবাদ,
*টিম Pickpickles*
🌐 pickpickles.xyz"""
        return msg.strip()

    @property
    def whatsapp_feedback_url(self):
        """
        Direct WhatsApp link to request customer review & feedback.
        """
        import urllib.parse
        phone = self.whatsapp_phone_international
        if not phone:
            return ''
        text = self.get_whatsapp_feedback_message()
        encoded_text = urllib.parse.quote(text)
        return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_text}"

    def get_whatsapp_1month_review_request_message(self):
        """
        Generates a polite, highly professional 1-month follow-up message requesting general review.
        """
        msg = f"""🥒 *Pickpickles — আপনার মূল্যবান মতামত* ⭐✨

প্রিয় *{self.customer_name}*,

আশা করি ভালো আছেন। কিছুদিন আগে আপনি Pickpickles থেকে আমাদের হোমমেড পিকল গ্রহণ করেছিলেন। আশা করি পিকলের স্বাদ ও ক্রাঞ্চিনেস আপনি উপভোগ করেছেন! 💚

আমাদের পিকলের মান ও সার্ভিস সম্পর্কে আপনার সাধারণ অভিজ্ঞতা ও মূল্যবান রিভিউ আমাদের সেবাকে আরও নিখুঁত করতে সাহায্য করবে।

মাত্র ১ মিনিট সময় দিয়ে যেকোনো মাধ্যমে আপনার রিভিউ জানাতে পারেন:

🌟 *রিভিউ দেওয়ার সহজ মাধ্যম:*
• 💬 *সরাসরি মেসেজে:* এই মেসেজে রিপ্লাই দিয়ে আপনার অনুভূতি বা রেটিং (১ থেকে ৫ ⭐) লিখে জানাতে পারেন।
• 🌐 *আমাদের ওয়েবসাইটে:* https://pickpickles.xyz
• 📘 *আমাদের ফেসবুক পেজে:* https://facebook.com/pickpickles07

Pickpickles-এর সাথে থাকার জন্য আন্তরিক ধন্যবাদ।

শুভকামনায়,
*টিম Pickpickles*
🌐 pickpickles.xyz | 📞 01794271523"""
        return msg.strip()

    @property
    def whatsapp_1month_review_request_url(self):
        """
        Direct WhatsApp link to send 1-month review request message.
        """
        import urllib.parse
        phone = self.whatsapp_phone_international
        if not phone:
            return ''
        text = self.get_whatsapp_1month_review_request_message()
        encoded_text = urllib.parse.quote(text)
        return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_text}"

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

    def sync_steadfast_status(self):
        """
        Syncs live consignment tracking status from Steadfast Courier API and updates order_status.
        """
        if not self.steadfast_consignment_id and not self.steadfast_tracking_code and not self.order_number:
            return None
        try:
            from store.steadfast import SteadfastCourierService
            service = SteadfastCourierService()
            if not service.is_configured():
                return None
            return service.sync_order_status(self)
        except Exception:
            pass
        return self.steadfast_order_status

    def sync_courier_status(self):
        """
        Automatically syncs status from whichever courier service the order was dispatched with.
        """
        if self.active_courier == 'STEADFAST':
            return self.sync_steadfast_status()
        elif self.active_courier == 'PATHAO':
            return self.sync_pathao_status()
        return None

    def __str__(self):
        return f"Order #{self.order_number} - {self.customer_name} (৳{self.total_amount})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name='order_items')
    product_name = models.CharField(max_length=200)
    jar_weight_grams = models.PositiveIntegerField(default=600)
    gross_weight_grams = models.PositiveIntegerField(default=850)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    def save(self, *args, **kwargs):
        self.total_price = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}x {self.product_name} in #{self.order.order_number}"


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    reviewer_name = models.CharField(max_length=100)
    reviewer_location = models.CharField(max_length=100, default="Dhaka, BD")
    rating = models.PositiveSmallIntegerField(default=5)
    comment = models.TextField()
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        prod = f" on {self.product.name}" if self.product else ""
        return f"{self.reviewer_name}{prod} ({self.rating}★)"
