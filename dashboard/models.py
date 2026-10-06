from django.conf import settings
from django.db import models
from django.utils import timezone


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subcategories')
    icon = models.CharField(max_length=50, default='fa-receipt')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Expense Categories'
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
            if not self.slug:
                import time
                self.slug = f"cat-{int(time.time())}"
        super().save(*args, **kwargs)

    @property
    def is_parent(self):
        return self.parent is None

    @property
    def full_name(self):
        if self.parent:
            return f"{self.parent.name} ➔ {self.name}"
        return self.name

    def __str__(self):
        return self.full_name


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('RAW_MATERIAL', 'Fresh Cucumbers & Veggies 🥒'),
        ('PACKAGING', 'Glass Jars, Lids & Labels 🫙'),
        ('SPICES_BRINE', 'Vinegar, Garlic & Whole Spices 🌿'),
        ('LOGISTICS', 'Courier & Rider Delivery Cost 🚚'),
        ('MARKETING', 'Digital Ads & Marketing 📢'),
        ('UTILITIES', 'Gas, Electricity & Kitchen Rent ⚡'),
        ('DAMAGE_LOSS', 'Damaged & Broken Products Loss 💥'),
        ('OTHER', 'Operational & Miscellaneous 📋'),
    ]

    UNIT_CHOICES = [
        ('kg', 'kg (কেজি)'),
        ('gm', 'gm (গ্রাম)'),
        ('pcs', 'pcs (পিস/সংখ্যা)'),
        ('liter', 'liter (লিটার)'),
        ('ml', 'ml (মিলি)'),
        ('pack', 'pack (প্যাকেট)'),
        ('box', 'box (বক্স/কার্টন)'),
        ('other', 'other (অন্যান্য)'),
    ]

    PAYMENT_CHOICES = [
        ('CASH', 'Cash'),
        ('BKASH', 'bKash'),
        ('NAGAD', 'Nagad'),
        ('BANK', 'Bank Transfer'),
    ]

    title = models.CharField(max_length=200, help_text="e.g. 200pcs 600g Glass Jars with Gold Lids")
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, default='RAW_MATERIAL')
    sub_category = models.CharField(max_length=100, blank=True, help_text="Sub-category (e.g. Cucumber, Carrot, Jar, Vinegar)")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Quantity or weight purchased")
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='pcs', blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Cost amount in BDT (৳)")
    expense_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='CASH')
    receipt_reference = models.CharField(max_length=100, blank=True, help_text="Invoice/Voucher # or bKash TrxID")
    notes = models.TextField(blank=True, help_text="Additional details, supplier name, etc.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-expense_date', '-created_at']

    @property
    def quantity_display(self):
        if not self.quantity:
            return ""
        q_str = f"{self.quantity:f}".rstrip('0').rstrip('.')
        return f"{q_str} {self.unit or ''}".strip()

    @property
    def unit_price_display(self):
        if self.quantity and self.quantity > 0:
            unit_cost = round(float(self.amount) / float(self.quantity), 2)
            unit_cost_str = f"{unit_cost:f}".rstrip('0').rstrip('.')
            return f"৳{unit_cost_str}/{self.unit or 'unit'}"
        return None

    @property
    def category_display_name(self):
        choices_dict = dict(self.CATEGORY_CHOICES)
        if self.category in choices_dict:
            return choices_dict[self.category]
        cat = ExpenseCategory.objects.filter(models.Q(slug=self.category) | models.Q(name=self.category)).first()
        if cat:
            return cat.name
        return self.category

    def __str__(self):
        return f"{self.title} - ৳{self.amount} ({self.category_display_name})"


class DamageLog(models.Model):
    DAMAGE_REASON_CHOICES = [
        ('TRANSIT_BREAKAGE', 'Courier / Rider Transit Breakage 🚚'),
        ('KITCHEN_SPILL', 'Kitchen Prep / Production Spill 🥒'),
        ('SEAL_DEFECT', 'Cap / Vacuum Seal Defect & Leaking 🫙'),
        ('EXPIRED_SPOILED', 'Spoiled / Freshness Quality Issue 🌿'),
        ('RETURN_DAMAGED', 'Damaged in Customer Return 📦'),
        ('OTHER', 'Other Operational Loss 📋'),
    ]

    product = models.ForeignKey('store.Product', on_delete=models.CASCADE, related_name='damage_logs')
    quantity = models.PositiveIntegerField(default=1, help_text="Number of jars damaged")
    estimated_cost_per_jar = models.DecimalField(max_digits=10, decimal_places=2, default=200.00, help_text="Cost per jar in BDT")
    total_loss_bdt = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    reason = models.CharField(max_length=50, choices=DAMAGE_REASON_CHOICES, default='TRANSIT_BREAKAGE')
    incident_date = models.DateField(default=timezone.now)
    order_ref = models.CharField(max_length=100, blank=True, help_text="Order # if courier related")
    expense = models.ForeignKey('Expense', on_delete=models.SET_NULL, null=True, blank=True, related_name='damage_logs')
    notes = models.TextField(blank=True, help_text="Details of incident, courier consignment, etc.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-incident_date', '-created_at']

    def save(self, *args, **kwargs):
        self.total_loss_bdt = self.quantity * self.estimated_cost_per_jar
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity}x {self.product.name} ({self.get_reason_display()}) - Loss ৳{self.total_loss_bdt}"


class OrderReturn(models.Model):
    RETURN_REASON_CHOICES = [
        ('CUSTOMER_UNREACHABLE', 'Customer Phone Off / Unreachable 📵 (Customer Issue)'),
        ('CUSTOMER_REFUSED', 'Customer Refused at Doorstep 🚪 (Customer Issue)'),
        ('WRONG_ADDRESS', 'Incorrect Address / Area Not Covered 📍'),
        ('COURIER_DELAY', 'Courier Delay / RTO ⏳ (Courier Fault)'),
        ('DAMAGED_IN_TRANSIT', 'Broken / Leaked in Transit 💥 (Courier Fault)'),
        ('COURIER_FAULT', 'Courier Fault / Lost / Hub Misroute 🚚 (Courier Fault)'),
        ('WRONG_ITEM', 'Wrong Variety Sent 🫙 (Merchant Fault)'),
    ]

    RETURN_STATUS_CHOICES = [
        ('RETURNING', 'Returning with Courier (ফেরত আসছে)'),
        ('RECEIVED_INTACT', 'Received Intact & Restocked (ভালো আছে ও স্টকে যোগ করা হয়েছে)'),
        ('RECEIVED_DAMAGED', 'Received Damaged / Broken (ভাঙা/নষ্ট অবস্থায় ফেরত)'),
    ]

    order = models.ForeignKey('store.Order', on_delete=models.CASCADE, related_name='returns')
    return_reason = models.CharField(max_length=50, choices=RETURN_REASON_CHOICES, default='CUSTOMER_REFUSED')
    return_status = models.CharField(max_length=30, choices=RETURN_STATUS_CHOICES, default='RETURNING')
    courier_return_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, help_text="Return fee charged by courier (৳)")
    expense = models.ForeignKey('Expense', on_delete=models.SET_NULL, null=True, blank=True, related_name='order_returns')
    is_restocked = models.BooleanField(default=False, help_text="Whether jars have been added back to Product stock")
    return_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True, help_text="Courier consignment ID, rider remarks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Return for #{self.order.order_number} ({self.get_return_status_display()})"


