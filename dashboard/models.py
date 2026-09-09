from django.db import models
from django.utils import timezone


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
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

    def __str__(self):
        return self.name


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('RAW_MATERIAL', 'Fresh Cucumbers & Veggies 🥒'),
        ('PACKAGING', 'Glass Jars, Lids & Labels 🫙'),
        ('SPICES_BRINE', 'Vinegar, Garlic & Whole Spices 🌿'),
        ('LOGISTICS', 'Courier & Rider Delivery Cost 🚚'),
        ('MARKETING', 'Digital Ads & Marketing 📢'),
        ('UTILITIES', 'Gas, Electricity & Kitchen Rent ⚡'),
        ('OTHER', 'Operational & Miscellaneous 📋'),
    ]

    PAYMENT_CHOICES = [
        ('CASH', 'Cash'),
        ('BKASH', 'bKash'),
        ('NAGAD', 'Nagad'),
        ('BANK', 'Bank Transfer'),
    ]

    title = models.CharField(max_length=200, help_text="e.g. 200pcs 500g Glass Jars with Gold Lids")
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, default='RAW_MATERIAL')
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
        ('CUSTOMER_UNREACHABLE', 'Customer Phone Off / Unreachable 📵'),
        ('CUSTOMER_REFUSED', 'Customer Refused at Doorstep 🚪'),
        ('WRONG_ADDRESS', 'Incorrect Address / Area Not Covered 📍'),
        ('COURIER_DELAY', 'Courier Delayed / Customer Cancelled ⏳'),
        ('DAMAGED_IN_TRANSIT', 'Jar Broken / Leaked during Delivery 💥'),
        ('WRONG_ITEM', 'Wrong Variety / Flavor Sent 🫙'),
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
    is_restocked = models.BooleanField(default=False, help_text="Whether jars have been added back to Product stock")
    return_date = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True, help_text="Courier consignment ID, rider remarks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Return for #{self.order.order_number} ({self.get_return_status_display()})"
