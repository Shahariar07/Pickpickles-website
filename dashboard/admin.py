# pyrefly: ignore[missing-import]
from django.contrib import admin
from .models import PriceHistory, StockLog, ProductionBatch, DamageLog, Expense, ExpenseCategory, OrderReturn, DashboardSecurityConfig


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'old_price', 'new_price', 'price_delta', 'percentage_change', 'change_type', 'reason', 'changed_by', 'created_at')
    list_filter = ('change_type', 'created_at', 'product')
    search_fields = ('product__name', 'reason', 'notes')
    readonly_fields = ('created_at', 'price_delta', 'percentage_change')