class StockLog(models.Model):
    LOG_TYPE_CHOICES = [
        ('RESTOCK', 'Production / Restocked 🥒 (+)'),
        ('ORDER_CONFIRMED', 'Order Confirmed / Sold 📦 (-)'),
        ('ORDER_CANCELLED', 'Order Cancelled / Restored 🔄 (+)'),
        ('DAMAGE_LOSS', 'Breakage / Spoilage Loss 💥 (-)'),
        ('RETURN_RESTOCKED', 'Customer Return Restocked 🔙 (+)'),
        ('MANUAL_ADJUSTMENT', 'Manual Adjustment ✏️'),
    ]

    product = models.ForeignKey('store.Product', on_delete=models.CASCADE, related_name='stock_logs')
    log_type = models.CharField(max_length=30, choices=LOG_TYPE_CHOICES, default='MANUAL_ADJUSTMENT')
    quantity_delta = models.IntegerField(help_text="Stock difference e.g. +50 or -3")
    previous_stock = models.IntegerField(default=0)
    resulting_stock = models.IntegerField(default=0)
    order = models.ForeignKey('store.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_logs')
    reference = models.CharField(max_length=150, blank=True, help_text="e.g. Batch #4, Order #ORD-2026-001, Damage Log #5")
    notes = models.TextField(blank=True, help_text="Extra details or remarks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_logs')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_addition(self):
        return self.quantity_delta > 0

    @property
    def is_deduction(self):
        return self.quantity_delta < 0

    def __str__(self):
        sign = '+' if self.quantity_delta > 0 else ''
        return f"{self.product.name}: {sign}{self.quantity_delta} ({self.get_log_type_display()}) -> Stock: {self.resulting_stock}"


class ProductionBatch(models.Model):
    batch_number = models.CharField(max_length=150, help_text="e.g. Batch #1, Batch #2, Winter Special 2026")
    production_date = models.DateField(default=timezone.now, help_text="Date when this batch was prepared/bottled")
    notes = models.TextField(blank=True, help_text="Batch preparation notes, ingredients, brine formulation, or chef remarks")
    total_cost_bdt = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Total production cost for this batch in BDT")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='production_batches')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-production_date', '-id']

    @property
    def total_jars(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_flavors(self):
        return self.items.count()

    @property
    def total_retail_value(self):
        return sum(item.quantity * float(item.product.price_bdt or 0) for item in self.items.select_related('product'))

    def __str__(self):
        return f"{self.batch_number} ({self.production_date.strftime('%d %b %Y')})"


class BatchItem(models.Model):
    batch = models.ForeignKey(ProductionBatch, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('store.Product', on_delete=models.CASCADE, related_name='batch_items')
    quantity = models.PositiveIntegerField(help_text="Number of jars produced for this flavor")
    unit_cost_bdt = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, help_text="Estimated cost per jar")
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['product__name']

    @property
    def total_retail_value(self):
        return self.quantity * float(self.product.price_bdt or 0)

    def __str__(self):
        return f"{self.batch.batch_number} - {self.product.name} (+{self.quantity} jars)"


class BlacklistedCustomer(models.Model):
    phone = models.CharField(max_length=20, unique=True, db_index=True, help_text="Clean recipient phone number (e.g. 017XXXXXXXX)")
    customer_name = models.CharField(max_length=150, blank=True, help_text="Optional customer name for reference")
    ip_address = models.GenericIPAddressField(null=True, blank=True, help_text="Optional IP address")
    reason = models.CharField(max_length=255, default="Fake orders / prank harassment / repeated refusal", help_text="Reason for blocking")
    is_active = models.BooleanField(default=True, db_index=True, help_text="Active block status")
    blocked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Blacklisted Customer'
        verbose_name_plural = 'Blacklisted Customers'

    @classmethod
    def is_phone_blocked(cls, phone_number):
        if not phone_number:
            return False
        clean = ''.join(c for c in str(phone_number) if c.isdigit())
        last_10 = clean[-10:] if len(clean) >= 10 else clean
        if not last_10:
            return False
        return cls.objects.filter(is_active=True, phone__icontains=last_10).exists()

    def __str__(self):
        return f"{self.phone} ({self.customer_name or 'Unknown'}) - {self.reason}"


