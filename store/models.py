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
    jar_weight_grams = models.PositiveIntegerField(default=500, help_text="Weight in grams (e.g. 500g)")
    
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


class Order(models.Model):
    ZONE_CHOICES = [
        ('INSIDE_DHAKA', 'Inside Dhaka (৳150 Delivery)'),
        ('OUTSIDE_DHAKA', 'Outside Dhaka / Nationwide (৳150 Courier)'),
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
        ('CONFIRMED', 'Confirmed & In Queue'),
        ('PACKING', 'Packing Fresh Jars'),
        ('OUT_FOR_DELIVERY', 'Out for Delivery / Shipped'),
        ('DELIVERED', 'Delivered 🎉'),
        ('CANCELLED', 'Cancelled'),
    ]

    order_number = models.CharField(max_length=32, unique=True, editable=False)
    
    # Customer Details
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=20)
    customer_email = models.EmailField(blank=True, null=True)
    
    # Address
    delivery_address = models.TextField(help_text="House, Road, Area, Landmark")
    delivery_city = models.CharField(max_length=100, default="Dhaka")
    delivery_zone = models.CharField(max_length=20, choices=ZONE_CHOICES, default='INSIDE_DHAKA')
    
    # Financials in BDT
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=150.00)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
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
            # Sequential periodical order numbering starting from PKP-0001 (e.g. PKP-0001, PKP-0002, ...)
            existing_pks = Order.all_objects.filter(order_number__startswith='PKP-').values_list('order_number', flat=True)
            max_num = 0
            for onum in existing_pks:
                match = re.search(r'^PKP-(\d+)$', str(onum).strip())
                if match:
                    try:
                        max_num = max(max_num, int(match.group(1)))
                    except ValueError:
                        pass
            
            candidate = max_num + 1
            cand_str = f"PKP-{candidate:04d}"
            while Order.all_objects.filter(order_number=cand_str).exists():
                candidate += 1
                cand_str = f"PKP-{candidate:04d}"
            self.order_number = cand_str
        super().save(*args, **kwargs)

    @property
    def total_items_count(self):
        return sum(item.quantity for item in self.items.all())

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

    def __str__(self):
        return f"Order #{self.order_number} - {self.customer_name} (৳{self.total_amount})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, related_name='order_items')
    product_name = models.CharField(max_length=200)
    jar_weight_grams = models.PositiveIntegerField(default=500)
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
