import csv
import json
import datetime
from datetime import timedelta
import math
import time
from collections import defaultdict
import calendar
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from decimal import Decimal
from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth.models import User
from store.models import Order, OrderItem, Product, Category, Review, calculate_pathao_delivery_fee, PromotionSetting, Coupon
from store.pathao import PathaoCourierService
from store.steadfast import SteadfastCourierService
from .models import Expense, ExpenseCategory, DamageLog, OrderReturn, StockLog, ProductionBatch, BatchItem, BlacklistedCustomer, StaffSecurityProfile, DashboardSecurityConfig, PriceHistory


def is_staff_user(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def is_view_only_user(user):
    """
    Checks if a user is in View-Only (Restricted) mode like Mitu.
    View-only users can browse and view all dashboard pages,
    but cannot edit, create, delete, dispatch, or modify anything.
    """
    if not user or not user.is_authenticated:
        return True
    if user.is_superuser:
        return False
    
    # Username 'mitu' or any user configured with edit restrictions
    if getattr(user, 'username', '').strip().lower() == 'mitu':
        return True

    profile = getattr(user, 'security_profile', None)
    if profile is not None:
        if not profile.can_edit_records:
            return True
        return False

    try:
        config = DashboardSecurityConfig.get_config()
        if config.strict_admin_only_edit:
            return True
    except Exception:
        pass

    return False


def can_user_delete(user):
    """
    Checks if a user has permission to delete any record across the platform.
    Rule:
    1. Superusers (Administrators) can ALWAYS delete records.
    2. If user is unauthenticated or view-only (like Mitu): False.
    3. If strict_admin_only_delete is enabled: ONLY superusers can delete.
    4. If strict_admin_only_delete is disabled AND allow_staff_delete_override is True:
       returns True if user has an active StaffSecurityProfile with can_delete_records=True.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_view_only_user(user):
        return False
    
    try:
        config = DashboardSecurityConfig.get_config()
        if config.strict_admin_only_delete:
            return False
        
        if config.allow_staff_delete_override:
            profile = getattr(user, 'security_profile', None)
            if profile and profile.can_delete_records:
                return True
    except Exception:
        pass
    
    return False


def can_user_edit(user):
    """
    Checks if a user has permission to edit/create records (orders, products, batches, expenses, etc.).
    Superusers always can edit.
    View-only users (like Mitu) CANNOT edit anything.
    If strict_admin_only_edit is True, only superusers can edit.
    Otherwise, checks user's StaffSecurityProfile.can_edit_records.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_view_only_user(user):
        return False
    
    try:
        config = DashboardSecurityConfig.get_config()
        if config.strict_admin_only_edit:
            return False
        
        profile = getattr(user, 'security_profile', None)
        if profile is not None:
            return profile.can_edit_records
    except Exception:
        pass
    
    return True


def can_user_dispatch(user):
    """
    Checks if a user has permission to dispatch orders to Pathao/Steadfast courier.
    Superusers always can dispatch.
    View-only users (like Mitu) CANNOT dispatch.
    If strict_admin_only_dispatch is True, only superusers can dispatch.
    Otherwise, checks user's StaffSecurityProfile.can_dispatch_courier.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if is_view_only_user(user):
        return False
    
    try:
        config = DashboardSecurityConfig.get_config()
        if config.strict_admin_only_dispatch:
            return False
        
        profile = getattr(user, 'security_profile', None)
        if profile is not None:
            return profile.can_dispatch_courier
    except Exception:
        pass
    
    return True


def _build_login_attempt_context(client_ip, failed_attempts, unlock_at=None, now_ts=None, max_attempts=5, turnstile_error=None):
    """Build context variables expected by templates/dashboard/login.html for rate-limit & error UI."""
    current_ts = now_ts if now_ts is not None else time.time()
    is_locked = failed_attempts >= max_attempts
    remaining_lock_seconds = 0
    remaining_lock_minutes = 0

    if is_locked:
        if unlock_at:
            remaining_lock_seconds = max(0, int(unlock_at - current_ts))
            if remaining_lock_seconds <= 0:
                is_locked = False
        else:
            remaining_lock_seconds = 900

        if is_locked:
            remaining_lock_minutes = max(1, math.ceil(remaining_lock_seconds / 60))

    effective_attempts = min(failed_attempts, max_attempts) if failed_attempts > 0 else 0
    remaining_attempts = max(0, max_attempts - effective_attempts)

    return {
        'is_locked': is_locked,
        'failed_attempts': effective_attempts,
        'remaining_attempts': remaining_attempts,
        'max_attempts': max_attempts,
        'remaining_lock_minutes': remaining_lock_minutes,
        'remaining_lock_seconds': remaining_lock_seconds,
        'client_ip': client_ip or 'Unknown',
        'turnstile_error': turnstile_error,
    }


def dashboard_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dashboard:index')

    from django.utils.http import url_has_allowed_host_and_scheme
    from store.security import verify_cloudflare_turnstile, get_client_ip

    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_SECONDS = 900

    client_ip = get_client_ip(request)
    safe_ip = client_ip or 'unknown'
    login_fail_key = f"dashboard_login_fail_{safe_ip}"

    now_ts = time.time()
    cached_state = cache.get(login_fail_key)
    failed_attempts = 0
    unlock_at = None

    if isinstance(cached_state, dict):
        failed_attempts = int(cached_state.get('count', 0) or 0)
        unlock_at = cached_state.get('unlock_at')
        if unlock_at and now_ts >= unlock_at:
            cache.delete(login_fail_key)
            failed_attempts = 0
            unlock_at = None
    elif isinstance(cached_state, int) and cached_state > 0:
        failed_attempts = cached_state
        if failed_attempts >= MAX_LOGIN_ATTEMPTS:
            unlock_at = now_ts + LOCKOUT_SECONDS

    turnstile_error = None

    if request.method == 'POST':
        # 1. Brute-Force Login Rate Limiting (Max 5 failed attempts per 15 minutes per IP)
        if failed_attempts >= MAX_LOGIN_ATTEMPTS:
            context = _build_login_attempt_context(
                client_ip, failed_attempts, unlock_at=unlock_at, now_ts=now_ts, max_attempts=MAX_LOGIN_ATTEMPTS
            )
            return render(request, 'dashboard/login.html', context)

        # 2. Cloudflare Turnstile Bot Protection
        is_turnstile_valid, cf_err = verify_cloudflare_turnstile(request, expected_action="login")
        if not is_turnstile_valid:
            turnstile_error = cf_err or "Please complete the Cloudflare security check."
            context = _build_login_attempt_context(
                client_ip,
                failed_attempts,
                unlock_at=unlock_at,
                now_ts=now_ts,
                max_attempts=MAX_LOGIN_ATTEMPTS,
                turnstile_error=turnstile_error,
            )
            return render(request, 'dashboard/login.html', context)

        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None and (user.is_staff or user.is_superuser):
            cache.delete(login_fail_key)
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            raw_next = request.GET.get('next') or request.POST.get('next') or ''
            if raw_next and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(raw_next)
            return redirect('dashboard:index')
        else:
            failed_attempts += 1
            if failed_attempts >= MAX_LOGIN_ATTEMPTS:
                unlock_at = unlock_at or (now_ts + LOCKOUT_SECONDS)
            cache.set(
                login_fail_key,
                {'count': failed_attempts, 'unlock_at': unlock_at},
                timeout=LOCKOUT_SECONDS,
            )

    context = _build_login_attempt_context(
        client_ip,
        failed_attempts,
        unlock_at=unlock_at,
        now_ts=now_ts,
        max_attempts=MAX_LOGIN_ATTEMPTS,
        turnstile_error=turnstile_error,
    )
    return render(request, 'dashboard/login.html', context)


def dashboard_logout(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('dashboard:login')


def get_order_customer_sequences():
    """
    Computes chronological sequence for all valid orders per customer phone.
    Order sequence:
      1: First-time purchase (Initial order, New customer order)
      2+: Repeat purchase (2nd order onwards)
    Returns:
      order_sequence_map: dict of order_id -> sequence_number (int)
      repeat_order_ids: set of order_ids with sequence >= 2
      first_order_ids: set of order_ids with sequence == 1
    """
    all_valid_orders = Order.objects.filter(is_deleted=False).exclude(order_status='CANCELLED').values(
        'id', 'customer_phone', 'created_at'
    ).order_by('created_at', 'id')

    order_sequence_map = {}
    customer_order_ids = defaultdict(list)

    for o in all_valid_orders:
        raw_ph = o['customer_phone'] or ''
        clean_ph = ''.join(c for c in raw_ph if c.isdigit())
        if clean_ph.startswith('8801') and len(clean_ph) == 13:
            clean_ph = clean_ph[2:]
        if not clean_ph:
            clean_ph = raw_ph.strip() or f"order_{o['id']}"

        customer_order_ids[clean_ph].append(o['id'])
        seq = len(customer_order_ids[clean_ph])
        order_sequence_map[o['id']] = seq

    repeat_order_ids = {oid for oid, seq in order_sequence_map.items() if seq >= 2}
    first_order_ids = {oid for oid, seq in order_sequence_map.items() if seq == 1}

    return order_sequence_map, repeat_order_ids, first_order_ids


@user_passes_test(is_staff_user, login_url='dashboard:login')
def dashboard_index(request):
    now = timezone.localtime(timezone.now())
    today = now.date()
    
    # Precise 12:00 AM (Midnight) Asia/Dhaka boundary for daily order & revenue calculations
    today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
    today_end = today_start + timedelta(days=1)
    
    # Ensure damage, returns and expense taxonomy allocations are synchronized (throttled)
    ensure_damage_and_returns_expenses_synced(user=request.user)
    ensure_expense_taxonomy_and_allocation_synced()
    
    current_year = today.year
    current_month = today.month

    if current_month == 1:
        last_month = 12
        last_month_year = current_year - 1
    else:
        last_month = current_month - 1
        last_month_year = current_year

    prev_year = current_year - 1

    import calendar
    month_names_bn = {
        1: 'জানুয়ারি', 2: 'ফেব্রুয়ারি', 3: 'মার্চ', 4: 'এপ্রিল',
        5: 'মে', 6: 'জুন', 7: 'জুলাই', 8: 'আগস্ট',
        9: 'সেপ্টেম্বর', 10: 'অক্টোবর', 11: 'নভেম্বর', 12: 'ডিসেম্বর'
    }

    this_month_label = f"{calendar.month_name[current_month]} {current_year}"
    this_month_label_bn = f"{month_names_bn.get(current_month, '')} {current_year}"
    last_month_label = f"{calendar.month_name[last_month]} {last_month_year}"
    last_month_label_bn = f"{month_names_bn.get(last_month, '')} {last_month_year}"
    this_year_label = f"{current_year}"
    prev_year_label = f"{prev_year}"

    # Consolidated Ultra-fast Single Batch Aggregation Query for all metrics
    order_metrics = Order.objects.aggregate(
        total_orders_count=Count('id'),
        
        # Today's Incoming Orders (Confirmed & Active) - Resets at 12:00 AM Midnight
        today_orders_count=Count('id', filter=Q(created_at__gte=today_start, created_at__lt=today_end) & Q(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'])),
        today_all_orders_count=Count('id', filter=Q(created_at__gte=today_start, created_at__lt=today_end) & ~Q(order_status='CANCELLED')),
        today_pending_count=Count('id', filter=Q(created_at__gte=today_start, created_at__lt=today_end, order_status='PENDING')),
        today_confirmed_sum=Sum('total_amount', filter=Q(created_at__gte=today_start, created_at__lt=today_end) & Q(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'])),
        
        # Today's Delivered Cash / Sales (On the exact day parcel is delivered) - Resets at 12:00 AM Midnight
        today_delivered_count=Count('id', filter=Q(order_status='DELIVERED') & (Q(delivered_at__gte=today_start, delivered_at__lt=today_end) | Q(delivered_at__isnull=True, updated_at__gte=today_start, updated_at__lt=today_end))),
        today_delivered_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__gte=today_start, delivered_at__lt=today_end) | Q(delivered_at__isnull=True, updated_at__gte=today_start, updated_at__lt=today_end))),
        today_revenue=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__gte=today_start, delivered_at__lt=today_end) | Q(delivered_at__isnull=True, updated_at__gte=today_start, updated_at__lt=today_end))),
        
        # This Month
        this_month_orders_count=Count('id', filter=Q(created_at__year=current_year, created_at__month=current_month) & Q(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'])),
        this_month_all_orders_count=Count('id', filter=Q(created_at__year=current_year, created_at__month=current_month) & ~Q(order_status='CANCELLED')),
        this_month_orders_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=current_year, delivered_at__month=current_month) | Q(delivered_at__isnull=True, created_at__year=current_year, created_at__month=current_month))),
        this_month_delivered_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=current_year, delivered_at__month=current_month) | Q(delivered_at__isnull=True, created_at__year=current_year, created_at__month=current_month))),
        this_month_delivered_count=Count('id', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=current_year, delivered_at__month=current_month) | Q(delivered_at__isnull=True, created_at__year=current_year, created_at__month=current_month))),
        this_month_active_count=Count('id', filter=Q(created_at__year=current_year, created_at__month=current_month, order_status__in=['PENDING', 'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY'])),
        this_month_pipeline_sum=Sum('total_amount', filter=Q(created_at__year=current_year, created_at__month=current_month) & ~Q(order_status__in=['DELIVERED', 'CANCELLED']) & ~Q(payment_status='PAID')),
        
        # Last Month
        last_month_orders_count=Count('id', filter=Q(created_at__year=last_month_year, created_at__month=last_month) & Q(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'])),
        last_month_orders_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=last_month_year, delivered_at__month=last_month) | Q(delivered_at__isnull=True, created_at__year=last_month_year, created_at__month=last_month))),
        last_month_delivered_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=last_month_year, delivered_at__month=last_month) | Q(delivered_at__isnull=True, created_at__year=last_month_year, created_at__month=last_month))),
        last_month_delivered_count=Count('id', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=last_month_year, delivered_at__month=last_month) | Q(delivered_at__isnull=True, created_at__year=last_month_year, created_at__month=last_month))),
        last_month_pipeline_sum=Sum('total_amount', filter=Q(created_at__year=last_month_year, created_at__month=last_month) & ~Q(order_status__in=['DELIVERED', 'CANCELLED']) & ~Q(payment_status='PAID')),
        
        # This Year
        this_year_orders_count=Count('id', filter=Q(created_at__year=current_year) & Q(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'])),
        this_year_orders_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=current_year) | Q(delivered_at__isnull=True, created_at__year=current_year))),
        this_year_delivered_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=current_year) | Q(delivered_at__isnull=True, created_at__year=current_year))),
        this_year_delivered_count=Count('id', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=current_year) | Q(delivered_at__isnull=True, created_at__year=current_year))),
        
        # Previous Year
        prev_year_orders_count=Count('id', filter=Q(created_at__year=prev_year) & Q(order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'])),
        prev_year_orders_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=prev_year) | Q(delivered_at__isnull=True, created_at__year=prev_year))),
        prev_year_delivered_sum=Sum('total_amount', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=prev_year) | Q(delivered_at__isnull=True, created_at__year=prev_year))),
        prev_year_delivered_count=Count('id', filter=Q(order_status='DELIVERED') & (Q(delivered_at__year=prev_year) | Q(delivered_at__isnull=True, created_at__year=prev_year))),
        
        total_revenue=Sum('total_amount', filter=Q(order_status='DELIVERED') | Q(payment_status='PAID')),
        pipeline_revenue=Sum('total_amount', filter=~Q(order_status__in=['DELIVERED', 'CANCELLED']) & ~Q(payment_status='PAID')),
    )

    total_orders_count = order_metrics['total_orders_count'] or 0
    today_orders_count = order_metrics['today_orders_count'] or 0
    today_all_orders_count = order_metrics['today_all_orders_count'] or 0
    today_pending_count = order_metrics['today_pending_count'] or 0
    today_confirmed_sum = order_metrics['today_confirmed_sum'] or 0
    today_delivered_count = order_metrics['today_delivered_count'] or 0
    today_delivered_sum = order_metrics['today_delivered_sum'] or 0
    today_revenue = order_metrics['today_revenue'] or 0
    today_orders_sum = today_delivered_sum

    this_month_orders_count = order_metrics['this_month_orders_count'] or 0
    this_month_all_orders_count = order_metrics['this_month_all_orders_count'] or 0
    this_month_orders_sum = order_metrics['this_month_orders_sum'] or 0
    this_month_delivered_sum = order_metrics['this_month_delivered_sum'] or 0
    this_month_delivered_count = order_metrics['this_month_delivered_count'] or 0
    this_month_active_count = order_metrics['this_month_active_count'] or 0
    this_month_pipeline_sum = order_metrics['this_month_pipeline_sum'] or 0

    last_month_orders_count = order_metrics['last_month_orders_count'] or 0
    last_month_orders_sum = order_metrics['last_month_orders_sum'] or 0
    last_month_delivered_sum = order_metrics['last_month_delivered_sum'] or 0
    last_month_delivered_count = order_metrics['last_month_delivered_count'] or 0
    last_month_pipeline_sum = order_metrics['last_month_pipeline_sum'] or 0

    this_year_orders_count = order_metrics['this_year_orders_count'] or 0
    this_year_orders_sum = order_metrics['this_year_orders_sum'] or 0
    this_year_delivered_sum = order_metrics['this_year_delivered_sum'] or 0
    this_year_delivered_count = order_metrics['this_year_delivered_count'] or 0

    prev_year_orders_count = order_metrics['prev_year_orders_count'] or 0
    prev_year_orders_sum = order_metrics['prev_year_orders_sum'] or 0
    prev_year_delivered_sum = order_metrics['prev_year_delivered_sum'] or 0
    prev_year_delivered_count = order_metrics['prev_year_delivered_count'] or 0

    total_revenue = order_metrics['total_revenue'] or 0
    pipeline_revenue = order_metrics['pipeline_revenue'] or 0
    
    # Expenses & Net Profit
    total_expenses = Expense.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    net_profit = float(total_revenue) - float(total_expenses)
    profit_margin = round((net_profit / float(total_revenue)) * 100, 1) if float(total_revenue) > 0 else 0
    
    # Status Counts (Optimized: 1 single group-by query instead of 6 queries)
    status_counts_dict = dict(Order.objects.values('order_status').annotate(cnt=Count('id')).values_list('order_status', 'cnt'))
    pending_count = status_counts_dict.get('PENDING', 0)
    confirmed_count = status_counts_dict.get('CONFIRMED', 0)
    packing_count = status_counts_dict.get('PACKING', 0)
    out_for_delivery_count = status_counts_dict.get('OUT_FOR_DELIVERY', 0)
    delivered_count = status_counts_dict.get('DELIVERED', 0)
    cancelled_count = status_counts_dict.get('CANCELLED', 0)
    
    # Advanced KPIs (Single aggregation query for jars across all active non-deleted orders)
    jar_stats = OrderItem.objects.filter(order__is_deleted=False).aggregate(
        delivered_jars=Sum('quantity', filter=(Q(order__order_status='DELIVERED') | Q(order__payment_status='PAID')) & ~Q(order__order_status='CANCELLED')),
        total_jars=Sum('quantity', filter=~Q(order__order_status='CANCELLED')),
        pipeline_jars=Sum('quantity', filter=~Q(order__order_status__in=['DELIVERED', 'CANCELLED']) & ~Q(order__payment_status='PAID')),

        # Today Jars
        today_jars=Sum('quantity', filter=Q(order__created_at__gte=today_start, order__created_at__lt=today_end) & ~Q(order__order_status='CANCELLED')),
        today_delivered_jars=Sum('quantity', filter=Q(order__order_status='DELIVERED') & (Q(order__delivered_at__gte=today_start, order__delivered_at__lt=today_end) | Q(order__delivered_at__isnull=True, order__updated_at__gte=today_start, order__updated_at__lt=today_end))),

        # This Month Jars
        this_month_jars=Sum('quantity', filter=Q(order__created_at__year=current_year, order__created_at__month=current_month) & ~Q(order__order_status='CANCELLED')),
        this_month_delivered_jars=Sum('quantity', filter=Q(order__order_status='DELIVERED') & (Q(order__delivered_at__year=current_year, order__delivered_at__month=current_month) | Q(order__delivered_at__isnull=True, order__created_at__year=current_year, order__created_at__month=current_month))),

        # Last Month Jars
        last_month_jars=Sum('quantity', filter=Q(order__created_at__year=last_month_year, order__created_at__month=last_month) & ~Q(order__order_status='CANCELLED')),
        last_month_delivered_jars=Sum('quantity', filter=Q(order__order_status='DELIVERED') & (Q(order__delivered_at__year=last_month_year, order__delivered_at__month=last_month) | Q(order__delivered_at__isnull=True, order__created_at__year=last_month_year, order__created_at__month=last_month))),

        # This Year Jars
        this_year_jars=Sum('quantity', filter=Q(order__created_at__year=current_year) & ~Q(order__order_status='CANCELLED')),
        this_year_delivered_jars=Sum('quantity', filter=Q(order__order_status='DELIVERED') & (Q(order__delivered_at__year=current_year) | Q(order__delivered_at__isnull=True, order__created_at__year=current_year))),

        # Previous Year Jars
        prev_year_jars=Sum('quantity', filter=Q(order__created_at__year=prev_year) & ~Q(order__order_status='CANCELLED')),
        prev_year_delivered_jars=Sum('quantity', filter=Q(order__order_status='DELIVERED') & (Q(order__delivered_at__year=prev_year) | Q(order__delivered_at__isnull=True, order__created_at__year=prev_year)))
    )
    delivered_jars_sold = jar_stats['delivered_jars'] or 0
    total_jars_sold = jar_stats['total_jars'] or 0
    pipeline_jars_sold = jar_stats['pipeline_jars'] or 0
    today_jars_count = jar_stats['today_jars'] or 0
    today_delivered_jars = jar_stats['today_delivered_jars'] or 0
    this_month_jars_count = jar_stats['this_month_jars'] or 0
    this_month_delivered_jars = jar_stats['this_month_delivered_jars'] or 0
    last_month_jars_count = jar_stats['last_month_jars'] or 0
    last_month_delivered_jars = jar_stats['last_month_delivered_jars'] or 0
    this_year_jars_count = jar_stats['this_year_jars'] or 0
    this_year_delivered_jars = jar_stats['this_year_delivered_jars'] or 0
    prev_year_jars_count = jar_stats['prev_year_jars'] or 0
    prev_year_delivered_jars = jar_stats['prev_year_delivered_jars'] or 0

    avg_order_val = round(float(total_revenue) / delivered_count, 1) if delivered_count > 0 else 0
    delivery_rate = round((delivered_count / total_orders_count) * 100, 1) if total_orders_count > 0 else 0
    
    # Inventory & Low Stock Tracking (Ultra-fast 1-Query Batch Demand)
    # Orders in PACKING, OUT_FOR_DELIVERY, or DELIVERED have already had physical stock deducted.
    # Therefore, active unfulfilled demand is strictly orders in PENDING or CONFIRMED status.
    active_demands = dict(
        OrderItem.objects.filter(
            order__is_deleted=False,
            order__order_status__in=['PENDING', 'CONFIRMED']
        ).values('product_id').annotate(total_demand=Sum('quantity')).values_list('product_id', 'total_demand')
    )

    all_catalog_products = list(Product.objects.all().select_related('category').order_by('stock_count', 'name'))
    total_products_count = len(all_catalog_products)
    low_stock_products = []
    critical_stock_count = 0
    total_needed_jars = 0
    total_current_inventory = 0

    for p in all_catalog_products:
        demand = active_demands.get(p.id, 0)
        needed = max(0, demand - p.stock_count)
        is_low = needed > 0 or (p.stock_count == 0 and not p.is_in_stock)
        is_crit = (p.stock_count == 0 and demand > 0)
        
        p._computed_demand = demand
        p._computed_needed = needed
        p._computed_is_low = is_low
        p._computed_is_crit = is_crit

        if is_low:
            low_stock_products.append(p)
        if is_crit:
            critical_stock_count += 1
        total_needed_jars += needed
        total_current_inventory += p.stock_count

    low_stock_count = len(low_stock_products)

    # 1. 10-Day Sales & Revenue Trend Calculation
    # - Orders Series: Confirmed orders that arrived on each date
    # - Revenue Series: Realized revenue of parcels delivered on each date
    days_to_plot = 10
    start_plot_dt = today_start - datetime.timedelta(days=days_to_plot)

    # Fetch incoming confirmed orders grouped by created_at date (in local time)
    incoming_confirmed_orders = list(Order.objects.filter(
        created_at__gte=start_plot_dt,
        order_status__in=['CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED']
    ).values('created_at', 'total_amount'))

    # Fetch delivered orders
    delivered_orders = list(Order.objects.filter(
        order_status='DELIVERED'
    ).filter(
        Q(delivered_at__gte=start_plot_dt) |
        Q(delivered_at__isnull=True, updated_at__gte=start_plot_dt)
    ).values('delivered_at', 'updated_at', 'created_at', 'total_amount'))

    # Calculate daily total jars ordered (sum of item quantities in active orders by created_at)
    incoming_jars_qs = list(OrderItem.objects.filter(
        order__created_at__gte=start_plot_dt,
        order__is_deleted=False
    ).exclude(
        order__order_status='CANCELLED'
    ).values('order__created_at', 'quantity'))

    daily_orders_map = {}
    daily_revenue_map = {}
    daily_jars_map = {}

    for ord_info in incoming_confirmed_orders:
        c_dt = ord_info.get('created_at')
        if c_dt:
            d = timezone.localtime(c_dt).date()
            daily_orders_map[d] = daily_orders_map.get(d, 0) + 1

    for jar_item in incoming_jars_qs:
        c_dt = jar_item.get('order__created_at')
        if c_dt:
            d = timezone.localtime(c_dt).date()
            daily_jars_map[d] = daily_jars_map.get(d, 0) + (jar_item.get('quantity') or 0)

    for ord_info in delivered_orders:
        deliv_dt = ord_info.get('delivered_at') or ord_info.get('updated_at') or ord_info.get('created_at')
        if deliv_dt:
            d = timezone.localtime(deliv_dt).date()
            if d and d >= (today - datetime.timedelta(days=days_to_plot)):
                daily_revenue_map[d] = daily_revenue_map.get(d, 0.0) + float(ord_info['total_amount'] or 0)

    date_labels = []
    revenue_series = []
    orders_series = []
    jars_series = []
    for i in range(days_to_plot - 1, -1, -1):
        target_date = today - datetime.timedelta(days=i)
        date_labels.append(target_date.strftime('%b %d'))
        revenue_series.append(round(daily_revenue_map.get(target_date, 0.0), 2))
        orders_series.append(daily_orders_map.get(target_date, 0))
        jars_series.append(daily_jars_map.get(target_date, 0))

    # 2. Dynamic Product Sales Performance Breakdown (Delivered / Out for Delivery / Paid orders)
    order_items_qs = OrderItem.objects.filter(
        order__is_deleted=False
    ).filter(
        Q(order__order_status__in=['DELIVERED', 'OUT_FOR_DELIVERY']) | Q(order__payment_status='PAID')
    )
    
    # Aggregate sales by product_id and product_name
    sales_by_id = {}
    sales_by_name = {}
    for row in order_items_qs.values('product_id', 'product_name').annotate(
        total_qty=Sum('quantity'),
        total_sales=Sum('total_price')
    ):
        qty = row['total_qty'] or 0
        sales = float(row['total_sales'] or 0)
        pid = row['product_id']
        pname = (row['product_name'] or '').strip()
        if pid:
            sales_by_id[pid] = sales_by_id.get(pid, {'qty': 0, 'sales': 0, 'name': pname})
            sales_by_id[pid]['qty'] += qty
            sales_by_id[pid]['sales'] += sales
        if pname:
            name_key = pname.lower()
            sales_by_name[name_key] = sales_by_name.get(name_key, {'qty': 0, 'sales': 0, 'name': pname})
            sales_by_name[name_key]['qty'] += qty
            sales_by_name[name_key]['sales'] += sales

    # Auto-load ALL products from inventory catalog
    catalog_prods = all_catalog_products
    processed_pids = set()
    processed_names = set()
    product_stats = []

    for prod in catalog_prods:
        matched_stat = sales_by_id.get(prod.id)
        if not matched_stat:
            matched_stat = sales_by_name.get(prod.name.strip().lower(), {'qty': 0, 'sales': 0, 'name': prod.name})
        
        qty = matched_stat.get('qty', 0)
        sales = matched_stat.get('sales', 0)
        product_stats.append({
            'id': prod.id,
            'name': prod.name,
            'is_featured': getattr(prod, 'is_featured', False),
            'quantity': qty,
            'sales': sales,
            'stock': prod.stock_count,
        })
        processed_pids.add(prod.id)
        processed_names.add(prod.name.strip().lower())

    # Include any legacy orders for products that might not be in the current active Product catalog
    for name_key, stat in sales_by_name.items():
        if name_key not in processed_names and stat['qty'] > 0:
            product_stats.append({
                'id': None,
                'name': stat['name'],
                'is_featured': False,
                'quantity': stat['qty'],
                'sales': stat['sales'],
                'stock': 0,
            })

    # Sort descending by quantity sold, then featured status, then by product ID (lower ID / Product 1 comes first), then name
    product_stats.sort(key=lambda x: (
        -x['quantity'],
        0 if x.get('is_featured') else 1,
        x.get('id') if x.get('id') is not None else 999999,
        x['name']
    ))

    top_products = product_stats[:10]
    product_labels = [p['name'] for p in top_products]
    product_qty_data = [p['quantity'] for p in top_products]

    if not product_labels:
        product_labels = ['No Products Added']
        product_qty_data = [0]

    best_seller = None
    if product_stats and product_stats[0]['quantity'] > 0:
        best_seller = {
            'name': product_stats[0]['name'],
            'quantity': product_stats[0]['quantity'],
            'sales': product_stats[0]['sales'],
        }

    # 3. Payment Methods Breakdown (Delivered/Paid orders only)
    pay_counts = dict(
        Order.objects.filter(Q(order_status='DELIVERED') | Q(payment_status='PAID'))
        .values('payment_method')
        .annotate(cnt=Count('id'))
        .values_list('payment_method', 'cnt')
    )
    cod_count = pay_counts.get('COD', 0)
    bkash_count = pay_counts.get('BKASH_ONLINE', 0) + pay_counts.get('BKASH', 0)
    nagad_count = pay_counts.get('NAGAD', 0)
    payment_data = [cod_count, bkash_count, nagad_count]

    # 4. Delivery Zone Breakdown (Delivered/Paid orders only)
    zone_counts = dict(
        Order.objects.filter(Q(order_status='DELIVERED') | Q(payment_status='PAID'))
        .values('delivery_zone')
        .annotate(cnt=Count('id'))
        .values_list('delivery_zone', 'cnt')
    )
    inside_dhaka_count = zone_counts.get('INSIDE_DHAKA', 0)
    outside_dhaka_count = zone_counts.get('OUTSIDE_DHAKA', 0)


    # 5. Expense Categories Breakdown (Real database sums)
    category_totals = Expense.objects.values('category').annotate(cat_sum=Sum('amount')).order_by('-cat_sum')
    cat_labels_map = dict(Expense.CATEGORY_CHOICES)
    for cat in ExpenseCategory.objects.all():
        cat_labels_map[cat.slug] = cat.name
        cat_labels_map[cat.name] = cat.name
    
    chart_cat_labels = []
    chart_cat_data = []
    for item in category_totals:
        chart_cat_labels.append(cat_labels_map.get(item['category'], item['category']))
        chart_cat_data.append(float(item['cat_sum']))

    if not chart_cat_labels:
        chart_cat_labels = ['Packaging & Jars', 'Cucumbers & Veggies', 'Vinegar & Spices', 'Courier & Logistics']
        chart_cat_data = [0, 0, 0, 0]

    # Sub-category / Specific Expense Head breakdown
    subcat_totals = Expense.objects.filter(sub_category__isnull=False).exclude(sub_category='').values('sub_category').annotate(sub_sum=Sum('amount')).order_by('-sub_sum')
    chart_subcat_labels = []
    chart_subcat_data = []
    for item in subcat_totals[:10]:
        if item['sub_category']:
            chart_subcat_labels.append(str(item['sub_category']))
            chart_subcat_data.append(float(item['sub_sum'] or 0))

    # -----------------------------------------------------------------
    # Customer Retention & Cohort Analytics (New vs Repeat Customers)
    # Requirement: Repeat orders count strictly starting from 2nd order (not 1st order)
    # Searchable and filterable by date range.
    # -----------------------------------------------------------------
    retention_period = request.GET.get('retention_period', 'ALL')
    retention_start_str = request.GET.get('retention_start', '').strip()
    retention_end_str = request.GET.get('retention_end', '').strip()

    ret_start_dt = None
    ret_end_dt = None

    if retention_start_str:
        try:
            s_date = datetime.datetime.strptime(retention_start_str, '%Y-%m-%d').date()
            ret_start_dt = timezone.make_aware(datetime.datetime.combine(s_date, datetime.time.min))
        except ValueError:
            pass

    if retention_end_str:
        try:
            e_date = datetime.datetime.strptime(retention_end_str, '%Y-%m-%d').date()
            ret_end_dt = timezone.make_aware(datetime.datetime.combine(e_date, datetime.time.max))
        except ValueError:
            pass

    if not ret_start_dt and not ret_end_dt:
        if retention_period == 'today':
            ret_start_dt = today_start
            ret_end_dt = today_end
        elif retention_period == 'this_month':
            m_start = datetime.date(current_year, current_month, 1)
            ret_start_dt = timezone.make_aware(datetime.datetime.combine(m_start, datetime.time.min))
            ret_end_dt = today_end
        elif retention_period == 'last_month':
            lm_start = datetime.date(last_month_year, last_month, 1)
            _, lm_last_day = calendar.monthrange(last_month_year, last_month)
            lm_end = datetime.date(last_month_year, last_month, lm_last_day)
            ret_start_dt = timezone.make_aware(datetime.datetime.combine(lm_start, datetime.time.min))
            ret_end_dt = timezone.make_aware(datetime.datetime.combine(lm_end, datetime.time.max))
        elif retention_period == 'last_30_days':
            ret_start_dt = today_start - datetime.timedelta(days=30)
            ret_end_dt = today_end
        elif retention_period == 'this_year':
            y_start = datetime.date(current_year, 1, 1)
            ret_start_dt = timezone.make_aware(datetime.datetime.combine(y_start, datetime.time.min))
            ret_end_dt = today_end
        elif retention_period == 'prev_year':
            py_start = datetime.date(prev_year, 1, 1)
            py_end = datetime.date(prev_year, 12, 31)
            ret_start_dt = timezone.make_aware(datetime.datetime.combine(py_start, datetime.time.min))
            ret_end_dt = timezone.make_aware(datetime.datetime.combine(py_end, datetime.time.max))

    order_sequence_map, repeat_order_ids, first_order_ids = get_order_customer_sequences()

    all_retention_orders = list(Order.objects.filter(is_deleted=False).exclude(order_status='CANCELLED').values(
        'id', 'customer_phone', 'customer_name', 'total_amount', 'created_at', 'order_number', 'delivery_city'
    ).order_by('-created_at'))

    period_orders = []
    for o in all_retention_orders:
        o_dt = o['created_at']
        if ret_start_dt and o_dt < ret_start_dt:
            continue
        if ret_end_dt and o_dt > ret_end_dt:
            continue
        period_orders.append(o)

    period_total_orders = len(period_orders)
    period_first_orders = [o for o in period_orders if order_sequence_map.get(o['id'], 1) == 1]
    period_repeat_orders = [o for o in period_orders if order_sequence_map.get(o['id'], 1) >= 2]

    new_orders_count = len(period_first_orders)
    repeat_orders_count = len(period_repeat_orders)

    repeat_rate = round((repeat_orders_count / period_total_orders) * 100, 1) if period_total_orders > 0 else 0.0
    new_rate = round(100.0 - repeat_rate, 1) if period_total_orders > 0 else 0.0

    repeat_revenue = sum(float(o['total_amount'] or 0.0) for o in period_repeat_orders)
    new_revenue = sum(float(o['total_amount'] or 0.0) for o in period_first_orders)

    repeat_cust_map = {}
    for o in period_repeat_orders:
        raw_ph = o['customer_phone'] or ''
        clean_ph = ''.join(c for c in raw_ph if c.isdigit())
        if clean_ph.startswith('8801') and len(clean_ph) == 13:
            clean_ph = clean_ph[2:]
        if not clean_ph:
            clean_ph = raw_ph.strip() or f"order_{o['id']}"

        if clean_ph not in repeat_cust_map:
            repeat_cust_map[clean_ph] = {
                'phone': clean_ph,
                'name': o['customer_name'] or 'Customer',
                'city': o['delivery_city'] or 'Dhaka',
                'repeat_orders_count': 0,
                'repeat_spent': 0.0,
                'latest_order_number': o['order_number'],
                'latest_order_date': o['created_at'],
            }
        repeat_cust_map[clean_ph]['repeat_orders_count'] += 1
        repeat_cust_map[clean_ph]['repeat_spent'] += float(o['total_amount'] or 0.0)

    repeat_customers_list = list(repeat_cust_map.values())
    repeat_customers_list.sort(key=lambda x: (x['repeat_orders_count'], x['repeat_spent']), reverse=True)
    repeat_customers_count = len(repeat_customers_list)

    if retention_start_str and retention_end_str:
        retention_period_label = f"{retention_start_str} to {retention_end_str}"
    elif retention_period == 'today':
        retention_period_label = "Today (আজকের)"
    elif retention_period == 'this_month':
        retention_period_label = f"This Month ({this_month_label})"
    elif retention_period == 'last_month':
        retention_period_label = f"Last Month ({last_month_label})"
    elif retention_period == 'last_30_days':
        retention_period_label = "Last 30 Days (বিগত ৩০ দিন)"
    elif retention_period == 'this_year':
        retention_period_label = f"This Year ({this_year_label})"
    else:
        retention_period_label = "All Time (সর্বমোট)"

    # JSON Serialized for Chart.js
    chart_data = {
        'trendLabels': date_labels,
        'revenueData': revenue_series,
        'ordersData': orders_series,
        'jarsData': jars_series,
        'statusLabels': ['Pending', 'Confirmed', 'Packing', 'Out for Delivery', 'Delivered', 'Cancelled'],
        'statusData': [pending_count, confirmed_count, packing_count, out_for_delivery_count, delivered_count, cancelled_count],
        'productLabels': product_labels,
        'productQtyData': product_qty_data,
        'paymentLabels': ['Cash on Delivery (COD)', 'bKash Wallet', 'Nagad Wallet'],
        'paymentData': payment_data,
        'zoneLabels': ['Inside Dhaka (Home Delivery)', 'Outside Dhaka (Courier)'],
        'zoneData': [inside_dhaka_count, outside_dhaka_count],
        'catLabels': chart_cat_labels,
        'catData': chart_cat_data,
        'subcatLabels': chart_subcat_labels,
        'subcatData': chart_subcat_data,
        'comparisonLabels': ['Gross Revenue (৳)', 'Total Costs (৳)', 'Net Profit / Balance (৳)'],
        'comparisonData': [float(total_revenue), float(total_expenses), float(net_profit)],
        'customerLabels': ['New Orders (1st Purchase)', 'Repeat Orders (2nd+ Purchase)'],
        'customerData': [new_orders_count, repeat_orders_count],
        'customerRates': [new_rate, repeat_rate],
    }

    # Recent orders preview for analytics dashboard
    recent_orders = Order.objects.all().prefetch_related('items')[:5]

    # Price increase/decrease history preview for analytics dashboard
    recent_price_changes = PriceHistory.objects.select_related('product', 'changed_by').all().order_by('-created_at')[:6]
    price_stats = {
        'total_events': PriceHistory.objects.count(),
        'increases': PriceHistory.objects.filter(change_type='INCREASE').count(),
        'decreases': PriceHistory.objects.filter(change_type='DECREASE').count(),
    }

    # Pending Reviews waiting for admin moderation & approval
    from store.models import Review
    pending_reviews = list(Review.objects.filter(is_approved=False).select_related('product').order_by('-created_at')[:6])
    pending_reviews_total = Review.objects.filter(is_approved=False).count()

    # Match reviewer phone numbers with customer orders to verify authenticity
    phone_to_order = {}
    for ord_row in Order.objects.filter(is_deleted=False).values('customer_phone', 'order_number').order_by('-created_at'):
        raw_p = (ord_row['customer_phone'] or '').strip()
        if raw_p:
            digits = ''.join(ch for ch in raw_p if ch.isdigit())
            clean_p = digits[-11:] if len(digits) >= 11 else digits
            if clean_p and clean_p not in phone_to_order:
                phone_to_order[clean_p] = ord_row['order_number']

    for r in pending_reviews:
        raw_rp = (getattr(r, 'reviewer_phone', '') or '').strip()
        r_digits = ''.join(ch for ch in raw_rp if ch.isdigit())
        clean_rp = r_digits[-11:] if len(r_digits) >= 11 else r_digits
        r.matched_order_number = phone_to_order.get(clean_rp) if clean_rp else None
        r.is_verified_customer = bool(r.matched_order_number)

    context = {
        'pending_reviews': pending_reviews,
        'pending_reviews_total': pending_reviews_total,
        'recent_orders': recent_orders,
        'recent_price_changes': recent_price_changes,
        'price_stats': price_stats,
        'best_seller': best_seller,
        'total_orders_count': total_orders_count,
        'today_orders_count': today_orders_count,
        'today_all_orders_count': today_all_orders_count,
        'today_pending_count': today_pending_count,
        'today_confirmed_sum': today_confirmed_sum,
        'today_delivered_count': today_delivered_count,
        'today_delivered_sum': today_delivered_sum,
        'today_orders_sum': today_orders_sum,
        'today_revenue': today_revenue,
        'today_jars_count': today_jars_count,
        'today_delivered_jars': today_delivered_jars,
        'total_revenue': total_revenue,
        'pipeline_revenue': pipeline_revenue,
        'this_month_orders_sum': this_month_orders_sum,
        'this_month_orders_count': this_month_orders_count,
        'this_month_delivered_sum': this_month_delivered_sum,
        'this_month_delivered_count': this_month_delivered_count,
        'this_month_active_count': this_month_active_count,
        'this_month_pipeline_sum': this_month_pipeline_sum,
        'this_month_label': this_month_label,
        'this_month_label_bn': this_month_label_bn,
        'this_month_jars_count': this_month_jars_count,
        'this_month_delivered_jars': this_month_delivered_jars,
        'last_month_orders_sum': last_month_orders_sum,
        'last_month_orders_count': last_month_orders_count,
        'last_month_delivered_sum': last_month_delivered_sum,
        'last_month_delivered_count': last_month_delivered_count,
        'last_month_pipeline_sum': last_month_pipeline_sum,
        'last_month_label': last_month_label,
        'last_month_label_bn': last_month_label_bn,
        'last_month_jars_count': last_month_jars_count,
        'last_month_delivered_jars': last_month_delivered_jars,
        'this_year_orders_sum': this_year_orders_sum,
        'this_year_orders_count': this_year_orders_count,
        'this_year_delivered_sum': this_year_delivered_sum,
        'this_year_delivered_count': this_year_delivered_count,
        'this_year_label': this_year_label,
        'this_year_jars_count': this_year_jars_count,
        'this_year_delivered_jars': this_year_delivered_jars,
        'prev_year_orders_sum': prev_year_orders_sum,
        'prev_year_orders_count': prev_year_orders_count,
        'prev_year_delivered_sum': prev_year_delivered_sum,
        'prev_year_delivered_count': prev_year_delivered_count,
        'prev_year_label': prev_year_label,
        'prev_year_jars_count': prev_year_jars_count,
        'prev_year_delivered_jars': prev_year_delivered_jars,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'avg_order_val': avg_order_val,
        'total_jars_sold': total_jars_sold,
        'delivered_jars_sold': delivered_jars_sold,
        'pipeline_jars_sold': pipeline_jars_sold,
        'delivery_rate': delivery_rate,
        'low_stock_count': low_stock_count,
        'critical_stock_count': critical_stock_count,
        'low_stock_products': low_stock_products,
        'total_needed_jars': total_needed_jars,
        'total_current_inventory': total_current_inventory,
        'total_products_count': total_products_count,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'packing_count': packing_count,
        'out_for_delivery_count': out_for_delivery_count,
        'delivered_count': delivered_count,
        'cancelled_count': cancelled_count,
        'retention_period': retention_period,
        'retention_period_label': retention_period_label,
        'retention_start': retention_start_str,
        'retention_end': retention_end_str,
        'period_total_orders': period_total_orders,
        'repeat_customers_count': repeat_customers_count,
        'repeat_orders_count': repeat_orders_count,
        'new_orders_count': new_orders_count,
        'repeat_rate': repeat_rate,
        'new_rate': new_rate,
        'repeat_revenue': repeat_revenue,
        'new_revenue': new_revenue,
        'repeat_customers_list': repeat_customers_list,
        'chart_data_json': json.dumps(chart_data),
    }
    return render(request, 'dashboard/index.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def orders_list(request):
    if request.method == 'POST' and request.POST.get('action') == 'bulk_update_status':
        if not can_user_edit(request.user):
            messages.error(request, 'Permission Denied: অর্ডার স্ট্যাটাস পরিবর্তন করার অনুমতি নেই। (Status editing restricted.)')
            return redirect(request.META.get('HTTP_REFERER') or 'dashboard:orders')

        new_status = request.POST.get('new_status', '').strip()
        raw_orders = request.POST.get('order_numbers', '')
        order_numbers = [o.strip() for o in raw_orders.split(',') if o.strip()]

        if new_status in dict(Order.ORDER_STATUS_CHOICES) and order_numbers:
            target_orders = Order.objects.prefetch_related('items__product').filter(order_number__in=order_numbers)
            updated_count = 0
            CONFIRMED_STATUSES = {'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'}
            for order in target_orders:
                old_status = order.order_status
                if old_status != new_status:
                    adjust_inventory_for_order_status_change(order, old_status, new_status, user=request.user)
                    order.order_status = new_status
                    if new_status == 'DELIVERED' and order.payment_status == 'UNPAID':
                        order.payment_status = 'PAID'
                    if new_status in CONFIRMED_STATUSES and old_status not in CONFIRMED_STATUSES:
                        try:
                            from store.meta_capi import send_meta_purchase_event_on_accept
                            send_meta_purchase_event_on_accept(order, request=request)
                        except Exception as _e:
                            print(f"Failed to dispatch Meta CAPI Purchase: {_e}")
                    order.save()
                    updated_count += 1
            status_label = dict(Order.ORDER_STATUS_CHOICES).get(new_status, new_status)
            if updated_count > 0:
                wa_hint = " (Tip: Select Shipped orders and use the WhatsApp Queue to send messages one by one.)" if new_status == 'OUT_FOR_DELIVERY' else ""
                messages.success(request, f"Updated {updated_count} order(s) to '{status_label}'{wa_hint}")
            else:
                messages.info(request, f"Selected orders are already in '{status_label}' status.")
        return redirect(request.META.get('HTTP_REFERER') or 'dashboard:orders')

    # High-performance single aggregation query for order status counts
    status_counts = dict(
        Order.objects.values('order_status').annotate(cnt=Count('id')).values_list('order_status', 'cnt')
    )
    pending_count = status_counts.get('PENDING', 0)
    confirmed_count = status_counts.get('CONFIRMED', 0)
    packing_count = status_counts.get('PACKING', 0)
    out_for_delivery_count = status_counts.get('OUT_FOR_DELIVERY', 0)
    delivered_count = status_counts.get('DELIVERED', 0)
    cancelled_count = status_counts.get('CANCELLED', 0)
    total_orders_count = sum(status_counts.values())

    orders = Order.objects.all().prefetch_related('items', 'items__product').order_by('-created_at', '-id')
    status_filter = request.GET.get('status', 'ALL')
    period_filter = request.GET.get('period', 'ALL')
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    search_query = request.GET.get('q', '').strip()
    zone_filter = request.GET.get('zone', 'ALL')
    payment_filter = request.GET.get('payment', 'ALL')

    now = timezone.localtime(timezone.now())
    today = now.date()
    today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
    today_end = today_start + timedelta(days=1)
    current_year = today.year
    current_month = today.month
    if current_month == 1:
        last_month = 12
        last_month_year = current_year - 1
    else:
        last_month = current_month - 1
        last_month_year = current_year
    prev_year = current_year - 1

    # Date Range Search / Custom Date filtering
    if start_date:
        try:
            s_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
            s_dt = timezone.make_aware(datetime.datetime.combine(s_date, datetime.time.min))
            orders = orders.filter(created_at__gte=s_dt)
        except ValueError:
            pass

    if end_date:
        try:
            e_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
            e_dt = timezone.make_aware(datetime.datetime.combine(e_date, datetime.time.max))
            orders = orders.filter(created_at__lte=e_dt)
        except ValueError:
            pass

    # Period presets (only if custom start_date/end_date not explicitly set)
    if not start_date and not end_date:
        if period_filter == 'today':
            orders = orders.filter(created_at__gte=today_start, created_at__lt=today_end)
        elif period_filter == 'this_month':
            orders = orders.filter(created_at__year=current_year, created_at__month=current_month)
        elif period_filter == 'last_month':
            orders = orders.filter(created_at__year=last_month_year, created_at__month=last_month)
        elif period_filter == 'this_year':
            orders = orders.filter(created_at__year=current_year)
        elif period_filter == 'prev_year':
            orders = orders.filter(created_at__year=prev_year)

    if status_filter and status_filter != 'ALL':
        orders = orders.filter(order_status=status_filter)
        
    if zone_filter and zone_filter != 'ALL':
        orders = orders.filter(delivery_zone=zone_filter)

    # Customer retention sequence: 1 = Initial purchase, 2+ = Repeat purchase
    order_sequence_map, repeat_order_ids, first_order_ids = get_order_customer_sequences()

    customer_type = request.GET.get('customer_type', 'ALL')
    if customer_type == 'repeat':
        # Strictly repeat purchases (2nd order onwards; never includes 1st order)
        orders = orders.filter(id__in=repeat_order_ids)
    elif customer_type == 'new':
        # Strictly first-time purchases
        orders = orders.filter(id__in=first_order_ids)

    if payment_filter and payment_filter != 'ALL':
        orders = orders.filter(payment_status=payment_filter)

    if search_query:
        import re
        clean_search = search_query.lstrip('#').strip()
        num_match = re.search(r'(\d+)', clean_search)
        
        s_filter = (
            Q(order_number__icontains=search_query) |
            Q(order_number__icontains=clean_search) |
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(delivery_city__icontains=search_query) |
            Q(payment_trx_id__icontains=search_query)
        )
        if num_match:
            try:
                num_val = int(num_match.group(1))
                s_filter |= Q(order_number__iexact=f"PKP-{num_val:05d}")
                s_filter |= Q(order_number__iexact=f"PKP-{num_val:04d}")
            except Exception:
                pass
        orders = orders.filter(s_filter)

    # CSV Export for Orders (respects current filters)
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="pickpickles_orders_{today.strftime("%Y%m%d")}.csv"'
        response.write('\ufeff'.encode('utf8'))
        writer = csv.writer(response)
        writer.writerow([
            'Order #', 'Date & Time', 'Customer Name', 'Phone', 'City', 'Zone', 'Delivery Address',
            'Items Ordered', 'Total Jars', 'Subtotal (BDT)', 'Delivery Fee (BDT)', 'Total Amount (BDT)',
            'Payment Method', 'Payment Status', 'bKash TrxID', 'Order Status', 'Courier', 'Consignment ID'
        ])
        for o in orders:
            items_summary = ", ".join(f"{itm.product_name} (x{itm.quantity})" for itm in o.items.all())
            writer.writerow([
                o.order_number,
                timezone.localtime(o.created_at).strftime('%Y-%m-%d %I:%M %p'),
                o.customer_name,
                o.customer_phone,
                o.delivery_city,
                o.get_delivery_zone_display(),
                o.delivery_address,
                items_summary,
                o.total_items_count,
                o.subtotal,
                o.delivery_fee,
                o.total_amount,
                o.get_payment_method_display(),
                o.payment_status,
                o.payment_trx_id or '',
                o.get_order_status_display(),
                o.active_courier_name or '',
                o.active_consignment_id or '',
            ])
        return response

    # Pagination configuration (Default 10 items per page)
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    paginator = Paginator(orders, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Elided page range for pagination navigation
    try:
        elided_page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        elided_page_range = paginator.page_range

    # Attach customer order sequence to orders on this page:
    # Sequence 1: 1st-time purchase (Initial order) -> NOT a repeat order
    # Sequence 2+: Repeat purchase (2nd order onwards)
    for o in page_obj:
        seq = order_sequence_map.get(o.id, 1)
        o.is_repeat_order = (seq >= 2)
        o.order_sequence = seq
        if seq == 1:
            o.order_seq_label = "1st Order"
        elif seq == 2:
            o.order_seq_label = "2nd Order"
        elif seq == 3:
            o.order_seq_label = "3rd Order"
        else:
            o.order_seq_label = f"{seq}th Order"

    promo_setting = PromotionSetting.get_settings()
    active_coupons = [
        c for c in Coupon.objects.filter(is_active=True).order_by('-created_at')
        if c.is_valid_now()[0]
    ]
    manual_offer_config = {
        'is_active': bool(promo_setting.is_active),
        'bundle_discount_enabled': bool(promo_setting.is_active and promo_setting.bundle_discount_enabled),
        'bundle_min_jars': int(promo_setting.bundle_min_jars or 2),
        'bundle_discount_amount': float(promo_setting.bundle_discount_amount or 0),
        'bundle_discount_label': promo_setting.get_discount_label() if (promo_setting.is_active and promo_setting.bundle_discount_enabled) else '',
        'bundle_apply_mode': promo_setting.bundle_apply_mode,
        'standard_delivery_fee': float(promo_setting.standard_delivery_fee if promo_setting.standard_delivery_fee is not None else 150),
        'free_delivery_enabled': bool(promo_setting.is_active and promo_setting.free_delivery_enabled),
        'free_delivery_min_jars': int(promo_setting.free_delivery_min_jars or 4),
        'advance_payment_discount_enabled': bool(promo_setting.is_active and promo_setting.advance_payment_discount_enabled),
        'advance_payment_discount_percent': float(promo_setting.advance_payment_discount_percent or 0),
        'advance_payment_discount_label': promo_setting.get_advance_payment_label() if (promo_setting.is_active and promo_setting.advance_payment_discount_enabled) else '',
        'coupons': [
            {
                'code': c.code,
                'discount_type': c.discount_type,
                'discount_value': float(c.discount_value or 0),
                'min_jars': int(c.min_jars or 1),
                'min_subtotal': float(c.min_subtotal or 0),
            }
            for c in active_coupons
        ],
    }

    context = {
        'orders': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'filtered_total_count': paginator.count,
        'total_orders_count': total_orders_count,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'packing_count': packing_count,
        'out_for_delivery_count': out_for_delivery_count,
        'delivered_count': delivered_count,
        'cancelled_count': cancelled_count,
        'trash_count': Order.trash_objects.count(),
        'status_filter': status_filter,
        'period_filter': period_filter,
        'start_date': start_date,
        'end_date': end_date,
        'zone_filter': zone_filter,
        'payment_filter': payment_filter,
        'customer_type': customer_type,
        'search_query': search_query,
        'status_choices': Order.ORDER_STATUS_CHOICES,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'products': Product.objects.all(),
        'promo_setting': promo_setting,
        'manual_coupons': active_coupons,
        'manual_offer_config_json': json.dumps(manual_offer_config),
    }
    return render(request, 'dashboard/orders_list.html', context)


PACKED_ORDER_STATUSES = {'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'}

def adjust_inventory_for_order_status_change(order, old_status, new_status, user=None):
    """
    Packing Inventory Model:
    Stock is deducted when the order is being packed (transitions to PACKING, OUT_FOR_DELIVERY, or DELIVERED).
    Stock is restored if a packed order is cancelled or reverted back to PENDING/CONFIRMED before packing.
    """
    was_packed = old_status in PACKED_ORDER_STATUSES
    now_packed = new_status in PACKED_ORDER_STATUSES

    if not was_packed and now_packed:
        # Deduct physical stock when packing fresh jars into the parcel
        for itm in order.items.all():
            if itm.product:
                prev_stock = itm.product.stock_count
                deduct_qty = itm.quantity
                new_stock = max(0, prev_stock - deduct_qty)
                itm.product.stock_count = new_stock
                itm.product.save(update_fields=['stock_count'])

                StockLog.objects.create(
                    product=itm.product,
                    log_type='ORDER_CONFIRMED',
                    quantity_delta=-deduct_qty,
                    previous_stock=prev_stock,
                    resulting_stock=new_stock,
                    order=order,
                    reference=f"Packed #{order.order_number}",
                    notes=f"Order #{order.order_number} packed into parcel ({old_status} -> {new_status}). Customer: {order.customer_name}",
                    created_by=user if getattr(user, 'is_authenticated', False) else None
                )
    elif was_packed and not now_packed:
        # If this order has an OrderReturn associated, return logic dictates stock
        if hasattr(order, 'returns') and order.returns.exists():
            return

        # Restore physical stock when a packed order is cancelled or reverted back to queue
        for itm in order.items.all():
            if itm.product:
                prev_stock = itm.product.stock_count
                restore_qty = itm.quantity
                new_stock = prev_stock + restore_qty
                itm.product.stock_count = new_stock
                itm.product.save(update_fields=['stock_count'])

                StockLog.objects.create(
                    product=itm.product,
                    log_type='ORDER_CANCELLED',
                    quantity_delta=restore_qty,
                    previous_stock=prev_stock,
                    resulting_stock=new_stock,
                    order=order,
                    reference=f"Reverted #{order.order_number}",
                    notes=f"Order #{order.order_number} cancelled/reverted from packing ({old_status} -> {new_status}). Restored {restore_qty} jars to stock.",
                    created_by=user if getattr(user, 'is_authenticated', False) else None
                )


def sync_parcel_status_with_cache(order, force=False, user=None):
    """
    Auto-updates parcel status from Steadfast or Pathao Courier API with smart caching.
    - Caches for 5 minutes during active transit to avoid API rate limits.
    - Updates courier parcel status (steadfast_order_status / pathao_order_status) only.
    - Does NOT modify store order_status.
    """
    if not (order.steadfast_consignment_id or order.pathao_consignment_id or order.steadfast_tracking_code):
        return None

    cache_key = f"courier_auto_sync_{order.order_number}"
    if not force:
        cached_status = cache.get(cache_key)
        if cached_status:
            return cached_status

    updated_status = None
    try:
        # Sync with appropriate courier
        if order.steadfast_consignment_id or (order.courier_provider == 'STEADFAST' and order.steadfast_tracking_code):
            updated_status = order.sync_steadfast_status()
        elif order.pathao_consignment_id or order.courier_provider == 'PATHAO':
            updated_status = order.sync_pathao_status()

        ttl = 300
        cache.set(cache_key, updated_status or 'SYNCED', timeout=ttl)
    except Exception:
        cache.set(cache_key, 'ERROR_COOLDOWN', timeout=60)

    return updated_status


@user_passes_test(is_staff_user, login_url='dashboard:login')
def order_detail(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), order_number=order_number)
    
    # Auto-update live parcel tracking status with caching
    if order.steadfast_consignment_id or order.pathao_consignment_id or order.steadfast_tracking_code:
        sync_parcel_status_with_cache(order, force=False, user=request.user)
    
    if request.method == 'POST':
        if not can_user_edit(request.user):
            messages.error(request, 'Permission Denied: অর্ডারের বিবরণ বা স্ট্যাটাস এডিট করার অনুমতি নেই। (Only authorized staff/admin can edit orders.)')
            return redirect('dashboard:order_detail', order_number=order.order_number)
        new_status = request.POST.get('order_status')
        new_payment_status = request.POST.get('payment_status')
        admin_notes = request.POST.get('admin_notes')
        
        old_status = order.order_status
        if new_status and new_status != old_status:
            # Adjust inventory based on acceptance / cancellation transition
            adjust_inventory_for_order_status_change(order, old_status, new_status)

            order.order_status = new_status
            # Auto-mark payment as collected/PAID when delivered
            if new_status == 'DELIVERED' and not new_payment_status and order.payment_status == 'UNPAID':
                order.payment_status = 'PAID'

            # Trigger automatic WhatsApp delivery & storage instruction popup when shipping out
            if new_status == 'OUT_FOR_DELIVERY' and order.customer_phone:
                request.session['auto_whatsapp_url'] = order.whatsapp_shipping_instruction_url
                request.session['auto_whatsapp_order_number'] = order.order_number

            # Trigger Meta Conversions API (CAPI) Purchase STRICTLY ONCE when moving to confirmed status
            CONFIRMED_STATUSES = {'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'}
            if new_status in CONFIRMED_STATUSES and old_status not in CONFIRMED_STATUSES:
                try:
                    from store.meta_capi import send_meta_purchase_event_on_accept
                    send_meta_purchase_event_on_accept(order, request=request)
                except Exception as _e:
                    print(f"Failed to dispatch Meta CAPI Purchase: {_e}")

        if new_payment_status:
            order.payment_status = new_payment_status
            
        if request.POST.get('payment_trx_id') is not None:
            order.payment_trx_id = request.POST.get('payment_trx_id', '').strip()
        if request.POST.get('payment_sender_number') is not None:
            order.payment_sender_number = request.POST.get('payment_sender_number', '').strip()
        if request.POST.get('payment_method'):
            order.payment_method = request.POST.get('payment_method')

        # Unified customer & delivery instruction (supports clearing to blank)
        if 'customer_notes' in request.POST or 'admin_notes' in request.POST:
            raw_inst = request.POST.get('customer_notes') if 'customer_notes' in request.POST else request.POST.get('admin_notes', '')
            clean_inst = (raw_inst or '').strip()
            order.customer_notes = clean_inst
            order.admin_notes = clean_inst
            
        order.save()
        messages.success(request, f'Order #{order.order_number} details successfully updated.')
        return redirect('dashboard:order_detail', order_number=order.order_number)

    from store.meta_capi import get_order_meta_sent_status, get_order_meta_details
    meta_sent_info = get_order_meta_sent_status(order.order_number)
    meta_details = get_order_meta_details(order)

    # Attach FIFO active selling batch to order items
    from dashboard.batch_fifo import calculate_all_products_fifo
    products_fifo_map = calculate_all_products_fifo()
    for item in order.items.all():
        if item.product_id:
            p_fifo = products_fifo_map.get(item.product_id, {})
            item.fifo_active_batch = p_fifo.get('active_batch')
            item.fifo_all_sold_out = p_fifo.get('all_sold_out', False)

    return render(request, 'dashboard/order_detail.html', {
        'order': order,
        'meta_sent_info': meta_sent_info,
        'meta_details': meta_details,
    })


@user_passes_test(is_staff_user, login_url='dashboard:login')
def update_order_status_quick(request, order_number):
    if request.method == 'POST':
        if not can_user_edit(request.user):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Permission Denied: অর্ডার স্ট্যাটাস পরিবর্তন করার অনুমতি নেই।'}, status=403)
            messages.error(request, 'Permission Denied: অর্ডার স্ট্যাটাস পরিবর্তন করার অনুমতি নেই। (Status editing restricted.)')
            return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')
        order = get_object_or_404(Order, order_number=order_number)
        new_status = request.POST.get('status')
        old_status = order.order_status
        if new_status in dict(Order.ORDER_STATUS_CHOICES) and new_status != old_status:
            # Adjust inventory based on acceptance / cancellation transition
            adjust_inventory_for_order_status_change(order, old_status, new_status)

            order.order_status = new_status
            # When marked as DELIVERED, automatically mark money as collected (PAID)
            if new_status == 'DELIVERED' and order.payment_status == 'UNPAID':
                order.payment_status = 'PAID'

            # Trigger automatic WhatsApp delivery & storage instruction when shipping out
            if new_status == 'OUT_FOR_DELIVERY' and order.customer_phone:
                request.session['auto_whatsapp_url'] = order.whatsapp_shipping_instruction_url
                request.session['auto_whatsapp_order_number'] = order.order_number

            # Trigger Meta Conversions API (CAPI) Purchase STRICTLY ONCE when moving to confirmed status
            CONFIRMED_STATUSES = {'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'}
            if new_status in CONFIRMED_STATUSES and old_status not in CONFIRMED_STATUSES:
                try:
                    from store.meta_capi import send_meta_purchase_event_on_accept
                    send_meta_purchase_event_on_accept(order, request=request)
                except Exception as _e:
                    print(f"Failed to dispatch Meta CAPI Purchase: {_e}")

            order.save()
            messages.success(request, f'Order #{order.order_number} status changed to {order.get_order_status_display()}')
            
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'new_status': new_status,
                'status_display': order.get_order_status_display(),
                'whatsapp_url': order.whatsapp_shipping_instruction_url if (new_status == 'OUT_FOR_DELIVERY' and order.customer_phone) else '',
                'should_open_whatsapp': (new_status == 'OUT_FOR_DELIVERY' and bool(order.customer_phone))
            })
            
    return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def resend_meta_purchase(request, order_number):
    """Manually dispatch or re-dispatch Meta CAPI & Pixel Purchase event for an order."""
    if not can_user_edit(request.user):
        messages.error(request, 'Permission Denied: মেটা ইভেন্ট পাঠানোর অনুমতি নেই।')
        return redirect('dashboard:order_detail', order_number=order_number)
    order = get_object_or_404(Order, order_number=order_number)
    try:
        from store.meta_capi import send_meta_purchase_event_on_accept
        res = send_meta_purchase_event_on_accept(order, request=request, force=True)
        if res.get('success'):
            messages.success(request, f"🎯 Meta Pixel & CAPI Purchase Event successfully dispatched for Order #{order.order_number} (৳{order.total_amount})!")
        else:
            messages.warning(request, f"Meta Purchase dispatch failed: {res.get('error')}")
    except Exception as e:
        messages.error(request, f"Error sending Meta Purchase: {e}")
    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def edit_order_customer(request, order_number):
    """
    Allows admin to edit customer name, phone, address, city, zone, and recalculate delivery fee.
    """
    order = get_object_or_404(Order, order_number=order_number)
    if request.method == 'POST':
        if not can_user_edit(request.user):
            messages.error(request, 'Permission Denied: কাস্টমার তথ্য বা ঠিকানা এডিট করার অনুমতি নেই। (Customer info editing restricted.)')
            return redirect('dashboard:order_detail', order_number=order.order_number)
        name = request.POST.get('customer_name', '').strip()
        phone = request.POST.get('customer_phone', '').strip()
        address = request.POST.get('delivery_address', '').strip()
        city = request.POST.get('delivery_city', '').strip()
        zone = request.POST.get('delivery_zone', '').strip()
        email = request.POST.get('customer_email', '').strip()
        notes = (request.POST.get('customer_notes') or request.POST.get('admin_notes') or '').strip()
        custom_fee = request.POST.get('delivery_fee', '').strip()
        trx_id = request.POST.get('payment_trx_id')
        sender_number = request.POST.get('payment_sender_number')
        pay_method = request.POST.get('payment_method')
        pay_status = request.POST.get('payment_status')

        if name:
            order.customer_name = name
        if phone:
            order.customer_phone = phone
        if address:
            order.delivery_address = address
        if city:
            order.delivery_city = city
        if email:
            order.customer_email = email
        if notes is not None:
            order.customer_notes = notes
            order.admin_notes = notes
        if trx_id is not None:
            order.payment_trx_id = trx_id.strip()
        if sender_number is not None:
            order.payment_sender_number = sender_number.strip()
        if pay_method:
            order.payment_method = pay_method
        if pay_status:
            order.payment_status = pay_status

        if zone and zone in dict(Order.ZONE_CHOICES):
            order.delivery_zone = zone
            
        if custom_fee:
            try:
                order.delivery_fee = Decimal(str(custom_fee))
            except Exception:
                pass
        elif zone:
            from store.models import calculate_pathao_delivery_fee
            order.delivery_fee = calculate_pathao_delivery_fee(order.total_weight_grams, order.delivery_zone, total_items=order.total_items_count)

        order.total_amount = order.subtotal + order.delivery_fee
        order.save()
        messages.success(request, f"Customer & Payment details updated for Order #{order.order_number}!")

    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def order_invoice(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related('items'), order_number=order_number)
    from dashboard.batch_fifo import calculate_all_products_fifo
    products_fifo_map = calculate_all_products_fifo()
    for item in order.items.all():
        if item.product_id:
            p_fifo = products_fifo_map.get(item.product_id, {})
            item.fifo_active_batch = p_fifo.get('active_batch')
    return render(request, 'dashboard/order_invoice.html', {'order': order})


@user_passes_test(is_staff_user, login_url='dashboard:login')
def dispatch_order_to_pathao(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    fallback_url = request.META.get('HTTP_REFERER') or reverse('dashboard:order_detail', kwargs={'order_number': order_number})
    
    if request.method == 'POST':
        if not can_user_dispatch(request.user):
            messages.error(request, 'Permission Denied: কুরিয়ারে পার্সেল পাঠানোর অনুমতি আপনার আইডিতে নেই। (Courier dispatch permission required.)')
            return redirect(fallback_url)
            
        pathao_service = PathaoCourierService()
        
        if not pathao_service.is_configured():
            messages.warning(request, "Pathao API is not configured. Please add PATHAO_CLIENT_ID, PATHAO_CLIENT_SECRET, PATHAO_USERNAME, PATHAO_PASSWORD, and PATHAO_STORE_ID in your environment or settings.")
            return redirect(fallback_url)
            
        result = pathao_service.create_order(order)
        if result.get('success'):
            messages.success(request, result.get('message', f'Order #{order.order_number} dispatched to Pathao Courier!'))
        else:
            messages.error(request, result.get('message', 'Failed to dispatch to Pathao.'))
            
    return redirect(fallback_url)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def dispatch_order_to_steadfast(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    fallback_url = request.META.get('HTTP_REFERER') or reverse('dashboard:order_detail', kwargs={'order_number': order_number})

    if request.method == 'POST':
        if not can_user_dispatch(request.user):
            messages.error(request, 'Permission Denied: কুরিয়ারে পার্সেল পাঠানোর অনুমতি আপনার আইডিতে নেই। (Courier dispatch permission required.)')
            return redirect(fallback_url)

        steadfast_service = SteadfastCourierService()

        if not steadfast_service.is_configured():
            messages.warning(request, "Steadfast API is not configured. Please add STEADFAST_API_KEY and STEADFAST_SECRET_KEY in your environment or settings.")
            return redirect(fallback_url)

        result = steadfast_service.create_order(order)
        if result.get('success'):
            messages.success(request, result.get('message', f'Order #{order.order_number} dispatched to Steadfast Courier!'))
        else:
            messages.error(request, result.get('message', 'Failed to dispatch to Steadfast.'))

    return redirect(fallback_url)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def sync_all_pathao_orders(request):
    """
    1-Click Bulk Sync: Query Pathao Courier API for active parcels.
    Updates courier tracking status without altering store order status.
    """
    active_orders = Order.objects.filter(
        pathao_consignment_id__isnull=False
    ).exclude(order_status__in=['DELIVERED', 'CANCELLED'])
    synced_count = 0

    for order in active_orders:
        new_status = order.sync_pathao_status()
        if new_status:
            synced_count += 1

    if synced_count > 0:
        messages.success(request, f"Synced {synced_count} active Pathao parcel statuses.")
    else:
        messages.info(request, "No active Pathao orders needed syncing, or Pathao API is not configured.")

    return redirect(request.META.get('HTTP_REFERER') or 'dashboard:orders')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def sync_all_steadfast_orders(request):
    """
    1-Click Bulk Sync: Query Steadfast Courier API for active parcels.
    Updates courier tracking status without altering store order status.
    """
    active_orders = Order.objects.filter(
        Q(steadfast_consignment_id__isnull=False) | Q(steadfast_tracking_code__isnull=False)
    ).exclude(order_status__in=['DELIVERED', 'CANCELLED'])
    synced_count = 0

    for order in active_orders:
        new_status = order.sync_steadfast_status()
        if new_status:
            synced_count += 1

    if synced_count > 0:
        messages.success(request, f"Synced {synced_count} active Steadfast parcel statuses.")
    else:
        messages.info(request, "No active Steadfast orders needed syncing, or Steadfast API is not configured.")

    return redirect(request.META.get('HTTP_REFERER') or 'dashboard:orders')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def sync_all_courier_orders(request):
    """
    Unified 1-Click Sync for all active orders across both Pathao and Steadfast couriers.
    Updates courier tracking status without altering store order status.
    """
    active_orders = Order.objects.filter(
        Q(pathao_consignment_id__isnull=False) | Q(steadfast_consignment_id__isnull=False) | Q(steadfast_tracking_code__isnull=False)
    ).exclude(order_status__in=['DELIVERED', 'CANCELLED'])
    synced_count = 0

    for order in active_orders:
        new_status = order.sync_courier_status()
        if new_status:
            synced_count += 1

    if synced_count > 0:
        messages.success(request, f"Synced {synced_count} active courier parcel statuses (Pathao & Steadfast).")
    else:
        messages.info(request, "No active courier orders needed syncing, or courier APIs are not configured.")

    return redirect(request.META.get('HTTP_REFERER') or 'dashboard:orders')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def sync_single_pathao_order(request, order_number):
    """
    1-Click Single Order Sync with Pathao Courier API.
    """
    order = get_object_or_404(Order, order_number=order_number)
    if not order.pathao_consignment_id:
        messages.warning(request, f"Order #{order.order_number} has not been dispatched to Pathao yet.")
    else:
        cache.delete(f"courier_auto_sync_{order.order_number}")
        status = order.sync_pathao_status()
        if status:
            messages.success(request, f"Pathao status updated: {order.pathao_order_status}")
            cache.set(f"courier_auto_sync_{order.order_number}", status, timeout=300)
        else:
            messages.info(request, "Could not fetch updated status from Pathao Courier API or no new status update.")
            
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def sync_single_steadfast_order(request, order_number):
    """
    1-Click Single Order Sync with Steadfast Courier API.
    """
    order = get_object_or_404(Order, order_number=order_number)
    if not order.steadfast_consignment_id and not order.steadfast_tracking_code:
        messages.warning(request, f"Order #{order.order_number} has not been dispatched to Steadfast yet.")
    else:
        cache.delete(f"courier_auto_sync_{order.order_number}")
        status = order.sync_steadfast_status()
        if status:
            messages.success(request, f"Steadfast status updated: {order.steadfast_order_status}")
            cache.set(f"courier_auto_sync_{order.order_number}", status, timeout=300)
        else:
            messages.info(request, "Could not fetch updated status from Steadfast Courier API or no new status update.")

    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def create_manual_order(request):
    if request.method == 'POST':
        if not can_user_edit(request.user):
            messages.error(request, 'Permission Denied: আপনার আইডিতে শুধুমাত্র দেখার অনুমতি (View-Only) রয়েছে। ম্যানুয়াল অর্ডার তৈরি করার অনুমতি নেই।')
            return redirect('dashboard:orders')
        try:
            customer_name = request.POST.get('customer_name', '').strip()
            customer_phone = request.POST.get('customer_phone', '').strip()
            delivery_address = request.POST.get('delivery_address', '').strip()
            delivery_city = request.POST.get('delivery_city', 'Dhaka').strip() or 'Dhaka'
            delivery_zone = request.POST.get('delivery_zone', 'INSIDE_DHAKA')
            if delivery_zone not in dict(Order.ZONE_CHOICES):
                delivery_zone = 'INSIDE_DHAKA'
            payment_method = request.POST.get('payment_method', 'COD')
            payment_status = request.POST.get('payment_status', 'UNPAID')
            payment_trx_id = request.POST.get('payment_trx_id', '').strip()
            instruction = (request.POST.get('delivery_instruction') or request.POST.get('customer_notes') or request.POST.get('admin_notes') or '').strip()
            customer_notes = instruction
            admin_notes = instruction

            # Retrieve multiple products and quantities
            product_ids = request.POST.getlist('product_id') or request.POST.getlist('product_id[]')
            quantities = request.POST.getlist('quantity') or request.POST.getlist('quantity[]')

            # Fallback for single product form submissions
            if not product_ids:
                single_pid = request.POST.get('product_id')
                if single_pid:
                    product_ids = [single_pid]
                    quantities = [request.POST.get('quantity', 1)]

            # Group items by product_id (in case the same product is added multiple times)
            items_dict = {}  # {product_id: total_quantity}
            for idx, pid in enumerate(product_ids):
                if not pid:
                    continue
                try:
                    p_id = int(pid)
                    qty = int(quantities[idx]) if idx < len(quantities) else 1
                    qty = max(1, qty)
                    items_dict[p_id] = items_dict.get(p_id, 0) + qty
                except (ValueError, TypeError):
                    continue

            if not items_dict:
                messages.error(request, 'Please select at least one product.')
                return redirect('dashboard:orders')

            # Fetch product objects and calculate subtotal
            valid_items = []
            subtotal = Decimal('0.00')
            for p_id, qty in items_dict.items():
                product = Product.objects.filter(id=p_id).first()
                if product:
                    line_price = product.price_bdt * qty
                    subtotal += line_price
                    valid_items.append({
                        'product': product,
                        'quantity': qty,
                        'unit_price': product.price_bdt,
                        'total_price': line_price,
                        'jar_weight_grams': product.jar_weight_grams or 600,
                        'gross_weight_grams': getattr(product, 'gross_weight_grams', 850) or 850
                    })

            if not valid_items:
                messages.error(request, 'None of the selected products were found in the database.')
                return redirect('dashboard:orders')

            # Delivery Fee based on Pathao gross weight calculation (850g per jar)
            total_items_count = sum(itm['quantity'] for itm in valid_items)
            total_gross_weight_grams = sum((itm.get('gross_weight_grams', 850) or 850) * itm['quantity'] for itm in valid_items)
            default_fee = calculate_pathao_delivery_fee(total_gross_weight_grams, delivery_zone, total_items=total_items_count)
            delivery_fee_str = request.POST.get('delivery_fee', '').strip()
            try:
                delivery_fee = Decimal(delivery_fee_str) if delivery_fee_str else default_fee
                if delivery_fee < 0:
                    delivery_fee = Decimal('0.00')
            except Exception:
                delivery_fee = default_fee

            promo = PromotionSetting.get_settings()
            if request.POST.get('apply_offers_present') == '1':
                apply_offers = (request.POST.get('apply_offers') == '1')
            else:
                apply_offers = True

            bundle_discount = promo.calculate_discount(total_items_count, subtotal) if apply_offers else Decimal('0.00')

            raw_coupon_code = (request.POST.get('coupon_code') or '').strip().upper()
            applied_coupon = None
            coupon_discount = Decimal('0.00')
            if raw_coupon_code:
                coupon_obj = Coupon.objects.filter(code__iexact=raw_coupon_code).first()
                if not coupon_obj:
                    messages.error(request, f"Invalid coupon code '{raw_coupon_code}'. Please check and try again.")
                    return redirect('dashboard:orders')
                c_disc, c_err = coupon_obj.calculate_discount(subtotal, total_items_count)
                if c_err:
                    messages.error(request, f"Coupon '{coupon_obj.code}': {c_err}")
                    return redirect('dashboard:orders')
                applied_coupon = coupon_obj
                coupon_discount = c_disc

            advance_discount = promo.calculate_advance_payment_discount(subtotal, payment_method) if apply_offers else Decimal('0.00')

            discount_amount = min(subtotal, bundle_discount + coupon_discount + advance_discount)
            total_amount = max(Decimal('0.00'), subtotal - discount_amount + delivery_fee)

            order = Order.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                delivery_address=delivery_address,
                delivery_city=delivery_city,
                delivery_zone=delivery_zone,
                delivery_fee=delivery_fee,
                subtotal=subtotal,
                discount_amount=discount_amount,
                coupon_code=applied_coupon.code if applied_coupon else None,
                total_amount=total_amount,
                payment_method=payment_method,
                payment_status=payment_status,
                payment_trx_id=payment_trx_id,
                order_status='CONFIRMED',
                customer_notes=customer_notes,
                admin_notes=admin_notes
            )

            if applied_coupon:
                applied_coupon.used_count += 1
                applied_coupon.save(update_fields=['used_count'])

            # Create OrderItems (Stock is deducted upon physical dispatch/delivery)
            for itm in valid_items:
                prod = itm['product']
                qty = itm['quantity']
                OrderItem.objects.create(
                    order=order,
                    product=prod,
                    product_name=prod.name,
                    jar_weight_grams=itm['jar_weight_grams'],
                    gross_weight_grams=itm.get('gross_weight_grams', 850),
                    unit_price=itm['unit_price'],
                    quantity=qty,
                    total_price=itm['total_price']
                )

            total_jars = sum(itm['quantity'] for itm in valid_items)
            messages.success(
                request,
                f'Manual Order #{order.order_number} for {customer_name} ({total_jars} jar(s)) created successfully!'
            )
            return redirect('dashboard:order_detail', order_number=order.order_number)
        except Exception as e:
            messages.error(request, f'Failed to create manual order: {str(e)}')

    return redirect('dashboard:orders')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def delete_order(request, order_number):
    if not can_user_delete(request.user):
        messages.error(request, 'Permission Denied: Admin ছাড়া কেউ কোনো অর্ডার ডিলিট করতে পারবেন না। (Order deletion restricted to Administrator.)')
        return redirect('dashboard:orders')

    if request.method == 'POST':
        order = get_object_or_404(Order, order_number=order_number)
        o_num = order.order_number
        order.soft_delete()
        messages.success(request, f'Order #{o_num} moved to Trash. You can restore it anytime from the Trash tab.')
        return redirect('dashboard:orders')
    return redirect('dashboard:order_detail', order_number=order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def orders_trash(request):
    if not can_user_delete(request.user):
        messages.error(request, 'Permission Denied: Admin ছাড়া ট্র্যাশ আর্কাইভে এক্সেস নিষিদ্ধ। (Trash archive access restricted to Administrator.)')
        return redirect('dashboard:orders')

    trash_orders = Order.trash_objects.all().prefetch_related('items').order_by('-deleted_at')
    trash_count = trash_orders.count()
    search_query = request.GET.get('q', '').strip()

    if search_query:
        import re
        clean_search = search_query.lstrip('#').strip()
        num_match = re.search(r'(\d+)', clean_search)
        
        s_filter = (
            Q(order_number__icontains=search_query) |
            Q(order_number__icontains=clean_search) |
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(delivery_city__icontains=search_query) |
            Q(payment_trx_id__icontains=search_query)
        )
        if num_match:
            try:
                num_val = int(num_match.group(1))
                s_filter |= Q(order_number__iexact=f"PKP-{num_val:05d}")
                s_filter |= Q(order_number__iexact=f"PKP-{num_val:04d}")
            except Exception:
                pass
        trash_orders = trash_orders.filter(s_filter)

    context = {
        'orders': trash_orders[:200],
        'trash_count': trash_count,
        'search_query': search_query,
    }
    return render(request, 'dashboard/orders_trash.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def restore_order(request, order_number):
    if not can_user_delete(request.user):
        messages.error(request, 'Permission Denied: Admin ছাড়া কেউ অর্ডার রিস্টোর করতে পারবেন না।')
        return redirect('dashboard:orders')

    if request.method == 'POST':
        order = get_object_or_404(Order.trash_objects, order_number=order_number)
        order.restore()
        messages.success(request, f'Order #{order.order_number} for {order.customer_name} has been successfully restored!')
        return redirect('dashboard:orders_trash')
    return redirect('dashboard:orders_trash')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def permanent_delete_order(request, order_number):
    if not can_user_delete(request.user):
        messages.error(request, 'Permission Denied: Admin ছাড়া স্থায়ীভাবে ডিলিট করার অনুমতি নেই। (Permanent deletion restricted to Administrator.)')
        return redirect('dashboard:orders_trash')

    if request.method == 'POST':
        order = get_object_or_404(Order.trash_objects, order_number=order_number)
        o_num = order.order_number
        if order.order_status in PACKED_ORDER_STATUSES:
            for itm in order.items.all():
                if itm.product:
                    itm.product.stock_count += itm.quantity
                    itm.product.is_in_stock = True
                    itm.product.save()
        order.delete()
        messages.success(request, f'Order #{o_num} has been permanently deleted from the database.')
        return redirect('dashboard:orders_trash')
    return redirect('dashboard:orders_trash')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def stock_manager(request):
    selected_cat = request.GET.get('category')
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'ALL')

    all_products = Product.objects.all().select_related('category').order_by('name')
    categories = Category.objects.annotate(product_count=Count('products')).order_by('name')
    
    products = all_products
    if selected_cat:
        products = products.filter(category__slug=selected_cat)

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(tagline__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(ingredients__icontains=search_query)
        )

    if status_filter == 'IN_STOCK':
        products = products.filter(is_in_stock=True, stock_count__gt=0)
    elif status_filter == 'OUT_OF_STOCK':
        products = products.filter(Q(is_in_stock=False) | Q(stock_count=0))
    elif status_filter == 'SHORTAGE':
        # Products with active demand exceeding physical stock
        prod_ids_shortage = [p.id for p in products if p.is_low_stock]
        products = products.filter(id__in=prod_ids_shortage)

    if request.method == 'POST':
        action = request.POST.get('action')
        product_id = request.POST.get('product_id')

        # 1. DELETE PRODUCT
        if action == 'delete_product' or 'delete_product' in request.POST:
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ প্রোডাক্ট ডিলিট করতে পারবেন না। (Only Administrator can delete products.)')
                return redirect('dashboard:stock_manager')
            product = get_object_or_404(Product, id=product_id)
            prod_name = product.name
            product.delete()
            messages.success(request, f'Pickle product "{prod_name}" has been permanently deleted.')
            return redirect('dashboard:stock_manager')

        # 2. FULL EDIT PRODUCT
        elif action == 'edit_product' or 'edit_product' in request.POST:
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: প্রোডাক্ট তথ্য এডিট করার অনুমতি নেই। (Product editing restricted.)')
                return redirect('dashboard:stock_manager')
            product = get_object_or_404(Product, id=product_id)
            try:
                name_val = request.POST.get('name')
                if name_val:
                    product.name = name_val.strip()
                
                product.tagline = request.POST.get('tagline', '').strip()
                product.description = request.POST.get('description', '').strip()
                
                cat_id = request.POST.get('category_id')
                if cat_id and str(cat_id).strip():
                    product.category = Category.objects.filter(id=cat_id).first()
                else:
                    product.category = None
                    
                product.cut_style = request.POST.get('cut_style') or product.cut_style or 'CHIPS'
                product.spice_level = request.POST.get('spice_level') or product.spice_level or 'MILD'
                
                crunch_val = request.POST.get('crunch_rating')
                product.crunch_rating = int(crunch_val) if crunch_val and str(crunch_val).isdigit() else (product.crunch_rating or 5)
                
                jar_w_val = request.POST.get('jar_weight_grams')
                product.jar_weight_grams = int(jar_w_val) if jar_w_val and str(jar_w_val).isdigit() else (product.jar_weight_grams or 600)
                
                gross_w_val = request.POST.get('gross_weight_grams')
                product.gross_weight_grams = int(gross_w_val) if gross_w_val and str(gross_w_val).isdigit() else getattr(product, 'gross_weight_grams', 850) or 850
                
                price_val = request.POST.get('price_bdt')
                if price_val and str(price_val).strip():
                    product.price_bdt = Decimal(str(price_val).strip())
                
                orig_price_val = request.POST.get('original_price_bdt')
                if orig_price_val and str(orig_price_val).strip():
                    product.original_price_bdt = Decimal(str(orig_price_val).strip())
                else:
                    product.original_price_bdt = None

                price_reason = request.POST.get('price_change_reason', '').strip()
                if price_reason:
                    product._price_change_reason = price_reason
                product._price_changed_by = request.user if request.user.is_authenticated else None
                
                stock_val = request.POST.get('stock_count')
                if stock_val is not None and str(stock_val).strip() != '':
                    product.stock_count = max(0, int(stock_val))
                    
                min_stock_val = request.POST.get('min_stock_threshold')
                product.min_stock_threshold = int(min_stock_val) if min_stock_val and str(min_stock_val).isdigit() else getattr(product, 'min_stock_threshold', 15) or 15
                
                target_stock_val = request.POST.get('target_stock_level')
                product.target_stock_level = int(target_stock_val) if target_stock_val and str(target_stock_val).isdigit() else getattr(product, 'target_stock_level', 50) or 50
                
                product.is_in_stock = request.POST.get('is_in_stock') in ['on', 'true', '1', True]
                product.is_featured = request.POST.get('is_featured') in ['on', 'true', '1', True]
                custom_badge_val = request.POST.get('custom_badge')
                if custom_badge_val is not None:
                    product.custom_badge = custom_badge_val.strip()
                
                if 'image' in request.FILES and request.FILES['image']:
                    product.image = request.FILES['image']
                    if product.image and hasattr(product.image, 'name') and product.image.name:
                        clean_name = product.image.name.lstrip('/\\').replace('\\', '/')
                        product.image_url = f"/media/{clean_name}"
                else:
                    image_url = request.POST.get('image_url')
                    if image_url is not None:
                        clean_url = image_url.strip()
                        if clean_url and not clean_url.endswith('pickle_default.png'):
                            product.image_url = clean_url
                        elif product.image and product.image.name:
                            clean_name = product.image.name.lstrip('/\\').replace('\\', '/')
                            product.image_url = f"/media/{clean_name}"

                product.ingredients = request.POST.get('ingredients', '').strip() or product.ingredients
                product.flavor_profile = request.POST.get('flavor_profile', '').strip() or product.flavor_profile
                product.pairing_suggestions = request.POST.get('pairing_suggestions', '').strip() or product.pairing_suggestions
                shelf_life_val = request.POST.get('shelf_life')
                if shelf_life_val is not None:
                    product.shelf_life = shelf_life_val.strip()

                product.save()

                # Robust audit sync: ensure latest PriceHistory matches current price
                last_ph = PriceHistory.objects.filter(product=product).order_by('-created_at', '-id').first()
                if last_ph and last_ph.new_price != product.price_bdt:
                    PriceHistory.objects.create(
                        product=product,
                        old_price=last_ph.new_price,
                        new_price=product.price_bdt,
                        old_original_price=product.original_price_bdt,
                        new_original_price=product.original_price_bdt,
                        change_type='INCREASE' if product.price_bdt > last_ph.new_price else 'DECREASE',
                        reason=price_reason or 'Price revised in Inventory',
                        notes='Synchronized with current active catalog price',
                        changed_by=request.user if request.user.is_authenticated else None
                    )

                messages.success(request, f'Product "{product.name}" has been successfully updated.')
            except Exception as e:
                messages.error(request, f'Failed to update product: {str(e)}')
            return redirect('dashboard:stock_manager')

        # 3. CREATE NEW PRODUCT
        elif action == 'create_product' or 'create_product' in request.POST:
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: নতুন প্রোডাক্ট যুক্ত করার অনুমতি নেই। (Product creation restricted.)')
                return redirect('dashboard:stock_manager')
            try:
                name = request.POST.get('name', '').strip()
                tagline = request.POST.get('tagline', '').strip()
                description = request.POST.get('description', '').strip()
                cat_id = request.POST.get('category_id')
                category = Category.objects.filter(id=cat_id).first() if (cat_id and str(cat_id).strip()) else None
                cut_style = request.POST.get('cut_style', 'SPEARS')
                spice_level = request.POST.get('spice_level', 'MILD')
                
                crunch_val = request.POST.get('crunch_rating')
                crunch_rating = int(crunch_val) if crunch_val and str(crunch_val).isdigit() else 5
                
                jar_w_val = request.POST.get('jar_weight_grams')
                jar_weight_grams = int(jar_w_val) if jar_w_val and str(jar_w_val).isdigit() else 600
                
                gross_w_val = request.POST.get('gross_weight_grams')
                gross_weight_grams = int(gross_w_val) if gross_w_val and str(gross_w_val).isdigit() else 850
                
                price_val = request.POST.get('price_bdt')
                price_bdt = float(price_val) if price_val and str(price_val).strip() else 380.0
                
                orig_price = request.POST.get('original_price_bdt')
                original_price_bdt = float(orig_price) if orig_price and str(orig_price).strip() else None
                
                stock_val = request.POST.get('stock_count')
                stock_count = max(0, int(stock_val)) if stock_val is not None and str(stock_val).strip() != '' else 50
                
                min_stock_val = request.POST.get('min_stock_threshold')
                min_stock_threshold = int(min_stock_val) if min_stock_val and str(min_stock_val).isdigit() else 15
                
                target_stock_val = request.POST.get('target_stock_level')
                target_stock_level = int(target_stock_val) if target_stock_val and str(target_stock_val).isdigit() else 50
                
                is_in_stock = request.POST.get('is_in_stock') in ['on', 'true', '1', True]
                is_featured = request.POST.get('is_featured') in ['on', 'true', '1', True]
                
                custom_badge = request.POST.get('custom_badge', '').strip()
                image_url = request.POST.get('image_url', '').strip()
                ingredients = request.POST.get('ingredients', '').strip()
                flavor_profile = request.POST.get('flavor_profile', '').strip()
                pairing_suggestions = request.POST.get('pairing_suggestions', '').strip()
                shelf_life = request.POST.get('shelf_life', '').strip()

                new_prod = Product.objects.create(
                    name=name,
                    tagline=tagline or f"Handcrafted {name}",
                    description=description or f"Crisp, delicious handcrafted {name}.",
                    category=category,
                    cut_style=cut_style,
                    spice_level=spice_level,
                    crunch_rating=crunch_rating,
                    jar_weight_grams=jar_weight_grams,
                    gross_weight_grams=gross_weight_grams,
                    price_bdt=price_bdt,
                    original_price_bdt=original_price_bdt,
                    stock_count=stock_count,
                    min_stock_threshold=min_stock_threshold,
                    target_stock_level=target_stock_level,
                    is_in_stock=is_in_stock,
                    is_featured=is_featured,
                    custom_badge=custom_badge,
                    image_url=image_url if (image_url and not image_url.endswith('pickle_default.png')) else '',
                    ingredients=ingredients or "Fresh Local Cucumbers, Pure Cane Vinegar, Himalayan Pink Salt, Garlic, Spices.",
                    flavor_profile=flavor_profile or "Crisp, Tangy, Garlic & Whole Spices",
                    pairing_suggestions=pairing_suggestions or "Burgers, Sandwiches, Snacks",
                    shelf_life=shelf_life or "Always keep refrigerated for maximum crunch. Best enjoyed within 2 months."
                )
                if 'image' in request.FILES and request.FILES['image']:
                    new_prod.image = request.FILES['image']
                    new_prod.save()
                    if new_prod.image and new_prod.image.name:
                        clean_name = new_prod.image.name.lstrip('/\\').replace('\\', '/')
                        new_prod.image_url = f"/media/{clean_name}"
                        new_prod.save(update_fields=['image_url'])
                elif not new_prod.image_url:
                    new_prod.image_url = f"/media/products/{new_prod.slug.replace('-', '_')}.webp"
                    new_prod.save(update_fields=['image_url'])

                messages.success(request, f'New pickle jar "{new_prod.name}" successfully added to catalog!')
            except Exception as e:
                messages.error(request, f'Failed to create product: {str(e)}')
            return redirect('dashboard:stock_manager')

        # 4. TOGGLE IN-STOCK STATUS
        elif 'toggle_stock' in request.POST or action == 'toggle_stock':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: স্টক পরিবর্তনের অনুমতি নেই। (Stock modification restricted.)')
                return redirect('dashboard:stock_manager')
            product = get_object_or_404(Product, id=product_id)
            product.is_in_stock = not product.is_in_stock
            product.save()
            messages.success(request, f'Updated stock availability for "{product.name}".')
            return redirect('dashboard:stock_manager')

        # 5. QUICK PRICE & STOCK UPDATE
        elif 'update_pricing' in request.POST or action == 'update_pricing':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: মূল্য বা স্টক পরিবর্তনের অনুমতি নেই। (Pricing/stock editing restricted.)')
                return redirect('dashboard:stock_manager')
            product = get_object_or_404(Product, id=product_id)
            try:
                new_price = request.POST.get('price_bdt')
                new_stock_str = request.POST.get('stock_count')
                new_target_str = request.POST.get('target_stock_level')
                new_min_str = request.POST.get('min_stock_threshold')
                note = request.POST.get('stock_note', '').strip()
                if new_price and str(new_price).strip():
                    product.price_bdt = Decimal(str(new_price).strip())
                if new_target_str:
                    product.target_stock_level = int(new_target_str)
                if new_min_str:
                    product.min_stock_threshold = int(new_min_str)
                if new_stock_str is not None and new_stock_str != '':
                    new_stock = int(new_stock_str)
                    prev_stock = product.stock_count
                    delta = new_stock - prev_stock
                    product.stock_count = new_stock
                    
                    if delta != 0:
                        StockLog.objects.create(
                            product=product,
                            log_type='RESTOCK' if delta > 0 else 'MANUAL_ADJUSTMENT',
                            quantity_delta=delta,
                            previous_stock=prev_stock,
                            resulting_stock=new_stock,
                            reference='Manual Stock Adjustment' if not note else note,
                            notes=note or f"Stock count updated from {prev_stock} to {new_stock}",
                            created_by=request.user if request.user.is_authenticated else None
                        )
                price_reason = request.POST.get('price_change_reason', '').strip() or note
                if price_reason:
                    product._price_change_reason = price_reason
                product._price_changed_by = request.user if request.user.is_authenticated else None
                product.save()

                # Robust audit sync: ensure latest PriceHistory record matches product.price_bdt
                last_ph = PriceHistory.objects.filter(product=product).order_by('-created_at', '-id').first()
                if last_ph and last_ph.new_price != product.price_bdt:
                    PriceHistory.objects.create(
                        product=product,
                        old_price=last_ph.new_price,
                        new_price=product.price_bdt,
                        old_original_price=product.original_price_bdt,
                        new_original_price=product.original_price_bdt,
                        change_type='INCREASE' if product.price_bdt > last_ph.new_price else 'DECREASE',
                        reason=price_reason or 'Price revised in Inventory',
                        notes='Synchronized with current active catalog price',
                        changed_by=request.user if request.user.is_authenticated else None
                    )

                messages.success(request, f'Updated price & inventory for "{product.name}".')
            except (ValueError, TypeError) as e:
                messages.error(request, 'Invalid price or stock count format.')
            return redirect('dashboard:stock_manager')

        # 5B. MULTI-ITEM PRODUCTION BATCH & RESTOCK ADD
        elif action in ['restock_batch', 'multi_item_batch'] or 'restock_batch' in request.POST or 'multi_item_batch' in request.POST:
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: নতুন প্রোডাকশন ব্যাচ বা স্টক যোগ করার অনুমতি নেই। (Stock modification restricted.)')
                return redirect('dashboard:stock_manager')
            batch_ref = request.POST.get('batch_reference', '').strip() or 'Production Batch'
            notes = request.POST.get('notes', '').strip()
            prod_date_str = request.POST.get('production_date', '').strip()
            prod_date_obj = None
            if prod_date_str:
                try:
                    prod_date_obj = datetime.datetime.strptime(prod_date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

            items_to_add = []

            # 1. Check array format product_ids[] / quantities[]
            prod_ids = request.POST.getlist('product_ids[]') or request.POST.getlist('product_id')
            qtys = request.POST.getlist('quantities[]') or request.POST.getlist('quantity')
            if prod_ids and qtys and len(prod_ids) == len(qtys):
                for p_id, q_val in zip(prod_ids, qtys):
                    try:
                        q_int = int(q_val)
                        if q_int > 0:
                            items_to_add.append((int(p_id), q_int))
                    except (ValueError, TypeError):
                        pass

            # 2. Check dynamic batch_qty_<id> fields
            for key, val in request.POST.items():
                if key.startswith('batch_qty_') and val:
                    try:
                        p_id = int(key.replace('batch_qty_', ''))
                        q_int = int(val)
                        if q_int > 0 and (p_id, q_int) not in items_to_add:
                            items_to_add.append((p_id, q_int))
                    except (ValueError, TypeError):
                        pass

            # 3. Fallback: single product_id and quantity
            if not items_to_add and product_id:
                try:
                    q_int = int(request.POST.get('quantity', 0))
                    if q_int > 0:
                        items_to_add.append((int(product_id), q_int))
                except (ValueError, TypeError):
                    pass

            if not items_to_add:
                messages.error(request, 'Please enter a valid production quantity (at least 1 jar) for one or more pickle items.')
                return redirect('dashboard:stock_manager')

            # Create ProductionBatch record
            p_batch = ProductionBatch.objects.create(
                batch_number=batch_ref,
                production_date=prod_date_obj or today,
                notes=notes,
                created_by=request.user if request.user.is_authenticated else None
            )

            total_added_jars = 0
            updated_product_names = []

            for p_id, add_qty in items_to_add:
                prod = Product.objects.filter(id=p_id).first()
                if prod:
                    prev_stock = prod.stock_count
                    new_stock = prev_stock + add_qty
                    prod.stock_count = new_stock
                    prod.is_in_stock = True
                    prod.save(update_fields=['stock_count', 'is_in_stock'])

                    # Create BatchItem record
                    BatchItem.objects.create(
                        batch=p_batch,
                        product=prod,
                        quantity=add_qty,
                        notes=f"{prod.name}: +{add_qty} jars"
                    )

                    log = StockLog.objects.create(
                        product=prod,
                        log_type='RESTOCK',
                        quantity_delta=add_qty,
                        previous_stock=prev_stock,
                        resulting_stock=new_stock,
                        reference=batch_ref,
                        notes=notes or f"Batch Production ({batch_ref}): +{add_qty} jars",
                        created_by=request.user if request.user.is_authenticated else None
                    )
                    if prod_date_obj:
                        prod_datetime = timezone.make_aware(datetime.datetime.combine(prod_date_obj, timezone.now().time())) if timezone.is_naive(datetime.datetime.combine(prod_date_obj, timezone.now().time())) else datetime.datetime.combine(prod_date_obj, timezone.now().time())
                        StockLog.objects.filter(id=log.id).update(created_at=prod_datetime)

                    total_added_jars += add_qty
                    updated_product_names.append(f"{prod.name} (+{add_qty})")

            date_display = f" on {prod_date_obj.strftime('%b %d, %Y')}" if prod_date_obj else ""
            messages.success(
                request,
                f'🎉 Production Batch "{batch_ref}"{date_display} successfully saved! Total +{total_added_jars} jars added across {len(updated_product_names)} pickle flavor(s).'
            )
            return redirect('dashboard:stock_manager')

        # 5C. QUICK STEPPER (+1 / -1 jars)
        elif action == 'quick_step_stock':
            if not can_user_edit(request.user):
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Permission Denied: স্টক পরিবর্তনের অনুমতি নেই।'}, status=403)
                messages.error(request, 'Permission Denied: স্টক পরিবর্তনের অনুমতি নেই। (Stock modification restricted.)')
                return redirect(request.META.get('HTTP_REFERER') or 'dashboard:stock_manager')
            product = get_object_or_404(Product, id=product_id)
            try:
                delta = int(request.POST.get('delta', 1))
                prev_stock = product.stock_count
                new_stock = max(0, prev_stock + delta)
                product.stock_count = new_stock
                product.save(update_fields=['stock_count'])

                StockLog.objects.create(
                    product=product,
                    log_type='RESTOCK' if delta > 0 else 'MANUAL_ADJUSTMENT',
                    quantity_delta=delta,
                    previous_stock=prev_stock,
                    resulting_stock=new_stock,
                    reference='Quick Stepper',
                    notes=f"Quick stock adjusted by {delta:+d} jar(s)",
                    created_by=request.user if request.user.is_authenticated else None
                )

                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'product_id': product.id,
                        'new_stock': new_stock,
                        'needed_stock': product.needed_stock,
                        'ordered_demand_count': product.ordered_demand_count,
                        'is_low_stock': product.is_low_stock,
                        'is_critical_stock': product.is_critical_stock
                    })
                messages.success(request, f'Updated stock for "{product.name}" to {new_stock} jars.')
            except Exception as e:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': str(e)}, status=400)
                messages.error(request, f'Failed to update stock: {str(e)}')
            return redirect(request.META.get('HTTP_REFERER') or 'dashboard:stock_manager')

        # 6. CREATE CATEGORY
        elif action == 'create_category' or 'create_category' in request.POST:
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: নতুন ক্যাটাগরি তৈরি করার অনুমতি নেই। (Category creation restricted.)')
                return redirect('dashboard:stock_manager')
            cat_name = request.POST.get('category_name', '').strip()
            cat_desc = request.POST.get('category_description', '').strip()
            cat_icon = request.POST.get('category_icon', 'fa-jar').strip()
            if cat_name:
                Category.objects.create(name=cat_name, description=cat_desc, icon=cat_icon)
                messages.success(request, f'New category "{cat_name}" created successfully!')
            else:
                messages.error(request, 'Category name cannot be empty.')
            return redirect('dashboard:stock_manager')

        # 7. DELETE CATEGORY
        elif action == 'delete_category' or 'delete_category' in request.POST:
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ ক্যাটাগরি ডিলিট করতে পারবেন না। (Only Administrator can delete categories.)')
                return redirect('dashboard:stock_manager')
            cat_id = request.POST.get('category_id')
            cat = get_object_or_404(Category, id=cat_id)
            c_name = cat.name
            cat.delete()
            messages.success(request, f'Category "{c_name}" deleted successfully.')
            return redirect('dashboard:stock_manager')

    # Calculate Low Stock & Production Needs Metrics
    low_stock_products = [p for p in all_products if p.is_low_stock]
    low_stock_count = len(low_stock_products)
    critical_stock_count = sum(1 for p in low_stock_products if p.is_critical_stock)
    total_needed_jars = sum(p.needed_stock for p in all_products)
    total_current_inventory = sum(p.stock_count for p in all_products)
    total_target_inventory = sum(p.target_stock_level for p in all_products)
    total_inventory_value = sum((p.stock_count or 0) * (p.price_bdt or 0) for p in all_products)

    # Suggest next batch reference number
    last_batch_log = StockLog.objects.filter(reference__icontains='Batch').order_by('-id').first()
    next_batch_num = 1
    if last_batch_log and last_batch_log.reference:
        import re
        m = re.search(r'Batch\s*#?\s*(\d+)', last_batch_log.reference, re.IGNORECASE)
        if m:
            try:
                next_batch_num = int(m.group(1)) + 1
            except Exception:
                pass
    suggested_batch_ref = f"Batch #{next_batch_num}"

    # Map comprehensive price history analytics for products (আগে কত ছিল, এখন কত আছে, কয়বার বাড়ছে)
    all_price_histories = list(PriceHistory.objects.select_related('changed_by').order_by('created_at', 'id'))
    ph_by_product = {}
    for ph in all_price_histories:
        ph_by_product.setdefault(ph.product_id, []).append(ph)

    for p in products:
        p_history = ph_by_product.get(p.id, [])
        first_rec = p_history[0] if p_history else None
        p.first_price = first_rec.old_price if first_rec else p.price_bdt

        inc_records = [ph for ph in p_history if ph.change_type == 'INCREASE']
        dec_records = [ph for ph in p_history if ph.change_type == 'DECREASE']
        p.increase_count = len(inc_records)
        p.decrease_count = len(dec_records)
        p.total_increase_bdt = max(Decimal('0'), Decimal(str(p.price_bdt)) - Decimal(str(p.first_price)))

        change_records = [ph for ph in p_history if ph.change_type in ['INCREASE', 'DECREASE']]
        if change_records:
            p.latest_price_change = change_records[-1]
            p.prev_price = p.latest_price_change.old_price
        else:
            p.latest_price_change = None
            p.prev_price = p.first_price

    recent_price_logs = PriceHistory.objects.select_related('product', 'changed_by').all().order_by('-created_at')[:6]

    # Map FIFO Batch selling recommendations for each product
    from dashboard.batch_fifo import calculate_all_products_fifo, get_active_selling_recommendations, calculate_all_batches_fifo
    products_fifo_map = calculate_all_products_fifo()
    active_selling_batches = get_active_selling_recommendations()
    all_batches_fifo_map = calculate_all_batches_fifo()

    # Pre-fetch recent production batches for inventory top view
    all_production_batches = list(ProductionBatch.objects.prefetch_related('items__product').order_by('-production_date', '-id')[:12])
    for b in all_production_batches:
        b_info = all_batches_fifo_map.get(b.id, {})
        b.fifo_sold = b_info.get('total_sold', 0)
        b.fifo_remaining = b_info.get('total_remaining', b.total_jars)
        b.fifo_percent = b_info.get('percent_sold', 0.0)
        b.fifo_status = b_info.get('status', 'QUEUED')
        b.fifo_status_bn = b_info.get('status_bn', 'অপেক্ষমাণ')
        b.fifo_badge_class = b_info.get('status_badge_class', 'bg-gray-100 text-gray-700 border-gray-200')

    for p in products:
        p_fifo = products_fifo_map.get(p.id, {})
        p.fifo_active_batch = p_fifo.get('active_batch')
        p.fifo_all_sold_out = p_fifo.get('all_sold_out', False)
        p.fifo_has_batches = p_fifo.get('has_batches', False)

    context = {
        'active_selling_batches': active_selling_batches,
        'all_production_batches': all_production_batches,
        'products': products,
        'recent_price_logs': recent_price_logs,
        'all_catalog_products': all_products,
        'suggested_batch_ref': suggested_batch_ref,
        'today_date': timezone.now().date().strftime('%Y-%m-%d'),
        'categories': categories,
        'selected_cat': selected_cat,
        'search_query': search_query,
        'status_filter': status_filter,
        'spice_choices': Product.SPICE_CHOICES,
        'cut_choices': Product.CUT_CHOICES,
        'total_products_count': all_products.count(),
        'in_stock_count': all_products.filter(is_in_stock=True, stock_count__gt=0).count(),
        'out_of_stock_count': all_products.filter(Q(is_in_stock=False) | Q(stock_count=0)).count(),
        'low_stock_products': low_stock_products,
        'low_stock_count': low_stock_count,
        'critical_stock_count': critical_stock_count,
        'total_needed_jars': total_needed_jars,
        'total_current_inventory': total_current_inventory,
        'total_target_inventory': total_target_inventory,
        'total_inventory_value': total_inventory_value,
    }
    return render(request, 'dashboard/stock_manager.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def production_batches_list(request):
    """
    Dedicated Production Batches Manager & Timeline.
    Shows every single batch produced (Batch #1, Batch #2, etc.), date prepared, total jars, flavors breakdown, and notes.
    """
    # Clean up any phantom 'Reverted ...' batch entries created previously
    ProductionBatch.objects.filter(batch_number__startswith='Reverted').delete()

    now = timezone.now()
    today = now.date()
    search_query = request.GET.get('q', '').strip()
    date_filter = request.GET.get('date_range', 'all')

    if request.method == 'POST':
        action = request.POST.get('action')
        
        # 1. CREATE NEW BATCH
        if action == 'create_batch':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: নতুন প্রোডাকশন ব্যাচ তৈরি করার অনুমতি নেই। (Batch creation restricted.)')
                return redirect('dashboard:production_batches')
            batch_ref = request.POST.get('batch_reference', '').strip()
            notes = request.POST.get('notes', '').strip()
            prod_date_str = request.POST.get('production_date', '').strip()
            total_cost_str = request.POST.get('total_cost_bdt', '0').strip()

            try:
                total_cost = Decimal(total_cost_str) if total_cost_str else Decimal('0.00')
            except Exception:
                total_cost = Decimal('0.00')

            prod_date_obj = today
            if prod_date_str:
                try:
                    prod_date_obj = datetime.datetime.strptime(prod_date_str, '%Y-%m-%d').date()
                except ValueError:
                    prod_date_obj = today

            # Auto-suggest batch name if left blank
            if not batch_ref:
                last_b = ProductionBatch.objects.order_by('-id').first()
                next_n = (last_b.id + 1) if last_b else 1
                batch_ref = f"Batch #{next_n}"

            items_to_add = []
            for key, val in request.POST.items():
                if key.startswith('batch_qty_') and val:
                    try:
                        p_id = int(key.replace('batch_qty_', ''))
                        q_int = int(val)
                        if q_int > 0:
                            items_to_add.append((p_id, q_int))
                    except (ValueError, TypeError):
                        pass

            if not items_to_add:
                messages.error(request, 'দয়া করে অন্তত ১টি আচারের পরিমাণ (Jars) লিখুন।')
                return redirect('dashboard:production_batches')

            # Create ProductionBatch
            batch = ProductionBatch.objects.create(
                batch_number=batch_ref,
                production_date=prod_date_obj,
                notes=notes,
                total_cost_bdt=total_cost,
                created_by=request.user if request.user.is_authenticated else None
            )

            total_added_jars = 0
            updated_product_names = []

            for p_id, add_qty in items_to_add:
                prod = Product.objects.filter(id=p_id).first()
                if prod:
                    prev_stock = prod.stock_count
                    new_stock = prev_stock + add_qty
                    prod.stock_count = new_stock
                    prod.is_in_stock = True
                    prod.save(update_fields=['stock_count', 'is_in_stock'])

                    # Create BatchItem
                    BatchItem.objects.create(
                        batch=batch,
                        product=prod,
                        quantity=add_qty,
                        notes=f"{prod.name}: +{add_qty} jars"
                    )

                    # Log Stock Transaction
                    log = StockLog.objects.create(
                        product=prod,
                        log_type='RESTOCK',
                        quantity_delta=add_qty,
                        previous_stock=prev_stock,
                        resulting_stock=new_stock,
                        reference=batch_ref,
                        notes=notes or f"Production Batch ({batch_ref}): +{add_qty} jars",
                        created_by=request.user if request.user.is_authenticated else None
                    )
                    if prod_date_obj:
                        prod_datetime = timezone.make_aware(datetime.datetime.combine(prod_date_obj, timezone.now().time())) if timezone.is_naive(datetime.datetime.combine(prod_date_obj, timezone.now().time())) else datetime.datetime.combine(prod_date_obj, timezone.now().time())
                        StockLog.objects.filter(id=log.id).update(created_at=prod_datetime)

                    total_added_jars += add_qty
                    updated_product_names.append(f"{prod.name} (+{add_qty})")

            messages.success(
                request,
                f'🎉 "{batch_ref}" সফলভাবে যুক্ত হয়েছে! মোট +{total_added_jars}টি জার তৈরি হয়েছে ({prod_date_obj.strftime("%d %b, %Y")})।'
            )
            return redirect('dashboard:production_batch_detail', batch_id=batch.id)

    batches_qs = ProductionBatch.objects.prefetch_related('items__product', 'created_by').all().order_by('-production_date', '-id')

    if search_query:
        batches_qs = batches_qs.filter(
            Q(batch_number__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(items__product__name__icontains=search_query)
        ).distinct()

    if date_filter == 'today':
        batches_qs = batches_qs.filter(production_date=today)
    elif date_filter == '7days':
        start_date = today - datetime.timedelta(days=7)
        batches_qs = batches_qs.filter(production_date__gte=start_date)
    elif date_filter == '30days':
        start_date = today - datetime.timedelta(days=30)
        batches_qs = batches_qs.filter(production_date__gte=start_date)
    elif date_filter == 'this_month':
        start_date = today.replace(day=1)
        batches_qs = batches_qs.filter(production_date__gte=start_date)
    elif date_filter == 'custom':
        custom_from = request.GET.get('from')
        custom_to = request.GET.get('to')
        if custom_from:
            try:
                f_date = datetime.datetime.strptime(custom_from, '%Y-%m-%d').date()
                batches_qs = batches_qs.filter(production_date__gte=f_date)
            except ValueError:
                pass
        if custom_to:
            try:
                t_date = datetime.datetime.strptime(custom_to, '%Y-%m-%d').date()
                batches_qs = batches_qs.filter(production_date__lte=t_date)
            except ValueError:
                pass

    all_batches_list = list(batches_qs)
    total_batches_count = len(all_batches_list)
    total_jars_produced = sum(b.total_jars for b in all_batches_list)
    total_retail_value = sum(b.total_retail_value for b in all_batches_list)
    avg_jars_per_batch = round(total_jars_produced / total_batches_count, 1) if total_batches_count > 0 else 0

    # Calculate FIFO batch tracking across all batches
    from dashboard.batch_fifo import calculate_all_batches_fifo, get_active_selling_recommendations
    batches_fifo_map = calculate_all_batches_fifo()
    active_selling_batches = get_active_selling_recommendations()

    for b in all_batches_list:
        b_info = batches_fifo_map.get(b.id, {})
        b.fifo_sold = b_info.get('total_sold', 0)
        b.fifo_remaining = b_info.get('total_remaining', b.total_jars)
        b.fifo_percent = b_info.get('percent_sold', 0.0)
        b.fifo_status = b_info.get('status', 'QUEUED')
        b.fifo_status_bn = b_info.get('status_bn', 'অপেক্ষমাণ')
        b.fifo_badge_class = b_info.get('status_badge_class', 'bg-gray-100 text-gray-700 border-gray-200')
        b.fifo_active_flavors = b_info.get('active_flavors', [])

    # Auto-suggest next batch reference
    last_batch = ProductionBatch.objects.order_by('-id').first()
    next_batch_num = 1
    if last_batch and last_batch.batch_number:
        import re
        m = re.search(r'(\d+)', last_batch.batch_number)
        if m:
            try:
                next_batch_num = int(m.group(1)) + 1
            except Exception:
                pass
    suggested_batch_ref = f"Batch #{next_batch_num}"

    # All active products for batch creation modal
    all_products = Product.objects.all().select_related('category').order_by('name')

    # Pagination configuration
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
        if per_page not in [5, 10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    paginator = Paginator(all_batches_list, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    try:
        elided_page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        elided_page_range = paginator.page_range

    context = {
        'batches': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'total_batches_count': total_batches_count,
        'total_jars_produced': total_jars_produced,
        'total_retail_value': total_retail_value,
        'avg_jars_per_batch': avg_jars_per_batch,
        'active_selling_batches': active_selling_batches,
        'suggested_batch_ref': suggested_batch_ref,
        'all_products': all_products,
        'search_query': search_query,
        'date_filter': date_filter,
        'today_date': today.strftime('%Y-%m-%d'),
    }
    return render(request, 'dashboard/production_batches.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def production_batch_detail(request, batch_id):
    """
    Detailed breakdown page for an individual production batch.
    Allows editing batch info and individual pickle quantities with automatic warehouse inventory adjustments.
    """
    batch = get_object_or_404(
        ProductionBatch.objects.prefetch_related('items__product__category', 'created_by'),
        id=batch_id
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        # 1. FULL BATCH & FLAVOR QUANTITIES EDIT
        if action in ['edit_batch_info', 'edit_batch_full']:
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: প্রোডাকশন ব্যাচ এডিট করার অনুমতি নেই।')
                return redirect('dashboard:production_batch_detail', batch_id=batch.id)

            old_batch_number = batch.batch_number
            new_batch_number = request.POST.get('batch_number', batch.batch_number).strip() or batch.batch_number
            batch.batch_number = new_batch_number
            batch.notes = request.POST.get('notes', '').strip()
            prod_date_str = request.POST.get('production_date', '').strip()
            if prod_date_str:
                try:
                    batch.production_date = datetime.datetime.strptime(prod_date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            cost_str = request.POST.get('total_cost_bdt', '').strip()
            if cost_str:
                try:
                    batch.total_cost_bdt = Decimal(cost_str)
                except Exception:
                    pass
            batch.save()

            if old_batch_number != new_batch_number:
                StockLog.objects.filter(reference=old_batch_number).update(reference=new_batch_number)

            # Process individual flavor quantities
            adjusted_changes = []
            all_prods = {p.id: p for p in Product.objects.all()}
            existing_items_map = {item.product_id: item for item in batch.items.all()}

            has_qty_inputs = any(k.startswith('batch_qty_') for k in request.POST.keys())
            if has_qty_inputs:
                for key, val in request.POST.items():
                    if key.startswith('batch_qty_'):
                        try:
                            p_id = int(key.replace('batch_qty_', ''))
                            new_qty = max(0, int(val) if val and str(val).strip() != '' else 0)
                        except (ValueError, TypeError):
                            continue

                        prod = all_prods.get(p_id)
                        if not prod:
                            continue

                        existing_item = existing_items_map.get(p_id)
                        old_qty = existing_item.quantity if existing_item else 0
                        delta = new_qty - old_qty

                        if delta != 0:
                            prev_stock = prod.stock_count
                            new_stock = max(0, prev_stock + delta)
                            prod.stock_count = new_stock
                            prod.save(update_fields=['stock_count'])

                            if new_qty > 0:
                                if existing_item:
                                    existing_item.quantity = new_qty
                                    existing_item.notes = f"{prod.name}: {new_qty} jars (edited from {old_qty})"
                                    existing_item.save(update_fields=['quantity', 'notes'])
                                else:
                                    BatchItem.objects.create(
                                        batch=batch,
                                        product=prod,
                                        quantity=new_qty,
                                        notes=f"{prod.name}: +{new_qty} jars (added in batch edit)"
                                    )
                            else:
                                if existing_item:
                                    existing_item.delete()

                            sign = '+' if delta > 0 else ''
                            StockLog.objects.create(
                                product=prod,
                                log_type='RESTOCK' if delta > 0 else 'STOCK_ADJUSTMENT',
                                quantity_delta=delta,
                                previous_stock=prev_stock,
                                resulting_stock=new_stock,
                                reference=batch.batch_number,
                                notes=f"Batch Edit ({batch.batch_number}): {prod.name} {sign}{delta} jars ({old_qty} -> {new_qty}). Resulting stock: {new_stock}",
                                created_by=request.user if request.user.is_authenticated else None
                            )
                            adjusted_changes.append(f"{prod.name} ({sign}{delta})")

            msg_suffix = f" এবং আচারের স্টকে সমন্বয় করা হয়েছে: {', '.join(adjusted_changes)}" if adjusted_changes else ""
            messages.success(request, f'ব্যাচ "{batch.batch_number}" সফলভাবে আপডেট হয়েছে{msg_suffix}।')
            return redirect('dashboard:production_batch_detail', batch_id=batch.id)

        # 2. QUICK EDIT SINGLE ITEM QUANTITY
        elif action == 'edit_batch_item_qty':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: আচারের সংখ্যা এডিট করার অনুমতি নেই।')
                return redirect('dashboard:production_batch_detail', batch_id=batch.id)

            item_id = request.POST.get('item_id')
            item = get_object_or_404(BatchItem, id=item_id, batch=batch)
            try:
                new_qty = max(0, int(request.POST.get('quantity', item.quantity)))
            except (ValueError, TypeError):
                new_qty = item.quantity

            old_qty = item.quantity
            delta = new_qty - old_qty

            if delta != 0:
                prod = item.product
                prev_stock = prod.stock_count
                new_stock = max(0, prev_stock + delta)
                prod.stock_count = new_stock
                prod.save(update_fields=['stock_count'])

                sign = '+' if delta > 0 else ''
                if new_qty > 0:
                    item.quantity = new_qty
                    item.notes = f"{prod.name}: {new_qty} jars (edited from {old_qty})"
                    item.save(update_fields=['quantity', 'notes'])
                else:
                    item.delete()

                StockLog.objects.create(
                    product=prod,
                    log_type='RESTOCK' if delta > 0 else 'STOCK_ADJUSTMENT',
                    quantity_delta=delta,
                    previous_stock=prev_stock,
                    resulting_stock=new_stock,
                    reference=batch.batch_number,
                    notes=f"Batch Item Edit ({batch.batch_number}): {prod.name} {sign}{delta} jars ({old_qty} -> {new_qty}). Resulting stock: {new_stock}",
                    created_by=request.user if request.user.is_authenticated else None
                )
                messages.success(request, f'{prod.name} এর পরিমাণ আপডেট করা হয়েছে: {old_qty} -> {new_qty} জার ({sign}{delta} ইনভেন্টরি সমন্বয়)।')
            else:
                messages.info(request, f'{item.product.name} এর সংখ্যা অপরিবর্তিত রয়েছে।')
            return redirect('dashboard:production_batch_detail', batch_id=batch.id)

        # 3. ADD SINGLE FLAVOR TO THIS BATCH
        elif action == 'add_single_flavor':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: আচার যোগ করার অনুমতি নেই।')
                return redirect('dashboard:production_batch_detail', batch_id=batch.id)

            prod_id = request.POST.get('product_id')
            prod = get_object_or_404(Product, id=prod_id)
            try:
                add_qty = int(request.POST.get('quantity', 0))
            except (ValueError, TypeError):
                add_qty = 0

            if add_qty > 0:
                existing_item = batch.items.filter(product=prod).first()
                prev_stock = prod.stock_count
                new_stock = prev_stock + add_qty
                prod.stock_count = new_stock
                prod.is_in_stock = True
                prod.save(update_fields=['stock_count', 'is_in_stock'])

                if existing_item:
                    existing_item.quantity += add_qty
                    existing_item.notes = f"{prod.name}: +{existing_item.quantity} jars"
                    existing_item.save(update_fields=['quantity', 'notes'])
                    msg_txt = f'ব্যাচে "{prod.name}" এ অতিরিক্ত +{add_qty} জার যোগ হয়েছে (মোট {existing_item.quantity} জার)।'
                else:
                    BatchItem.objects.create(
                        batch=batch,
                        product=prod,
                        quantity=add_qty,
                        notes=f"{prod.name}: +{add_qty} jars (added to batch)"
                    )
                    msg_txt = f'ব্যাচে "{prod.name}" নতুনভাবে +{add_qty} জার যুক্ত করা হয়েছে।'

                StockLog.objects.create(
                    product=prod,
                    log_type='RESTOCK',
                    quantity_delta=add_qty,
                    previous_stock=prev_stock,
                    resulting_stock=new_stock,
                    reference=batch.batch_number,
                    notes=f"Added to Batch ({batch.batch_number}): {prod.name} +{add_qty} jars",
                    created_by=request.user if request.user.is_authenticated else None
                )
                messages.success(request, msg_txt)
            else:
                messages.error(request, 'পরিমাণ অবশ্যই ১ বা তার বেশি হতে হবে।')
            return redirect('dashboard:production_batch_detail', batch_id=batch.id)

        # 4. REMOVE ITEM FROM BATCH
        elif action == 'delete_batch_item':
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: আইটেম মুছে ফেলার অনুমতি নেই।')
                return redirect('dashboard:production_batch_detail', batch_id=batch.id)

            item_id = request.POST.get('item_id')
            item = get_object_or_404(BatchItem, id=item_id, batch=batch)
            prod = item.product
            revert_stock = request.POST.get('revert_stock') in ('1', 'true', 'on', 'yes')
            removed_qty = item.quantity

            if revert_stock and prod:
                prev_stock = prod.stock_count
                new_stock = max(0, prev_stock - removed_qty)
                prod.stock_count = new_stock
                prod.save(update_fields=['stock_count'])

                StockLog.objects.create(
                    product=prod,
                    log_type='STOCK_ADJUSTMENT',
                    quantity_delta=-removed_qty,
                    previous_stock=prev_stock,
                    resulting_stock=new_stock,
                    reference=batch.batch_number,
                    notes=f"Removed from Batch ({batch.batch_number}): {prod.name} -{removed_qty} jars reverted from stock",
                    created_by=request.user if request.user.is_authenticated else None
                )

            item_name = prod.name if prod else "আচার"
            item.delete()
            revert_msg = f" (স্টক থেকে {removed_qty} জার বিয়োগ হয়েছে)" if revert_stock else ""
            messages.success(request, f'ব্যাচ থেকে "{item_name}" বাদ দেওয়া হয়েছে{revert_msg}।')
            return redirect('dashboard:production_batch_detail', batch_id=batch.id)

    items = list(batch.items.select_related('product__category').all())
    total_jars = sum(i.quantity for i in items)
    total_retail_value = sum(i.total_retail_value for i in items)

    # Compute FIFO tracking for this specific batch
    from dashboard.batch_fifo import calculate_all_batches_fifo
    all_batches_fifo = calculate_all_batches_fifo()
    batch_fifo = all_batches_fifo.get(batch.id, {})

    batch_sold_jars = batch_fifo.get('total_sold', 0)
    batch_remaining_jars = batch_fifo.get('total_remaining', total_jars)
    batch_percent_sold = batch_fifo.get('percent_sold', 0.0)
    batch_status = batch_fifo.get('status', 'QUEUED')
    batch_status_bn = batch_fifo.get('status_bn', 'অপেক্ষমাণ')
    batch_badge_class = batch_fifo.get('status_badge_class', 'bg-amber-100 text-amber-900 border-amber-300')

    items_fifo_by_pid = {it['product_id']: it for it in batch_fifo.get('items', [])}
    for item in items:
        f_info = items_fifo_by_pid.get(item.product_id, {})
        item.fifo_sold = f_info.get('sold_qty', 0)
        item.fifo_remaining = f_info.get('remaining_qty', item.quantity)
        item.fifo_status = f_info.get('status', 'QUEUED')
        item.fifo_status_bn = f_info.get('status_bn', 'অপেক্ষমাণ')
        item.fifo_percent = f_info.get('percent_sold', 0.0)

    all_products = list(Product.objects.all().select_related('category').order_by('name'))
    existing_product_ids = {item.product_id for item in items}
    available_products_to_add = [p for p in all_products if p.id not in existing_product_ids]

    for p in all_products:
        p.current_batch_qty = next((i.quantity for i in items if i.product_id == p.id), 0)
        p.is_in_this_batch = p.id in existing_product_ids

    context = {
        'batch': batch,
        'items': items,
        'total_jars': total_jars,
        'total_retail_value': total_retail_value,
        'batch_sold_jars': batch_sold_jars,
        'batch_remaining_jars': batch_remaining_jars,
        'batch_percent_sold': batch_percent_sold,
        'batch_status': batch_status,
        'batch_status_bn': batch_status_bn,
        'batch_badge_class': batch_badge_class,
        'all_products': all_products,
        'available_products_to_add': available_products_to_add,
        'today_date': timezone.now().date().strftime('%Y-%m-%d'),
        'can_delete': can_user_delete(request.user),
        'can_edit': can_user_edit(request.user),
    }
    return render(request, 'dashboard/production_batch_detail.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def delete_production_batch(request, batch_id):
    """
    Delete a production batch with optional stock reversion.
    """
    if not can_user_delete(request.user):
        messages.error(request, 'Permission Denied: Admin ছাড়া কেউ প্রোডাকশন ব্যাচ ডিলিট করতে পারবেন না। (Only Administrator can delete production batches.)')
        return redirect('dashboard:production_batches')

    if request.method == 'POST':
        batch = get_object_or_404(ProductionBatch, id=batch_id)
        batch_name = batch.batch_number
        revert_stock = request.POST.get('revert_stock') in ('1', 'true', 'on', 'yes')

        if revert_stock:
            for item in batch.items.select_related('product'):
                if item.product:
                    prev_stock = item.product.stock_count
                    new_stock = max(0, prev_stock - item.quantity)
                    item.product.stock_count = new_stock
                    item.product.save(update_fields=['stock_count'])

        # Clean up any StockLogs referencing this batch
        StockLog.objects.filter(reference=batch_name).delete()
        StockLog.objects.filter(reference__startswith=f"Reverted {batch_name}").delete()
        StockLog.objects.filter(notes__icontains=batch_name).delete()

        batch.delete()
        revert_msg = " এবং স্টক থেকে জার সংখ্যা সমন্বয় করা হয়েছে।" if revert_stock else "।"
        messages.success(request, f'প্রোডাকশন ব্যাচ "{batch_name}" সফলভাবে মুছে ফেলা হয়েছে{revert_msg}')
        return redirect('dashboard:production_batches')

    return redirect('dashboard:production_batches')



@user_passes_test(is_staff_user, login_url='dashboard:login')
def stock_ledger(request):
    """
    Comprehensive Stock History & Ledger Audit Trail.
    Allows filtering by Product, Transaction Type, Date Range, and Search keywords.
    """
    product_filter = request.GET.get('product', '')
    type_filter = request.GET.get('type', '')
    date_filter = request.GET.get('date_range', '30days')
    search_query = request.GET.get('q', '').strip()
    export_csv = request.GET.get('export') == 'csv'

    logs_qs = StockLog.objects.select_related('product', 'order', 'created_by').all()

    # 1. Product Filter
    selected_product = None
    if product_filter:
        try:
            prod_id = int(product_filter)
            logs_qs = logs_qs.filter(product_id=prod_id)
            selected_product = Product.objects.filter(id=prod_id).first()
        except ValueError:
            pass

    # 2. Type Filter
    if type_filter and type_filter in dict(StockLog.LOG_TYPE_CHOICES):
        logs_qs = logs_qs.filter(log_type=type_filter)

    # 3. Search Query
    if search_query:
        logs_qs = logs_qs.filter(
            Q(product__name__icontains=search_query) |
            Q(reference__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(order__order_number__icontains=search_query)
        )

    # 4. Date Range Filter
    now = timezone.localtime(timezone.now())
    today = now.date()
    today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
    today_end = today_start + timedelta(days=1)

    if date_filter == 'today':
        logs_qs = logs_qs.filter(created_at__gte=today_start, created_at__lt=today_end)
    elif date_filter == '7days':
        start_date = today - datetime.timedelta(days=7)
        logs_qs = logs_qs.filter(created_at__date__gte=start_date)
    elif date_filter == '30days':
        start_date = today - datetime.timedelta(days=30)
        logs_qs = logs_qs.filter(created_at__date__gte=start_date)
    elif date_filter == 'this_month':
        start_date = today.replace(day=1)
        logs_qs = logs_qs.filter(created_at__date__gte=start_date)
    elif date_filter == 'custom':
        custom_from = request.GET.get('from')
        custom_to = request.GET.get('to')
        if custom_from:
            try:
                f_date = datetime.datetime.strptime(custom_from, '%Y-%m-%d').date()
                logs_qs = logs_qs.filter(created_at__date__gte=f_date)
            except ValueError:
                pass
        if custom_to:
            try:
                t_date = datetime.datetime.strptime(custom_to, '%Y-%m-%d').date()
                logs_qs = logs_qs.filter(created_at__date__lte=t_date)
            except ValueError:
                pass

    # 5. Handle CSV Export
    if export_csv:
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="pickpickles_stock_ledger_{today.strftime("%Y%m%d")}.csv"'
        response.write('\ufeff'.encode('utf8')) # UTF-8 BOM for Excel
        writer = csv.writer(response)
        writer.writerow(['Date & Time', 'Product', 'Type', 'Delta Quantity', 'Previous Stock', 'Resulting Stock', 'Reference', 'Order #', 'User', 'Notes'])
        for log in logs_qs.order_by('-created_at'):
            writer.writerow([
                log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                log.product.name if log.product else 'N/A',
                log.get_log_type_display(),
                f"{'+' if log.quantity_delta > 0 else ''}{log.quantity_delta}",
                log.previous_stock,
                log.resulting_stock,
                log.reference,
                log.order.order_number if log.order else '',
                log.created_by.username if log.created_by else 'System',
                log.notes
            ])
        return response

    # 6. Statistics Calculations
    total_in = logs_qs.filter(quantity_delta__gt=0).aggregate(Sum('quantity_delta'))['quantity_delta__sum'] or 0
    total_out = abs(logs_qs.filter(quantity_delta__lt=0).aggregate(Sum('quantity_delta'))['quantity_delta__sum'] or 0)
    net_movement = total_in - total_out
    current_inventory_total = Product.objects.aggregate(Sum('stock_count'))['stock_count__sum'] or 0

    all_products = Product.objects.all().order_by('name')
    logs_ordered = logs_qs.order_by('-created_at')

    # Pagination (Default: 10 per page)
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    paginator = Paginator(logs_ordered, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    try:
        elided_page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        elided_page_range = paginator.page_range

    context = {
        'logs': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'all_products': all_products,
        'selected_product': selected_product,
        'product_filter': product_filter,
        'type_filter': type_filter,
        'date_filter': date_filter,
        'search_query': search_query,
        'total_logs_count': paginator.count,
        'total_jars_in': total_in,
        'total_jars_out': total_out,
        'net_movement': net_movement,
        'current_inventory_total': current_inventory_total,
        'log_type_choices': StockLog.LOG_TYPE_CHOICES,
    }
    return render(request, 'dashboard/stock_ledger.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def product_stock_ledger(request, product_id):
    """Direct shortcut to view ledger of a specific product"""
    product = get_object_or_404(Product, id=product_id)
    return redirect(f"{reverse('dashboard:stock_ledger')}?product={product.id}&date_range=all")


@user_passes_test(is_staff_user, login_url='dashboard:login')
def price_history(request):
    """
    Comprehensive Price History & Audit Trail (মূল্য পরিবর্তনের খতিয়ান).
    Allows filtering by Product, Change Type (All, Increase, Decrease, Initial), Date Range, and Search keywords.
    """
    product_filter = request.GET.get('product', '')
    type_filter = request.GET.get('type', '')
    date_filter = request.GET.get('date_range', 'all')
    search_query = request.GET.get('q', '').strip()

    history_qs = PriceHistory.objects.select_related('product', 'changed_by').all().order_by('-created_at')

    # 1. Product Filter
    selected_product = None
    if product_filter:
        try:
            prod_id = int(product_filter)
            history_qs = history_qs.filter(product_id=prod_id)
            selected_product = Product.objects.filter(id=prod_id).first()
        except ValueError:
            pass

    # 2. Type Filter
    if type_filter and type_filter in ['INCREASE', 'DECREASE', 'INITIAL']:
        history_qs = history_qs.filter(change_type=type_filter)

    # 3. Search Query
    if search_query:
        history_qs = history_qs.filter(
            Q(product__name__icontains=search_query) |
            Q(reason__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(changed_by__username__icontains=search_query)
        )

    # 4. Date Range Filter
    now = timezone.localtime(timezone.now())
    today = now.date()
    today_start = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
    today_end = today_start + timedelta(days=1)

    if date_filter == 'today':
        history_qs = history_qs.filter(created_at__gte=today_start, created_at__lt=today_end)
    elif date_filter == '7days':
        start_date = today - datetime.timedelta(days=7)
        history_qs = history_qs.filter(created_at__date__gte=start_date)
    elif date_filter == '30days':
        start_date = today - datetime.timedelta(days=30)
        history_qs = history_qs.filter(created_at__date__gte=start_date)
    elif date_filter == 'this_month':
        start_date = today.replace(day=1)
        history_qs = history_qs.filter(created_at__date__gte=start_date)
    elif date_filter == 'custom':
        custom_from = request.GET.get('from')
        custom_to = request.GET.get('to')
        if custom_from:
            try:
                from_date = datetime.datetime.strptime(custom_from, '%Y-%m-%d').date()
                history_qs = history_qs.filter(created_at__date__gte=from_date)
            except ValueError:
                pass
        if custom_to:
            try:
                to_date = datetime.datetime.strptime(custom_to, '%Y-%m-%d').date()
                history_qs = history_qs.filter(created_at__date__lte=to_date)
            except ValueError:
                pass

    # Summary Stats
    total_records = history_qs.count()
    increases_count = history_qs.filter(change_type='INCREASE').count()
    decreases_count = history_qs.filter(change_type='DECREASE').count()
    initial_count = history_qs.filter(change_type='INITIAL').count()
    distinct_products_count = history_qs.values('product').distinct().count()

    # Pagination
    try:
        per_page = int(request.GET.get('per_page', 10))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in [5, 10, 20, 50, 100]:
        per_page = 10

    paginator = Paginator(history_qs, per_page)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    try:
        elided_page_range = paginator.get_elided_page_range(
            page_obj.number, on_each_side=2, on_ends=1
        )
    except Exception:
        elided_page_range = paginator.page_range

    all_products = Product.objects.all().order_by('name')

    context = {
        'page_obj': page_obj,
        'records': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'all_products': all_products,
        'selected_product': selected_product,
        'product_filter': product_filter,
        'type_filter': type_filter,
        'date_filter': date_filter,
        'search_query': search_query,
        'total_records': total_records,
        'increases_count': increases_count,
        'decreases_count': decreases_count,
        'initial_count': initial_count,
        'distinct_products_count': distinct_products_count,
        'can_edit': can_user_edit(request.user),
    }
    return render(request, 'dashboard/price_history.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def product_price_history(request, product_id):
    """Direct shortcut to view price history of a specific product"""
    product = get_object_or_404(Product, id=product_id)
    return redirect(f"{reverse('dashboard:price_history')}?product={product.id}&date_range=all")


def sync_order_return_state(order_return, new_status, courier_fee=None, notes=None, restock_if_intact=True, user=None):
    """
    Synchronizes an OrderReturn with Product stock, StockLog ledger, DamageLog records, and Expenses.
    - If RECEIVED_INTACT: restocks inventory (if restock_if_intact and not already restocked),
      removes any auto-generated DamageLogs for this order.
    - If RECEIVED_DAMAGED: reverses any previous restock, creates accurate DamageLog records
      for all order items using real unit prices, and logs stock deduction.
    - If RETURNING: reverses any previous restock and removes auto-generated DamageLogs until
      final inspection upon receipt.
    - Accurately creates/updates/removes linked courier return fee Expense.
    """
    order = order_return.order
    today = timezone.now().date()

    if courier_fee is not None:
        order_return.courier_return_fee = Decimal(str(courier_fee))
    if notes is not None:
        order_return.notes = notes

    order_return.return_status = new_status

    # Always ensure order status is CANCELLED when returned
    if order.order_status != 'CANCELLED':
        order.order_status = 'CANCELLED'
        order.save(update_fields=['order_status'])

    # Handle Courier Return Fee in Expense Ledger
    courier_fee_val = float(order_return.courier_return_fee or 0)
    if courier_fee_val > 0:
        if order_return.expense:
            order_return.expense.amount = Decimal(str(courier_fee_val))
            order_return.expense.expense_date = order_return.return_date or today
            order_return.expense.notes = f"Return Courier Charge for Order #{order.order_number} ({order_return.get_return_reason_display()})"
            order_return.expense.save()
        else:
            exp = Expense.objects.create(
                title=f"Courier Return Fee: Order #{order.order_number}",
                category='LOGISTICS',
                amount=Decimal(str(courier_fee_val)),
                expense_date=order_return.return_date or today,
                payment_method='CASH',
                receipt_reference=f"RET-FEE-{order.order_number}",
                notes=f"Return Courier Charge for Order #{order.order_number} ({order_return.get_return_reason_display()})"
            )
            order_return.expense = exp
    else:
        if order_return.expense:
            order_return.expense.delete()
            order_return.expense = None

    # 1. Handling RECEIVED_INTACT (Jars returned intact and safe to resell)
    if new_status == 'RECEIVED_INTACT':
        # Remove any damage logs previously recorded for this returned order along with linked expenses
        for old_dmg in DamageLog.objects.filter(order_ref=order.order_number, reason='RETURN_DAMAGED'):
            if old_dmg.expense:
                old_dmg.expense.delete()
            old_dmg.delete()

        # Restock items if requested and not already restocked
        if restock_if_intact and not order_return.is_restocked:
            for item in order.items.all():
                if item.product:
                    prev_stock = item.product.stock_count
                    new_stock = prev_stock + item.quantity
                    item.product.stock_count = new_stock
                    item.product.is_in_stock = True
                    item.product.save(update_fields=['stock_count', 'is_in_stock'])

                    StockLog.objects.create(
                        product=item.product,
                        log_type='RETURN_RESTOCKED',
                        quantity_delta=item.quantity,
                        previous_stock=prev_stock,
                        resulting_stock=new_stock,
                        order=order,
                        reference=f"Return #{order.order_number}",
                        notes=f"Customer return restocked intact ({order_return.get_return_reason_display()})",
                        created_by=user if getattr(user, 'is_authenticated', False) else None
                    )
            order_return.is_restocked = True

    # 2. Handling RECEIVED_DAMAGED (Jars returned broken/ruined and cannot be resold)
    elif new_status == 'RECEIVED_DAMAGED':
        # If it was previously restocked as intact, revert the restocked inventory
        if order_return.is_restocked:
            for item in order.items.all():
                if item.product:
                    prev_stock = item.product.stock_count
                    new_stock = max(0, prev_stock - item.quantity)
                    item.product.stock_count = new_stock
                    item.product.save(update_fields=['stock_count'])

                    StockLog.objects.create(
                        product=item.product,
                        log_type='DAMAGE_LOSS',
                        quantity_delta=-item.quantity,
                        previous_stock=prev_stock,
                        resulting_stock=new_stock,
                        order=order,
                        reference=f"Damaged Return #{order.order_number}",
                        notes=f"Return damaged in transit - stock deducted ({order_return.get_return_reason_display()})",
                        created_by=user if getattr(user, 'is_authenticated', False) else None
                    )
            order_return.is_restocked = False

        # Ensure accurate DamageLog records exist for each product item using real unit prices
        for old_dmg in DamageLog.objects.filter(order_ref=order.order_number, reason='RETURN_DAMAGED'):
            if old_dmg.expense:
                old_dmg.expense.delete()
            old_dmg.delete()

        for item in order.items.all():
            if item.product:
                unit_cost = float(item.unit_price) if item.unit_price else float(item.product.price_bdt)
                total_loss = unit_cost * item.quantity
                
                # Auto create expense record for damaged return loss
                exp = Expense.objects.create(
                    title=f"Damaged Return: {item.quantity}x {item.product.name} (#{order.order_number})",
                    category='DAMAGE_LOSS',
                    amount=Decimal(str(total_loss)),
                    expense_date=order_return.return_date or today,
                    payment_method='CASH',
                    receipt_reference=f"DMG-RET-{order.order_number}",
                    notes=f"Returned damaged/broken parcel: Order #{order.order_number} ({order_return.get_return_reason_display()})"
                )

                DamageLog.objects.create(
                    product=item.product,
                    quantity=item.quantity,
                    estimated_cost_per_jar=Decimal(str(unit_cost)),
                    reason='RETURN_DAMAGED',
                    incident_date=order_return.return_date or today,
                    order_ref=order.order_number,
                    expense=exp,
                    notes=f"Returned damaged/broken parcel: Order #{order.order_number} ({order_return.get_return_reason_display()})"
                )

    # 3. Handling RETURNING (In transit with courier)
    elif new_status == 'RETURNING':
        # Remove damage logs since parcel is still in courier transit
        for old_dmg in DamageLog.objects.filter(order_ref=order.order_number, reason='RETURN_DAMAGED'):
            if old_dmg.expense:
                old_dmg.expense.delete()
            old_dmg.delete()

        # If it was previously marked restocked, revert stock
        if order_return.is_restocked:
            for item in order.items.all():
                if item.product:
                    prev_stock = item.product.stock_count
                    new_stock = max(0, prev_stock - item.quantity)
                    item.product.stock_count = new_stock
                    item.product.save(update_fields=['stock_count'])
            order_return.is_restocked = False

    order_return.save()
    return order_return


def ensure_damage_and_returns_expenses_synced(user=None, force=False):
    """
    Guarantees that all DamageLogs and OrderReturns are properly represented in the Expense ledger.
    Backfills any unlinked DamageLogs or OrderReturn courier fees.
    """
    if not force:
        cache_key = 'damage_returns_synced_flag'
        if cache.get(cache_key):
            return
        cache.set(cache_key, True, timeout=600)  # Throttled to once every 10 minutes

    today = timezone.now().date()
    
    # 1. Backfill any DamageLog without an Expense
    unlinked_damages = DamageLog.objects.filter(expense__isnull=True).select_related('product')
    for dmg in unlinked_damages:
        reason_label = dmg.get_reason_display()
        total_loss = float(dmg.total_loss_bdt or (dmg.quantity * dmg.estimated_cost_per_jar))
        exp = Expense.objects.create(
            title=f"Damaged Product: {dmg.quantity}x {dmg.product.name}",
            category='DAMAGE_LOSS',
            amount=Decimal(str(total_loss)),
            expense_date=dmg.incident_date or today,
            payment_method='CASH',
            receipt_reference=f"DMG-{dmg.order_ref}" if dmg.order_ref else f"DMG-LOG-{dmg.id}",
            notes=f"Reason: {reason_label}. {dmg.notes}".strip()
        )
        dmg.expense = exp
        dmg.save(update_fields=['expense'])

    # 2. Backfill/Sync any OrderReturn with courier fee > 0 without an Expense
    unlinked_returns = OrderReturn.objects.filter(courier_return_fee__gt=0, expense__isnull=True).select_related('order')
    for ret in unlinked_returns:
        fee = float(ret.courier_return_fee)
        exp = Expense.objects.create(
            title=f"Courier Return Fee: Order #{ret.order.order_number}",
            category='LOGISTICS',
            amount=Decimal(str(fee)),
            expense_date=ret.return_date or today,
            payment_method='CASH',
            receipt_reference=f"RET-FEE-{ret.order.order_number}",
            notes=f"Return Courier Charge for Order #{ret.order.order_number} ({ret.get_return_reason_display()})"
        )
        ret.expense = exp
        ret.save(update_fields=['expense'])

    # 3. Synchronize any RECEIVED_DAMAGED order return that is missing damage logs
    damaged_returns_without_logs = OrderReturn.objects.filter(return_status='RECEIVED_DAMAGED').select_related('order')
    for ret in damaged_returns_without_logs:
        existing_log_count = DamageLog.objects.filter(order_ref=ret.order.order_number, reason='RETURN_DAMAGED').count()
        if existing_log_count == 0:
            sync_order_return_state(ret, 'RECEIVED_DAMAGED', user=user)


def ensure_expense_taxonomy_and_allocation_synced(force=False):
    """
    Disabled: User database additions and edits must be strictly preserved.
    No background taxonomy overwriting or auto-execution is permitted.
    """
    return


@user_passes_test(is_staff_user, login_url='dashboard:login')
def damage_returns_manager(request):
    """Manager for recording broken/damaged pickle jars and courier returned parcels."""
    now = timezone.now()
    today = now.date()

    # Automatically ensure historical damages and returns are fully synchronized with expenses
    ensure_damage_and_returns_expenses_synced(user=request.user)

    damage_logs = DamageLog.objects.all().select_related('product', 'expense').order_by('-incident_date', '-created_at')
    order_returns = OrderReturn.objects.all().select_related('order', 'expense').prefetch_related('order__items').order_by('-created_at')
    products = Product.objects.all().order_by('name')
    orders = Order.objects.all().order_by('-created_at')[:100]

    if request.method == 'POST':
        action = request.POST.get('action')

        # 1. RECORD DAMAGE LOG
        if action == 'record_damage':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: ড্যামেজ রেকর্ড যুক্ত করার অনুমতি নেই। (Damage recording restricted.)')
                return redirect('dashboard:damage_returns')
            try:
                prod_id = request.POST.get('product_id')
                product = get_object_or_404(Product, id=prod_id)
                quantity = int(request.POST.get('quantity', 1))
                default_price = float(product.price_bdt)
                cost_input = request.POST.get('estimated_cost_per_jar')
                estimated_cost = float(cost_input) if cost_input and float(cost_input) > 0 else default_price
                reason = request.POST.get('reason', 'TRANSIT_BREAKAGE')
                incident_date = request.POST.get('incident_date') or today
                order_ref = request.POST.get('order_ref', '').strip()
                notes = request.POST.get('notes', '').strip()
                deduct_stock = request.POST.get('deduct_stock') == 'on'
                add_to_expense = ('add_to_expense' in request.POST) or (request.POST.get('add_to_expense') == 'on')

                # Deduct from product stock if requested
                if deduct_stock and product.stock_count >= quantity:
                    prev_stock = product.stock_count
                    new_stock = max(0, prev_stock - quantity)
                    product.stock_count = new_stock
                    product.save(update_fields=['stock_count'])

                    StockLog.objects.create(
                        product=product,
                        log_type='DAMAGE_LOSS',
                        quantity_delta=-quantity,
                        previous_stock=prev_stock,
                        resulting_stock=new_stock,
                        reference=f"Damage Loss: {reason}" if not order_ref else f"Damage (Order #{order_ref})",
                        notes=notes or f"{quantity} jar(s) recorded as damaged/broken",
                        created_by=request.user if request.user.is_authenticated else None
                    )

                exp = None
                if add_to_expense:
                    reason_dict = dict(DamageLog.DAMAGE_REASON_CHOICES)
                    reason_label = reason_dict.get(reason, reason)
                    exp = Expense.objects.create(
                        title=f"Damaged Product: {quantity}x {product.name}",
                        category='DAMAGE_LOSS',
                        amount=Decimal(str(estimated_cost * quantity)),
                        expense_date=incident_date,
                        payment_method='CASH',
                        receipt_reference=f"DMG-{order_ref}" if order_ref else f"DMG-{product.id}-{int(timezone.now().timestamp())}",
                        notes=f"Reason: {reason_label}. {notes}".strip()
                    )

                DamageLog.objects.create(
                    product=product,
                    quantity=quantity,
                    estimated_cost_per_jar=Decimal(str(estimated_cost)),
                    reason=reason,
                    incident_date=incident_date,
                    order_ref=order_ref,
                    expense=exp,
                    notes=notes
                )
                exp_msg = " Added to expenses." if exp else ""
                messages.success(request, f'Logged {quantity}x {product.name} damage (৳{estimated_cost * quantity:,.0f} loss).{exp_msg} Stock updated.')
            except Exception as e:
                messages.error(request, f'Failed to record damage: {str(e)}')
            return redirect('dashboard:damage_returns')

        # 2. DELETE DAMAGE LOG
        elif action == 'delete_damage':
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ ড্যামেজ রেকর্ড ডিলিট করতে পারবেন না। (Only Administrator can delete damage logs.)')
                return redirect('dashboard:damage_returns')
            damage_id = request.POST.get('damage_id')
            log = get_object_or_404(DamageLog, id=damage_id)
            if log.expense:
                log.expense.delete()
            log.delete()
            messages.success(request, 'Damage record and associated expense deleted.')
            return redirect('dashboard:damage_returns')

        # 2.5 DELETE RETURN LOG
        elif action == 'delete_return':
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ রিটার্ন রেকর্ড ডিলিট করতে পারবেন না। (Only Administrator can delete return logs.)')
                return redirect('dashboard:damage_returns')
            ret_id = request.POST.get('return_id')
            ret = get_object_or_404(OrderReturn, id=ret_id)
            if ret.expense:
                ret.expense.delete()
            for old_dmg in DamageLog.objects.filter(order_ref=ret.order.order_number, reason='RETURN_DAMAGED'):
                if old_dmg.expense:
                    old_dmg.expense.delete()
                old_dmg.delete()
            ret.delete()
            messages.success(request, 'Return record and associated expenses deleted.')
            return redirect('dashboard:damage_returns')

        # 3. RECORD COURIER RETURN
        elif action == 'record_return':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: রিটার্ন রেকর্ড করার অনুমতি নেই। (Return recording restricted.)')
                return redirect('dashboard:damage_returns')
            try:
                order_id = request.POST.get('order_id')
                order = get_object_or_404(Order, id=order_id)
                return_reason = request.POST.get('return_reason', 'CUSTOMER_REFUSED')
                return_status = request.POST.get('return_status', 'RETURNING')
                courier_return_fee = float(request.POST.get('courier_return_fee', 0.00))
                notes = request.POST.get('notes', '').strip()
                restock_now = request.POST.get('restock_now') == 'on'

                ret, _ = OrderReturn.objects.get_or_create(
                    order=order,
                    defaults={
                        'return_reason': return_reason,
                        'return_status': return_status,
                        'courier_return_fee': courier_return_fee,
                        'notes': notes,
                        'return_date': today,
                    }
                )
                ret.return_reason = return_reason

                sync_order_return_state(
                    order_return=ret,
                    new_status=return_status,
                    courier_fee=courier_return_fee,
                    notes=notes,
                    restock_if_intact=(return_status == 'RECEIVED_INTACT' and restock_now),
                    user=request.user
                )

                messages.success(request, f'Return logged for Order #{order.order_number} ({ret.get_return_status_display()}).')
            except Exception as e:
                messages.error(request, f'Failed to record return: {str(e)}')
            return redirect('dashboard:damage_returns')

        # 4. UPDATE RETURN STATUS
        elif action == 'update_return_status':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: রিটার্ন স্ট্যাটাস পরিবর্তন করার অনুমতি নেই।')
                return redirect('dashboard:damage_returns')
            try:
                ret_id = request.POST.get('return_id')
                ret = get_object_or_404(OrderReturn, id=ret_id)
                new_status = request.POST.get('new_status')
                courier_fee = float(request.POST.get('courier_return_fee', ret.courier_return_fee))
                notes = request.POST.get('notes', ret.notes)

                sync_order_return_state(
                    order_return=ret,
                    new_status=new_status,
                    courier_fee=courier_fee,
                    notes=notes,
                    restock_if_intact=(new_status == 'RECEIVED_INTACT'),
                    user=request.user
                )

                messages.success(request, f'Return for #{ret.order.order_number} updated to {ret.get_return_status_display()}.')
            except Exception as e:
                messages.error(request, f'Failed to update return: {str(e)}')
            return redirect('dashboard:damage_returns')

    # Aggregations & Detailed Calculations (Full Querysets)
    total_damaged_jars = damage_logs.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_damage_loss = float(damage_logs.aggregate(Sum('total_loss_bdt'))['total_loss_bdt__sum'] or 0)

    total_returns_count = order_returns.count()
    total_courier_fees = float(order_returns.aggregate(Sum('courier_return_fee'))['courier_return_fee__sum'] or 0)
    intact_returns_count = order_returns.filter(return_status='RECEIVED_INTACT').count()
    damaged_returns_count = order_returns.filter(return_status='RECEIVED_DAMAGED').count()
    pending_returning_count = order_returns.filter(return_status='RETURNING').count()

    total_combined_loss = total_damage_loss + total_courier_fees

    # 1. Courier Returns Pagination
    ret_page_number = request.GET.get('ret_page', 1)
    ret_per_page = request.GET.get('ret_per_page', 10)
    try:
        ret_per_page = int(ret_per_page)
        if ret_per_page not in [10, 15, 25, 50]:
            ret_per_page = 10
    except (ValueError, TypeError):
        ret_per_page = 10

    returns_paginator = Paginator(order_returns, ret_per_page)
    try:
        returns_page_obj = returns_paginator.page(ret_page_number)
    except PageNotAnInteger:
        returns_page_obj = returns_paginator.page(1)
    except EmptyPage:
        returns_page_obj = returns_paginator.page(returns_paginator.num_pages)

    try:
        returns_elided_range = returns_paginator.get_elided_page_range(number=returns_page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        returns_elided_range = returns_paginator.page_range

    # 2. Damage Logs Pagination
    dmg_page_number = request.GET.get('dmg_page', 1)
    dmg_per_page = request.GET.get('dmg_per_page', 10)
    try:
        dmg_per_page = int(dmg_per_page)
        if dmg_per_page not in [10, 15, 25, 50]:
            dmg_per_page = 10
    except (ValueError, TypeError):
        dmg_per_page = 10

    damage_paginator = Paginator(damage_logs, dmg_per_page)
    try:
        damage_page_obj = damage_paginator.page(dmg_page_number)
    except PageNotAnInteger:
        damage_page_obj = damage_paginator.page(1)
    except EmptyPage:
        damage_page_obj = damage_paginator.page(damage_paginator.num_pages)

    try:
        damage_elided_range = damage_paginator.get_elided_page_range(number=damage_page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        damage_elided_range = damage_paginator.page_range

    context = {
        'damage_logs': damage_page_obj,
        'damage_page_obj': damage_page_obj,
        'damage_paginator': damage_paginator,
        'damage_elided_range': damage_elided_range,
        'dmg_per_page': dmg_per_page,

        'order_returns': returns_page_obj,
        'returns_page_obj': returns_page_obj,
        'returns_paginator': returns_paginator,
        'returns_elided_range': returns_elided_range,
        'ret_per_page': ret_per_page,

        'products': products,
        'orders': orders,
        'damage_reasons': DamageLog.DAMAGE_REASON_CHOICES,
        'return_reasons': OrderReturn.RETURN_REASON_CHOICES,
        'return_statuses': OrderReturn.RETURN_STATUS_CHOICES,
        'total_damaged_jars': total_damaged_jars,
        'total_damage_loss': total_damage_loss,
        'total_returns_count': total_returns_count,
        'total_courier_fees': total_courier_fees,
        'intact_returns_count': intact_returns_count,
        'damaged_returns_count': damaged_returns_count,
        'pending_returning_count': pending_returning_count,
        'total_combined_loss': total_combined_loss,
        'today': today,
    }
    return render(request, 'dashboard/damage_returns.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def mark_order_returned(request, order_number):
    """Quick handler to mark an order as returned from the order detail view."""
    order = get_object_or_404(Order, order_number=order_number)
    if request.method == 'POST':
        if not can_user_edit(request.user):
            messages.error(request, 'Permission Denied: অর্ডার রিটার্ন চিহ্নিত করার অনুমতি নেই।')
            return redirect('dashboard:order_detail', order_number=order.order_number)
        reason = request.POST.get('return_reason', 'CUSTOMER_REFUSED')
        status = request.POST.get('return_status', 'RETURNING')
        fee = float(request.POST.get('courier_return_fee', 0.00))
        notes = request.POST.get('notes', '').strip()

        ret, _ = OrderReturn.objects.get_or_create(
            order=order,
            defaults={
                'return_reason': reason,
                'return_status': status,
                'courier_return_fee': fee,
                'notes': notes,
            }
        )
        ret.return_reason = reason
        sync_order_return_state(
            order_return=ret,
            new_status=status,
            courier_fee=fee,
            notes=notes,
            restock_if_intact=(status == 'RECEIVED_INTACT'),
            user=request.user
        )
        messages.success(request, f'Order #{order.order_number} marked as returned ({ret.get_return_status_display()}).')
    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def reviews_manager(request):
    all_reviews = Review.objects.all().select_related('product').order_by('-created_at')
    products = Product.objects.all().order_by('name')

    total_reviews = all_reviews.count()
    approved_count = all_reviews.filter(is_approved=True).count()
    pending_reviews_count = all_reviews.filter(is_approved=False).count()
    avg_rating = all_reviews.filter(is_approved=True).aggregate(Avg('rating'))['rating__avg']
    overall_rating = round(avg_rating, 1) if avg_rating else 5.0

    status_filter = request.GET.get('status', '').strip().lower()
    reviews = all_reviews
    if status_filter == 'pending':
        reviews = reviews.filter(is_approved=False)
    elif status_filter == 'approved':
        reviews = reviews.filter(is_approved=True)

    if request.method == 'POST':
        action = request.POST.get('action')
        review_id = request.POST.get('review_id')

        # 1. Toggle Approve
        if action == 'toggle_approve':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: রিভিউ অনুমোদন বা স্ট্যাটাস পরিবর্তন করার অনুমতি নেই।')
                redirect_url = reverse('dashboard:reviews')
                if status_filter:
                    redirect_url += f'?status={status_filter}'
                return redirect(redirect_url)
            review = get_object_or_404(Review, id=review_id)
            review.is_approved = not review.is_approved
            review.save()
            status_txt = 'approved & visible' if review.is_approved else 'hidden'
            messages.success(request, f'Review by {review.reviewer_name} is now {status_txt}.')
            redirect_url = reverse('dashboard:reviews')
            if status_filter:
                redirect_url += f'?status={status_filter}'
            return redirect(redirect_url)

        # 1b. Reject Review
        elif action == 'reject_review':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: রিভিউ রিজেক্ট করার অনুমতি নেই।')
                return redirect('dashboard:reviews')
            review = get_object_or_404(Review, id=review_id)
            r_name = review.reviewer_name
            review.delete()
            messages.success(request, f'Review by {r_name} was rejected.')
            redirect_url = reverse('dashboard:reviews')
            if status_filter:
                redirect_url += f'?status={status_filter}'
            return redirect(redirect_url)

        # 2. Delete Review
        elif action == 'delete_review':
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ রিভিউ ডিলিট করতে পারবেন না। (Only Administrator can delete reviews.)')
                return redirect('dashboard:reviews')
            review = get_object_or_404(Review, id=review_id)
            r_name = review.reviewer_name
            review.delete()
            messages.success(request, f'Review from {r_name} deleted successfully.')
            redirect_url = reverse('dashboard:reviews')
            if status_filter:
                redirect_url += f'?status={status_filter}'
            return redirect(redirect_url)

        # 3. Add Manual Review
        elif action == 'create_review':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: রিভিউ যুক্ত করার অনুমতি আপনার নেই। (Review creation restricted.)')
                return redirect('dashboard:reviews')
            prod_id = request.POST.get('product_id', '').strip()
            product = None
            if prod_id and prod_id != '0' and prod_id.lower() != 'all':
                product = Product.objects.filter(id=prod_id).first()

            name = request.POST.get('reviewer_name', 'Verified Customer').strip()
            phone = request.POST.get('reviewer_phone', '').strip()
            location = request.POST.get('reviewer_location', 'Dhaka').strip()
            rating = int(request.POST.get('rating', 5))
            crunch_score = int(request.POST.get('crunch_score', 5))
            comment = request.POST.get('comment', '').strip()
            image_file = request.FILES.get('image')

            Review.objects.create(
                product=product,
                reviewer_name=name,
                reviewer_phone=phone,
                reviewer_location=location,
                rating=rating,
                comment=comment,
                image=image_file,
                is_approved=True
            )
            target_name = product.name if product else "All Pickles (General Review)"
            messages.success(request, f'Review for {target_name} added successfully!')
            return redirect('dashboard:reviews')

        # 4. Edit Review
        elif action == 'edit_review':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: রিভিউ এডিট করার অনুমতি আপনার নেই। (Only Admin/Authorized Staff can edit reviews.)')
                return redirect('dashboard:reviews')

            review = get_object_or_404(Review, id=review_id)
            prod_id = request.POST.get('product_id', '').strip()
            if prod_id and prod_id != '0' and prod_id.lower() != 'all':
                review.product = Product.objects.filter(id=prod_id).first()
            else:
                review.product = None

            review.reviewer_name = request.POST.get('reviewer_name', review.reviewer_name).strip() or review.reviewer_name
            if 'reviewer_phone' in request.POST:
                review.reviewer_phone = request.POST.get('reviewer_phone', '').strip()
            review.reviewer_location = request.POST.get('reviewer_location', review.reviewer_location).strip() or review.reviewer_location
            try:
                review.rating = int(request.POST.get('rating', review.rating))
            except (ValueError, TypeError):
                pass

            review.comment = request.POST.get('comment', review.comment).strip() or review.comment

            if 'image' in request.FILES:
                review.image = request.FILES['image']
            elif request.POST.get('remove_image') == 'true':
                review.image = None

            if 'is_approved' in request.POST:
                review.is_approved = (request.POST.get('is_approved') in ['1', 'true', 'True'])

            review.save()
            messages.success(request, f'Review by {review.reviewer_name} updated successfully!')
            redirect_url = reverse('dashboard:reviews')
            if status_filter:
                redirect_url += f'?status={status_filter}'
            return redirect(redirect_url)

    # Pagination (Default: 10 per page)
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    paginator = Paginator(reviews, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    try:
        elided_page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        elided_page_range = paginator.page_range

    # Match customer phone numbers against Order records to verify authentic buyers
    phone_to_order = {}
    for ord_row in Order.objects.filter(is_deleted=False).values('customer_phone', 'order_number').order_by('-created_at'):
        raw_p = (ord_row['customer_phone'] or '').strip()
        if raw_p:
            digits = ''.join(ch for ch in raw_p if ch.isdigit())
            clean_p = digits[-11:] if len(digits) >= 11 else digits
            if clean_p and clean_p not in phone_to_order:
                phone_to_order[clean_p] = ord_row['order_number']

    for r in page_obj:
        raw_rp = (getattr(r, 'reviewer_phone', '') or '').strip()
        r_digits = ''.join(ch for ch in raw_rp if ch.isdigit())
        clean_rp = r_digits[-11:] if len(r_digits) >= 11 else r_digits
        r.matched_order_number = phone_to_order.get(clean_rp) if clean_rp else None

    context = {
        'reviews': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'products': products,
        'total_reviews': total_reviews,
        'approved_count': approved_count,
        'pending_reviews_count': pending_reviews_count,
        'overall_rating': overall_rating,
        'status_filter': status_filter,
        'can_edit': can_user_edit(request.user),
        'can_delete': can_user_delete(request.user),
    }
    return render(request, 'dashboard/reviews.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def feedback_reminders_manager(request):
    """
    Lists customers whose orders are >= 30 days old and have not yet provided feedback/review.
    - Status 'pending': Never sent, OR sent 30+ minutes ago (due for reminder).
    - Status 'done': Sent within the last 30 minutes (grace period).
    """
    now = timezone.now()

    # Days filter (default 30 days)
    days_param = request.GET.get('days', '30')
    try:
        min_days = int(days_param)
        if min_days < 1:
            min_days = 30
    except (ValueError, TypeError):
        min_days = 30

    status_filter = request.GET.get('status', 'pending').strip().lower()
    if status_filter not in ['pending', 'done', 'all']:
        status_filter = 'pending'

    cutoff_date = now - timedelta(days=min_days)

    # Base query: non-deleted orders placed at least `min_days` ago OR already marked as sent
    orders_qs = Order.objects.filter(
        Q(created_at__lte=cutoff_date) | Q(feedback_request_sent_at__isnull=False),
        is_deleted=False
    ).exclude(
        order_status__in=['CANCELLED']
    ).prefetch_related('items', 'items__product').order_by('-created_at')

    # Get set of all reviewer names (lowercased)
    reviewed_names = set(
        r.strip().lower() 
        for r in Review.objects.values_list('reviewer_name', flat=True) 
        if r and r.strip()
    )

    # Search filter
    q = request.GET.get('q', '').strip()
    if q:
        orders_qs = orders_qs.filter(
            Q(customer_name__icontains=q) |
            Q(customer_phone__icontains=q) |
            Q(order_number__icontains=q) |
            Q(delivery_city__icontains=q)
        )

    # Filter out customers who already reviewed:
    # - Pending: Feedback reminder NOT sent yet and created_at <= cutoff_date
    # - Done: Feedback reminder has already been sent
    pending_list = []
    done_list = []

    for order in orders_qs:
        cust_name_clean = (order.customer_name or '').strip().lower()
        if cust_name_clean not in reviewed_names:
            days_ago = (now.date() - order.created_at.date()).days
            order.days_ago = days_ago

            if order.feedback_request_sent_at:
                order.is_feedback_done = True
                order.days_since_sent = (now.date() - order.feedback_request_sent_at.date()).days
                done_list.append(order)
            elif order.created_at <= cutoff_date:
                order.is_feedback_done = False
                order.days_since_sent = None
                pending_list.append(order)

    pending_count = len(pending_list)
    done_count = len(done_list)

    if status_filter == 'done':
        selected_orders = done_list
    elif status_filter == 'all':
        selected_orders = pending_list + done_list
    else:
        selected_orders = pending_list

    total_eligible = len(selected_orders)

    # Pagination (Default: 20 per page)
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 20)
    try:
        per_page = int(per_page)
        if per_page not in [10, 20, 50, 100]:
            per_page = 20
    except (ValueError, TypeError):
        per_page = 20

    paginator = Paginator(selected_orders, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    try:
        elided_page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        elided_page_range = paginator.page_range

    context = {
        'orders': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'elided_page_range': elided_page_range,
        'total_eligible': total_eligible,
        'pending_count': pending_count,
        'done_count': done_count,
        'status_filter': status_filter,
        'min_days': min_days,
        'q': q,
        'per_page': per_page,
        'total_reviews': Review.objects.count(),
    }
    return render(request, 'dashboard/feedback_reminders.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def mark_feedback_reminder_sent(request, order_number):
    """Marks an order's review request message as sent now, or unmarks it if action=undo."""
    if request.method in ['POST', 'GET']:
        if not can_user_edit(request.user):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
                return JsonResponse({'success': False, 'error': 'Permission Denied: রিমাইন্ডার আপডেট করার অনুমতি নেই।'}, status=403)
            messages.error(request, 'Permission Denied: রিমাইন্ডার আপডেট করার অনুমতি নেই।')
            return redirect('dashboard:feedback_reminders')
        order = get_object_or_404(Order, order_number=order_number)
        action = request.GET.get('action') or request.POST.get('action')

        if action == 'undo':
            order.feedback_request_sent_at = None
            order.save(update_fields=['feedback_request_sent_at'])
            msg = f'Review reminder undone for #{order.order_number}. Moved back to Pending.'
            is_done = False
        else:
            order.feedback_request_sent_at = timezone.now()
            order.feedback_request_count = (order.feedback_request_count or 0) + 1
            order.save(update_fields=['feedback_request_sent_at', 'feedback_request_count'])
            msg = f'Review request marked as sent for #{order.order_number}. Moved to Done.'
            is_done = True

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
            return JsonResponse({
                'success': True,
                'order_number': order.order_number,
                'sent_at': order.feedback_request_sent_at.isoformat() if order.feedback_request_sent_at else None,
                'is_done': is_done,
                'count': order.feedback_request_count,
                'message': msg
            })

        messages.success(request, msg)
        return redirect('dashboard:feedback_reminders')

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def expense_manager(request):
    now = timezone.localtime(timezone.now())
    today = now.date()

    # Ensure damage, returns, and expense taxonomy allocations are synchronized
    ensure_damage_and_returns_expenses_synced(user=request.user)
    ensure_expense_taxonomy_and_allocation_synced()

    if request.method == 'POST':
        action = request.POST.get('action')
        expense_id = request.POST.get('expense_id')

        def get_safe_redirect():
            return_url = request.POST.get('return_url') or request.META.get('HTTP_REFERER')
            if return_url:
                from urllib.parse import urlparse
                parsed = urlparse(return_url)
                if parsed.path.rstrip('/').endswith('/expenses'):
                    safe_url = parsed.path
                    if parsed.query:
                        safe_url += f"?{parsed.query}"
                    return redirect(safe_url)
            return redirect('dashboard:expenses')

        # 1. CREATE EXPENSE
        if action == 'create_expense' or 'create_expense' in request.POST:
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: খরচ রেকর্ড তৈরি করার অনুমতি নেই। (Expense creation restricted.)')
                return get_safe_redirect()
            try:
                title = request.POST.get('title').strip()
                category = request.POST.get('category', 'RAW_MATERIAL')
                sub_category = request.POST.get('sub_category', '').strip()
                quantity_raw = request.POST.get('quantity', '').strip()
                quantity = float(quantity_raw) if quantity_raw else None
                unit = request.POST.get('unit', 'pcs').strip()
                amount = float(request.POST.get('amount'))
                expense_date = request.POST.get('expense_date') or today
                payment_method = request.POST.get('payment_method', 'CASH')
                receipt_reference = request.POST.get('receipt_reference', '').strip()
                notes = request.POST.get('notes', '').strip()

                Expense.objects.create(
                    title=title,
                    category=category,
                    sub_category=sub_category,
                    quantity=quantity,
                    unit=unit,
                    amount=amount,
                    expense_date=expense_date,
                    payment_method=payment_method,
                    receipt_reference=receipt_reference,
                    notes=notes
                )
                messages.success(request, f'Expense "৳{amount} - {title}" successfully recorded.')
            except Exception as e:
                messages.error(request, f'Failed to record expense: {str(e)}')
            return get_safe_redirect()

        # 2. EDIT EXPENSE
        elif action == 'edit_expense' or 'edit_expense' in request.POST:
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: খরচ রেকর্ড এডিট করার অনুমতি নেই। (Expense editing restricted.)')
                return get_safe_redirect()
            expense = get_object_or_404(Expense, id=expense_id)
            try:
                expense.title = request.POST.get('title', expense.title).strip()
                expense.category = request.POST.get('category', expense.category)
                expense.sub_category = request.POST.get('sub_category', '').strip()
                quantity_raw = request.POST.get('quantity', '').strip()
                expense.quantity = float(quantity_raw) if quantity_raw else None
                expense.unit = request.POST.get('unit', expense.unit or 'pcs').strip()
                expense.amount = float(request.POST.get('amount', expense.amount))
                if request.POST.get('expense_date'):
                    expense.expense_date = request.POST.get('expense_date')
                expense.payment_method = request.POST.get('payment_method', expense.payment_method)
                expense.receipt_reference = request.POST.get('receipt_reference', '').strip()
                expense.notes = request.POST.get('notes', '').strip()
                expense.save()
                messages.success(request, f'Expense record "#{expense.id} - {expense.title}" updated.')
            except Exception as e:
                messages.error(request, f'Failed to update expense: {str(e)}')
            return get_safe_redirect()

        # 3. DELETE EXPENSE
        elif action == 'delete_expense' or 'delete_expense' in request.POST:
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ খরচ রেকর্ড ডিলিট করতে পারবেন না। (Only Administrator can delete expense records.)')
                return get_safe_redirect()
            expense = get_object_or_404(Expense, id=expense_id)
            title = expense.title
            amount = expense.amount
            expense.delete()
            messages.success(request, f'Expense record "৳{amount} - {title}" has been deleted.')
            return get_safe_redirect()

    # Query & Filters
    expenses = Expense.objects.all()
    category_filter = request.GET.get('category', 'ALL')
    sub_category_filter = request.GET.get('sub_category', '').strip()
    search_query = request.GET.get('q', '').strip()

    if category_filter and category_filter != 'ALL':
        expenses = expenses.filter(
            Q(category=category_filter) |
            Q(category__iexact=category_filter) |
            Q(sub_category=category_filter) |
            Q(sub_category__icontains=category_filter)
        )

    if sub_category_filter:
        expenses = expenses.filter(
            Q(sub_category=sub_category_filter) |
            Q(sub_category__icontains=sub_category_filter)
        )

    if search_query:
        expenses = expenses.filter(
            Q(title__icontains=search_query) |
            Q(receipt_reference__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(sub_category__icontains=search_query)
        )

    # Financial Profit & Loss Calculations (Realized/Collected from Delivered/Paid orders)
    delivered_paid_orders = Order.objects.filter(Q(order_status='DELIVERED') | Q(payment_status='PAID'))
    total_expenses = Expense.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_revenue = delivered_paid_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    pipeline_revenue = Order.objects.filter(~Q(order_status__in=['DELIVERED', 'CANCELLED']) & ~Q(payment_status='PAID')).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    net_profit = float(total_revenue) - float(total_expenses)
    profit_margin = round((net_profit / float(total_revenue)) * 100, 1) if float(total_revenue) > 0 else 0

    first_of_month = today.replace(day=1)
    this_month_expenses = Expense.objects.filter(expense_date__gte=first_of_month).aggregate(Sum('amount'))['amount__sum'] or 0

    # Auto-seed standard categories if table is empty
    if ExpenseCategory.objects.count() == 0:
        default_seed = [
            ('Fresh Cucumbers & Veggies 🥒', 'RAW_MATERIAL', 'fa-carrot', 'Fresh cucumbers, garlic cloves, peppers, and raw produce.'),
            ('Fresh Fruits (ফলমূল) 🍎', 'FRUITS', 'fa-apple-whole', 'Fresh pineapples, raw mangoes, grapes, olives, and fruits for pickling.'),
            ('Glass Jars, Lids & Labels 🫙', 'PACKAGING', 'fa-jar', 'Food-grade glass jars, airtight gold metal lids, and stickers.'),
            ('Vinegar, Garlic & Whole Spices 🌿', 'SPICES_BRINE', 'fa-leaf', 'Pure cane vinegar, pickling salt, bay leaf, mustard seeds, and brine spices.'),
            ('Courier & Rider Delivery Cost 🚚', 'LOGISTICS', 'fa-truck-fast', 'Courier parcel shipping fees and direct delivery rider charges.'),
            ('Digital Ads & Marketing 📢', 'MARKETING', 'fa-bullhorn', 'Facebook page sponsored ads, boost campaigns, and promotion.'),
            ('Gas, Electricity & Kitchen Rent ⚡', 'UTILITIES', 'fa-bolt', 'Kitchen utilities, gas cylinders, and production space rent.'),
            ('Damaged & Broken Products Loss 💥', 'DAMAGE_LOSS', 'fa-burst', 'Financial loss from courier breakage, kitchen spills, and unsellable damaged jars.'),
            ('Operational & Miscellaneous 📋', 'OTHER', 'fa-receipt', 'Sanitizing supplies, kitchen tools, and operational expenses.'),
        ]
        for name, slug, icon, desc in default_seed:
            ExpenseCategory.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'icon': icon, 'description': desc}
            )

    # Category Breakdown for Chart.js
    category_totals = Expense.objects.values('category').annotate(cat_sum=Sum('amount')).order_by('-cat_sum')
    cat_labels_map = dict(Expense.CATEGORY_CHOICES)
    for cat in ExpenseCategory.objects.all():
        cat_labels_map[cat.slug] = cat.name
        cat_labels_map[cat.name] = cat.name
    
    chart_cat_labels = []
    chart_cat_data = []
    for item in category_totals:
        chart_cat_labels.append(cat_labels_map.get(item['category'], item['category']))
        chart_cat_data.append(float(item['cat_sum']))

    if not chart_cat_labels:
        chart_cat_labels = ['Glass Jars & Lids', 'Cucumbers', 'Vinegar & Spices', 'Courier & Logistics']
        chart_cat_data = [4500, 2200, 1850, 680]

    # Specific Expense Heads (Sub-category Breakdown)
    subcat_totals = Expense.objects.filter(sub_category__isnull=False).exclude(sub_category='').values('sub_category').annotate(sub_sum=Sum('amount')).order_by('-sub_sum')
    chart_subcat_labels = []
    chart_subcat_data = []
    top_expense_heads = []
    total_exp_float = float(total_expenses) if total_expenses else 1.0

    for item in subcat_totals:
        if item['sub_category']:
            chart_subcat_labels.append(str(item['sub_category']))
            chart_subcat_data.append(float(item['sub_sum'] or 0))

    for item in subcat_totals[:7]:
        if item['sub_category']:
            amt = float(item['sub_sum'] or 0)
            pct = round((amt / total_exp_float) * 100, 1)
            top_expense_heads.append({
                'name': str(item['sub_category']),
                'amount': amt,
                'percentage': pct
            })

    expense_chart_data = {
        'catLabels': chart_cat_labels,
        'catData': chart_cat_data,
        'subcatLabels': chart_subcat_labels[:12],
        'subcatData': chart_subcat_data[:12],
        'comparisonLabels': ['Gross Revenue (৳)', 'Total Costs (৳)', 'Net Profit (৳)'],
        'comparisonData': [float(total_revenue), float(total_expenses), max(0, net_profit)],
        'topExpenseHeads': top_expense_heads,
    }

    # Order expenses consistently
    expenses_ordered = expenses.order_by('-expense_date', '-created_at')

    # CSV Export for Expenses
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="pickpickles_expenses_{today.strftime("%Y%m%d")}.csv"'
        response.write('\ufeff'.encode('utf8'))
        writer = csv.writer(response)
        writer.writerow(['Date', 'Title', 'Main Category', 'Sub-Category', 'Quantity', 'Unit', 'Amount (BDT)', 'Payment Method', 'Receipt / Ref #', 'Notes'])
        for exp in expenses_ordered:
            writer.writerow([
                exp.expense_date.strftime('%Y-%m-%d') if exp.expense_date else '',
                exp.title,
                exp.category_display_name,
                exp.sub_category or '',
                exp.quantity if exp.quantity is not None else '',
                exp.unit or '',
                exp.amount,
                exp.get_payment_method_display(),
                exp.receipt_reference or '',
                exp.notes or '',
            ])
        return response

    # Pagination (Default: 10 per page)
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    paginator = Paginator(expenses_ordered, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    try:
        elided_page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        elided_page_range = paginator.page_range

    # Build parent categories & subcategory mapping for modal selections
    parent_categories = ExpenseCategory.objects.filter(parent__isnull=True).prefetch_related('subcategories')
    category_subcat_map = {}
    for p_cat in parent_categories:
        sub_list = [{'id': sub.id, 'name': sub.name, 'slug': sub.slug} for sub in p_cat.subcategories.all()]
        category_subcat_map[p_cat.slug] = sub_list
        category_subcat_map[p_cat.name] = sub_list

    context = {
        'expenses': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'dynamic_categories': ExpenseCategory.objects.all(),
        'parent_categories': parent_categories,
        'category_subcat_map_json': json.dumps(category_subcat_map),
        'unit_choices': Expense.UNIT_CHOICES,
        'category_choices': Expense.CATEGORY_CHOICES,
        'payment_choices': Expense.PAYMENT_CHOICES,
        'category_filter': category_filter,
        'sub_category_filter': sub_category_filter,
        'search_query': search_query,
        'dynamic_subcategories': ExpenseCategory.objects.filter(parent__isnull=False).select_related('parent').order_by('parent__name', 'name'),
        'total_expenses': total_expenses,
        'total_revenue': total_revenue,
        'pipeline_revenue': pipeline_revenue,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'this_month_expenses': this_month_expenses,
        'expense_count': paginator.count,
        'top_expense_heads': top_expense_heads,
        'expense_chart_json': json.dumps(expense_chart_data),
    }
    return render(request, 'dashboard/expenses.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def financial_statement(request):
    now = timezone.localtime(timezone.now())
    today = now.date()
    
    date_range = request.GET.get('range', 'ALL')
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    
    orders_qs = Order.objects.filter(~Q(order_status='CANCELLED'))
    expenses_qs = Expense.objects.all()
    
    period_title = "All Time (সর্বমোট পূর্ণাঙ্গ বিবরণী)"
    start_date = None
    end_date = None
    
    if date_range == 'THIS_MONTH':
        start_date = today.replace(day=1)
        end_date = today
        period_title = f"This Month ({start_date.strftime('%B %Y')})"
    elif date_range == 'LAST_MONTH':
        first_of_this_month = today.replace(day=1)
        last_day_prev_month = first_of_this_month - datetime.timedelta(days=1)
        start_date = last_day_prev_month.replace(day=1)
        end_date = last_day_prev_month
        period_title = f"Last Month ({start_date.strftime('%B %Y')})"
    elif date_range == 'THIS_YEAR':
        start_date = today.replace(month=1, day=1)
        end_date = today
        period_title = f"This Year ({today.year})"
    elif date_range == 'CUSTOM' and start_date_str and end_date_str:
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            period_title = f"{start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"
        except ValueError:
            pass

    if start_date and end_date:
        orders_qs = orders_qs.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        expenses_qs = expenses_qs.filter(expense_date__gte=start_date, expense_date__lte=end_date)

    # 1. Income Metrics (Only DELIVERED or PAID orders count as Realized Inflow)
    delivered_qs = orders_qs.filter(Q(order_status='DELIVERED') | Q(payment_status='PAID'))
    pipeline_qs = orders_qs.filter(~Q(order_status__in=['DELIVERED', 'CANCELLED']) & ~Q(payment_status='PAID'))
    
    gross_revenue = float(delivered_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    product_sales = float(delivered_qs.aggregate(Sum('subtotal'))['subtotal__sum'] or 0)
    delivery_fees = float(delivered_qs.aggregate(Sum('delivery_fee'))['delivery_fee__sum'] or 0)
    pipeline_revenue = float(pipeline_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    
    orders_count = delivered_qs.count()
    jars_sold = OrderItem.objects.filter(order__in=delivered_qs).aggregate(Sum('quantity'))['quantity__sum'] or 0
    
    # Payment breakdown from delivered/collected orders
    cod_revenue = float(delivered_qs.filter(payment_method='COD').aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    bkash_revenue = float(delivered_qs.filter(payment_method='BKASH').aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    nagad_revenue = float(delivered_qs.filter(payment_method='NAGAD').aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    
    # 2. Expense Metrics
    total_expenses = float(expenses_qs.aggregate(Sum('amount'))['amount__sum'] or 0)
    expenses_count = expenses_qs.count()
    
    cat_summary = expenses_qs.values('category').annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    cat_map = dict(Expense.CATEGORY_CHOICES)
    for ec in ExpenseCategory.objects.all():
        cat_map[ec.slug] = ec.name
        cat_map[ec.name] = ec.name
        
    ensure_expense_taxonomy_and_allocation_synced()
    
    cat_expenses = []
    for item in cat_summary:
        cat_name = cat_map.get(item['category'], item['category'])
        sub_items = list(
            expenses_qs.filter(category=item['category'])
            .filter(sub_category__isnull=False)
            .exclude(sub_category='')
            .values('sub_category')
            .annotate(sub_total=Sum('amount'), sub_count=Count('id'))
            .order_by('-sub_total')
        )
        cat_expenses.append({
            'name': cat_name,
            'category_code': item['category'],
            'amount': float(item['total']),
            'count': item['count'],
            'percentage': round((float(item['total']) / total_expenses) * 100, 1) if total_expenses > 0 else 0,
            'sub_items': sub_items,
        })

    # 3. Net Profit / Loss
    net_profit = gross_revenue - total_expenses
    profit_margin = round((net_profit / gross_revenue) * 100, 1) if gross_revenue > 0 else 0
    is_profitable = net_profit >= 0

    # 4. Combined Transaction Stream (Delivered Orders + Expenses in chronological order)
    combined_transactions = []
    
    for order in delivered_qs.order_by('-created_at'):
        combined_transactions.append({
            'date': order.created_at,
            'is_income': True,
            'type': 'ORDER_REVENUE',
            'type_display': 'Collected Inflow (আদায়কৃত আয়)',
            'title': f"Order #{order.order_number} - {order.customer_name}",
            'category': f"{order.delivery_city} ({order.get_delivery_zone_display()})",
            'payment_method': order.get_payment_method_display(),
            'ref': order.order_number,
            'amount': float(order.total_amount),
            'url': reverse('dashboard:order_detail', args=[order.order_number]),
        })

    for exp in expenses_qs.order_by('-expense_date', '-created_at'):
        combined_transactions.append({
            'date': timezone.make_aware(datetime.datetime.combine(exp.expense_date, datetime.time.min)) if timezone.is_naive(datetime.datetime.combine(exp.expense_date, datetime.time.min)) else exp.created_at,
            'is_income': False,
            'type': 'EXPENSE_COST',
            'type_display': 'Expense Outflow (ব্যয়)',
            'title': exp.title,
            'category': exp.category_display_name,
            'payment_method': exp.get_payment_method_display(),
            'ref': exp.receipt_reference or f"EXP-{exp.id}",
            'amount': float(exp.amount),
            'url': None,
        })

    # Sort combined transactions by date descending
    combined_transactions.sort(key=lambda x: x['date'], reverse=True)

    # Pagination (Default: 10 per page)
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except (ValueError, TypeError):
        per_page = 10

    paginator = Paginator(combined_transactions, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    try:
        elided_page_range = paginator.get_elided_page_range(number=page_obj.number, on_each_side=2, on_ends=1)
    except Exception:
        elided_page_range = paginator.page_range

    context = {
        'period_title': period_title,
        'date_range': date_range,
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'gross_revenue': gross_revenue,
        'product_sales': product_sales,
        'delivery_fees': delivery_fees,
        'pipeline_revenue': pipeline_revenue,
        'orders_count': orders_count,
        'jars_sold': jars_sold,
        'cod_revenue': cod_revenue,
        'bkash_revenue': bkash_revenue,
        'nagad_revenue': nagad_revenue,
        'total_expenses': total_expenses,
        'expenses_count': expenses_count,
        'cat_expenses': cat_expenses,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'is_profitable': is_profitable,
        'transactions': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'total_transactions_count': paginator.count,
        'now': now,
    }
    return render(request, 'dashboard/statement.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def financial_statement_print(request):
    """Standalone, clean printable view for saving as PDF or printing on paper."""
    now = timezone.localtime(timezone.now())
    today = now.date()
    
    date_range = request.GET.get('range', 'ALL')
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    
    orders_qs = Order.objects.filter(~Q(order_status='CANCELLED'))
    expenses_qs = Expense.objects.all()
    
    period_title = "All Time (সর্বমোট বিবরণী)"
    start_date = None
    end_date = None
    
    if date_range == 'THIS_MONTH':
        start_date = today.replace(day=1)
        end_date = today
        period_title = f"This Month ({start_date.strftime('%B %Y')})"
    elif date_range == 'LAST_MONTH':
        first_of_this_month = today.replace(day=1)
        last_day_prev_month = first_of_this_month - datetime.timedelta(days=1)
        start_date = last_day_prev_month.replace(day=1)
        end_date = last_day_prev_month
        period_title = f"Last Month ({start_date.strftime('%B %Y')})"
    elif date_range == 'THIS_YEAR':
        start_date = today.replace(month=1, day=1)
        end_date = today
        period_title = f"This Year ({today.year})"
    elif date_range == 'CUSTOM' and start_date_str and end_date_str:
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            period_title = f"{start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"
        except ValueError:
            pass

    if start_date and end_date:
        orders_qs = orders_qs.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
        expenses_qs = expenses_qs.filter(expense_date__gte=start_date, expense_date__lte=end_date)

    # Realized / Delivered / Paid orders only
    delivered_qs = orders_qs.filter(Q(order_status='DELIVERED') | Q(payment_status='PAID'))
    gross_revenue = float(delivered_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    product_sales = float(delivered_qs.aggregate(Sum('subtotal'))['subtotal__sum'] or 0)
    delivery_fees = float(delivered_qs.aggregate(Sum('delivery_fee'))['delivery_fee__sum'] or 0)
    orders_count = delivered_qs.count()
    jars_sold = OrderItem.objects.filter(order__in=delivered_qs).aggregate(Sum('quantity'))['quantity__sum'] or 0
    
    cod_revenue = float(delivered_qs.filter(payment_method='COD').aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    bkash_revenue = float(delivered_qs.filter(payment_method='BKASH').aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    nagad_revenue = float(delivered_qs.filter(payment_method='NAGAD').aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    
    total_expenses = float(expenses_qs.aggregate(Sum('amount'))['amount__sum'] or 0)
    expenses_count = expenses_qs.count()
    
    cat_summary = expenses_qs.values('category').annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    cat_map = dict(Expense.CATEGORY_CHOICES)
    for ec in ExpenseCategory.objects.all():
        cat_map[ec.slug] = ec.name
        cat_map[ec.name] = ec.name
        
    ensure_expense_taxonomy_and_allocation_synced()

    cat_expenses = []
    for item in cat_summary:
        cat_name = cat_map.get(item['category'], item['category'])
        sub_items = list(
            expenses_qs.filter(category=item['category'])
            .filter(sub_category__isnull=False)
            .exclude(sub_category='')
            .values('sub_category')
            .annotate(sub_total=Sum('amount'), sub_count=Count('id'))
            .order_by('-sub_total')
        )
        cat_expenses.append({
            'name': cat_name,
            'amount': float(item['total']),
            'count': item['count'],
            'percentage': round((float(item['total']) / total_expenses) * 100, 1) if total_expenses > 0 else 0,
            'sub_items': sub_items,
        })

    net_profit = gross_revenue - total_expenses
    profit_margin = round((net_profit / gross_revenue) * 100, 1) if gross_revenue > 0 else 0
    is_profitable = net_profit >= 0

    combined_transactions = []
    for order in delivered_qs.order_by('-created_at'):
        combined_transactions.append({
            'date': order.created_at,
            'is_income': True,
            'type_display': 'Sales Inflow (আদায়কৃত আয়)',
            'title': f"Order #{order.order_number} - {order.customer_name}",
            'category': f"{order.delivery_city} ({order.get_delivery_zone_display()})",
            'payment_method': order.get_payment_method_display(),
            'ref': order.order_number,
            'amount': float(order.total_amount),
        })

    for exp in expenses_qs.order_by('-expense_date', '-created_at'):
        combined_transactions.append({
            'date': timezone.make_aware(datetime.datetime.combine(exp.expense_date, datetime.time.min)) if timezone.is_naive(datetime.datetime.combine(exp.expense_date, datetime.time.min)) else exp.created_at,
            'is_income': False,
            'type_display': 'Expense Outflow (ব্যয়)',
            'title': exp.title,
            'category': exp.category_display_name,
            'payment_method': exp.get_payment_method_display(),
            'ref': exp.receipt_reference or f"EXP-{exp.id}",
            'amount': float(exp.amount),
        })

    combined_transactions.sort(key=lambda x: x['date'], reverse=True)

    context = {
        'period_title': period_title,
        'gross_revenue': gross_revenue,
        'product_sales': product_sales,
        'delivery_fees': delivery_fees,
        'orders_count': orders_count,
        'jars_sold': jars_sold,
        'cod_revenue': cod_revenue,
        'bkash_revenue': bkash_revenue,
        'nagad_revenue': nagad_revenue,
        'total_expenses': total_expenses,
        'expenses_count': expenses_count,
        'cat_expenses': cat_expenses,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'is_profitable': is_profitable,
        'transactions': combined_transactions,
        'now': now,
    }
    return render(request, 'dashboard/statement_print.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def business_profitability(request):
    """
    Business Profitability & Smart Pricing Intelligence:
    Calculates cost-per-jar, unit economics, recommended selling prices for targeted profit margins,
    break-even volume, and interactive feasibility analysis based on real expenses & production data.
    """
    # 1. Production & Sales Volume
    # Only strictly DELIVERED or PAID orders count as sold (64 jars)
    delivered_paid_orders = Order.objects.filter(
        is_deleted=False
    ).filter(
        Q(order_status='DELIVERED') | Q(payment_status='PAID')
    ).exclude(
        order_status='CANCELLED'
    )
    
    # Shipping Out (In-Transit) orders (11 jars) - tracked separately
    shipping_out_orders = Order.objects.filter(
        is_deleted=False,
        order_status='OUT_FOR_DELIVERY'
    ).exclude(
        payment_status='PAID'
    )
    
    # Unshipped Queue orders (Pending / Confirmed / Packing)
    unshipped_queue_orders = Order.objects.filter(
        is_deleted=False,
        order_status__in=['PENDING', 'CONFIRMED', 'PACKING']
    ).exclude(
        payment_status='PAID'
    )

    # Shipping Out & Packing orders (already deducted from physical stock)
    packed_in_transit_orders = Order.objects.filter(
        is_deleted=False,
        order_status__in=['PACKING', 'OUT_FOR_DELIVERY']
    ).exclude(
        payment_status='PAID'
    )

    jars_delivered = OrderItem.objects.filter(order__in=delivered_paid_orders).aggregate(Sum('quantity'))['quantity__sum'] or 0
    shipping_jars = OrderItem.objects.filter(order__in=shipping_out_orders).aggregate(Sum('quantity'))['quantity__sum'] or 0
    packed_in_transit_jars = OrderItem.objects.filter(order__in=packed_in_transit_orders).aggregate(Sum('quantity'))['quantity__sum'] or 0
    pipeline_jars = OrderItem.objects.filter(order__in=unshipped_queue_orders).aggregate(Sum('quantity'))['quantity__sum'] or 0

    # Realized & Pipeline Revenue
    realized_revenue = float(delivered_paid_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    realized_product_sales = float(delivered_paid_orders.aggregate(Sum('subtotal'))['subtotal__sum'] or 0)
    realized_delivery_fees = float(delivered_paid_orders.aggregate(Sum('delivery_fee'))['delivery_fee__sum'] or 0)
    shipping_revenue = float(shipping_out_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    pipeline_revenue = float(unshipped_queue_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
    delivered_orders_count = delivered_paid_orders.count()

    # Total Sold Jars is strictly Delivered Jars (delivered howar por e dekhao)
    jars_sold_total = jars_delivered

    # Current Catalog & Physical Stock
    all_products = list(Product.objects.select_related('category').all().order_by('name'))
    total_physical_stock = sum(p.stock_count for p in all_products)
    catalog_product_count = len(all_products)

    # Average, Min & Max selling price in store
    valid_prices = [float(p.price_bdt) for p in all_products if p.price_bdt and p.price_bdt > 0]
    avg_store_price = round(sum(valid_prices) / len(valid_prices), 2) if valid_prices else 400.0
    min_store_price = round(min(valid_prices), 0) if valid_prices else 0
    max_store_price = round(max(valid_prices), 0) if valid_prices else 0

    # Total Accounted Production Batch Volume (Physical Stock + Packed/In-Transit + Delivered Jars)
    batch_volume = total_physical_stock + packed_in_transit_jars + jars_delivered
    effective_volume = max(1, batch_volume)

    # 2. Expenses Breakdown
    ensure_expense_taxonomy_and_allocation_synced()
    total_expenses = float(Expense.objects.aggregate(Sum('amount'))['amount__sum'] or 0)

    # Build parent category resolver map for robust COGS allocation
    cat_root_map = {}
    for ec in ExpenseCategory.objects.select_related('parent').all():
        root = ec.parent if ec.parent else ec
        cat_root_map[ec.slug.upper()] = root.slug.upper()
        cat_root_map[ec.name.upper()] = root.slug.upper()

    # Categorize expenses
    cat_expenses = Expense.objects.values('category').annotate(total=Sum('amount'), count=Count('id'))
    
    packaging_expense = 0.0
    raw_material_expense = 0.0
    spices_brine_expense = 0.0
    logistics_expense = 0.0
    marketing_expense = 0.0
    utilities_rent_expense = 0.0
    other_expense = 0.0

    for row in cat_expenses:
        raw_cat = (row['category'] or '').upper()
        cat = cat_root_map.get(raw_cat, raw_cat)
        amt = float(row['total'] or 0)
        if any(k in cat for k in ['PACKAGING', 'JAR', 'BOTTLE', 'LABEL', 'LID']):
            packaging_expense += amt
        elif any(k in cat for k in ['RAW_MATERIAL', 'CUCUMBER', 'VEGGIE', 'FRUIT', 'MANGO', 'EGG', 'BEETROOT', 'CARROT']):
            raw_material_expense += amt
        elif any(k in cat for k in ['SPICES_BRINE', 'HERB', 'SALT', 'SUGAR', 'WATER', 'VINEGAR', 'SPICE']):
            spices_brine_expense += amt
        elif any(k in cat for k in ['LOGISTICS', 'COURIER', 'RIDER', 'DELIVERY']):
            logistics_expense += amt
        elif any(k in cat for k in ['MARKETING', 'AD', 'FACEBOOK', 'BOOST', 'PROMOTION']):
            marketing_expense += amt
        elif any(k in cat for k in ['UTILITIES', 'GAS', 'ELECTRICITY', 'RENT']):
            utilities_rent_expense += amt
        else:
            other_expense += amt

    # Direct Production Cost (COGS) & Detailed Overhead Heads
    direct_cogs = packaging_expense + raw_material_expense + spices_brine_expense
    utilities_other_expense = utilities_rent_expense + other_expense
    indirect_overhead = logistics_expense + marketing_expense + utilities_other_expense

    # Per Jar Unit Economics (Batch-allocated)
    cogs_per_jar = round(direct_cogs / effective_volume, 2)
    packaging_per_jar = round(packaging_expense / effective_volume, 2)
    raw_produce_per_jar = round(raw_material_expense / effective_volume, 2)
    spices_per_jar = round(spices_brine_expense / effective_volume, 2)
    logistics_per_jar = round(logistics_expense / effective_volume, 2)
    marketing_per_jar = round(marketing_expense / effective_volume, 2)
    utilities_other_per_jar = round(utilities_other_expense / effective_volume, 2)
    overhead_per_jar = round(indirect_overhead / effective_volume, 2)
    
    total_cost_per_jar = round(total_expenses / effective_volume, 2) if effective_volume > 0 else 0.0

    # Pricing Models based on Unit Cost
    # Formula: Price = Cost / (1 - Margin%)
    pricing_matrix = []
    margin_tiers = [
        {'name': 'Break-Even (আসল খরচ)', 'margin': 0, 'desc': 'জিরো প্রফিট - শুধু আসল খরচ উঠে আসবে'},
        {'name': 'Wholesale Margin (২০% লাভ)', 'margin': 20, 'desc': 'পাইকারি বা বাল্ক অর্ডারের প্রফিট রেঞ্জ'},
        {'name': 'Standard Retail (৩৫% লাভ)', 'margin': 35, 'desc': 'ফুড রিটেইল ইন্ডাস্ট্রির প্রচলিত রেঞ্জ'},
        {'name': 'Target Healthy Margin (৫০% লাভ)', 'margin': 50, 'desc': 'ব্র্যান্ড গ্রোথ ও স্থায়ী প্রফিটের জন্য আদর্শ'},
        {'name': 'Premium Artisan (৬৫% লাভ)', 'margin': 65, 'desc': 'প্রিমিয়াম অর্গানিক হোমমেড ক্যাটাগরি'},
        {'name': 'Super Premium Margin (৭৫% লাভ)', 'margin': 75, 'desc': 'হাই-মার্জিন ব্র্যান্ড স্ট্যান্ডার্ড'},
    ]

    for tier in margin_tiers:
        m = tier['margin']
        if m == 0:
            rec_price = total_cost_per_jar
        else:
            rec_price = total_cost_per_jar / (1 - (m / 100))
        
        profit_per_jar = rec_price - total_cost_per_jar
        pricing_matrix.append({
            'tier_name': tier['name'],
            'margin_pct': m,
            'desc': tier['desc'],
            'recommended_price': round(rec_price, 0),
            'profit_per_jar': round(profit_per_jar, 0),
        })

    # Compare current store average price against cost
    current_profit_per_jar = round(avg_store_price - total_cost_per_jar, 2)
    current_margin_pct = round((current_profit_per_jar / avg_store_price) * 100, 1) if avg_store_price > 0 else 0

    # Break-Even Sales Volume Calculation:
    # How many jars at current average price are needed to cover 100% of all expenses?
    break_even_jars = int(math.ceil(total_expenses / avg_store_price)) if avg_store_price > 0 else 0
    jars_remaining_to_breakeven = max(0, break_even_jars - jars_sold_total)
    breakeven_progress_pct = min(100, round((jars_sold_total / break_even_jars) * 100, 1)) if break_even_jars > 0 else 100

    # Per-product Delivered Sales & Active Queue Demand
    delivered_by_prod = {}
    for row in OrderItem.objects.filter(order__in=delivered_paid_orders).values('product_id', 'product_name').annotate(
        sold_qty=Sum('quantity'),
        sold_revenue=Sum('total_price')
    ):
        pid = row['product_id']
        if pid:
            delivered_by_prod[pid] = {
                'qty': row['sold_qty'] or 0,
                'revenue': float(row['sold_revenue'] or 0),
            }

    active_queue_by_prod = {}
    for row in OrderItem.objects.filter(
        order__is_deleted=False,
        order__order_status__in=['PENDING', 'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY']
    ).exclude(order__payment_status='PAID').values('product_id').annotate(q_qty=Sum('quantity')):
        if row['product_id']:
            active_queue_by_prod[row['product_id']] = row['q_qty'] or 0

    # Price History mapping per product
    all_ph = list(PriceHistory.objects.order_by('created_at', 'id'))
    ph_map = {}
    for ph in all_ph:
        ph_map.setdefault(ph.product_id, []).append(ph)

    # Product-wise profitability mapping
    product_profit_list = []
    total_stock_value = 0.0
    total_stock_profit_potential = 0.0
    total_realized_unit_profit = 0.0

    for prod in all_products:
        p_price = float(prod.price_bdt or 0)
        p_profit = round(p_price - total_cost_per_jar, 2)
        p_margin = round((p_profit / p_price) * 100, 1) if p_price > 0 else 0
        s_val = round(p_price * prod.stock_count, 2)
        s_prof = round(p_profit * prod.stock_count, 2)

        sold_stat = delivered_by_prod.get(prod.id, {'qty': 0, 'revenue': 0.0})
        sold_qty = sold_stat['qty']
        sold_rev = round(sold_stat['revenue'], 2)
        realized_prod_profit = round(sold_rev - (sold_qty * total_cost_per_jar), 2)
        queue_qty = active_queue_by_prod.get(prod.id, 0)

        p_hist = ph_map.get(prod.id, [])
        first_price = float(p_hist[0].old_price) if p_hist else p_price
        inc_count = sum(1 for h in p_hist if h.change_type == 'INCREASE')

        total_stock_value += s_val
        total_stock_profit_potential += s_prof
        total_realized_unit_profit += realized_prod_profit

        product_profit_list.append({
            'product': prod,
            'price': p_price,
            'first_price': first_price,
            'increase_count': inc_count,
            'cost': total_cost_per_jar,
            'cogs': cogs_per_jar,
            'overhead': overhead_per_jar,
            'profit': p_profit,
            'margin': p_margin,
            'sold_qty': sold_qty,
            'sold_revenue': sold_rev,
            'realized_profit': realized_prod_profit,
            'queue_qty': queue_qty,
            'stock': prod.stock_count,
            'stock_value': s_val,
            'stock_profit_potential': s_prof,
        })

    total_stock_value = round(total_stock_value, 2)
    total_stock_profit_potential = round(total_stock_profit_potential, 2)
    total_realized_unit_profit = round(total_realized_unit_profit, 2)
    realized_net_profit = round(realized_revenue - total_expenses, 2)
    realized_recovery_pct = min(100, round((realized_revenue / total_expenses) * 100, 1)) if total_expenses > 0 else 100

    # Potential Batch Revenue & Profit when full batch (realized + in-transit + current stock) is sold out:
    batch_projected_revenue = round(realized_revenue + shipping_revenue + total_stock_value, 2)
    if batch_projected_revenue <= 0:
        batch_projected_revenue = round(effective_volume * avg_store_price, 2)
    batch_projected_profit = round(batch_projected_revenue - total_expenses, 2)

    # Cost percentages
    cost_percentages = {
        'packaging': round((packaging_expense / total_expenses * 100), 1) if total_expenses > 0 else 0,
        'raw_material': round((raw_material_expense / total_expenses * 100), 1) if total_expenses > 0 else 0,
        'spices_brine': round((spices_brine_expense / total_expenses * 100), 1) if total_expenses > 0 else 0,
        'logistics': round((logistics_expense / total_expenses * 100), 1) if total_expenses > 0 else 0,
        'marketing': round((marketing_expense / total_expenses * 100), 1) if total_expenses > 0 else 0,
        'utilities_other': round((utilities_other_expense / total_expenses * 100), 1) if total_expenses > 0 else 0,
        'overhead': round((indirect_overhead / total_expenses * 100), 1) if total_expenses > 0 else 0,
        'direct_cogs_pct': round((direct_cogs / total_expenses * 100), 1) if total_expenses > 0 else 0,
    }

    context = {
        'total_jars_sold': jars_sold_total,
        'jars_delivered': jars_delivered,
        'delivered_orders_count': delivered_orders_count,
        'shipping_jars': shipping_jars,
        'packed_in_transit_jars': packed_in_transit_jars,
        'pipeline_jars': pipeline_jars,
        'realized_revenue': realized_revenue,
        'realized_product_sales': realized_product_sales,
        'realized_delivery_fees': realized_delivery_fees,
        'shipping_revenue': shipping_revenue,
        'pipeline_revenue': pipeline_revenue,
        'realized_net_profit': realized_net_profit,
        'realized_recovery_pct': realized_recovery_pct,
        'total_physical_stock': total_physical_stock,
        'total_stock_value': total_stock_value,
        'total_stock_profit_potential': total_stock_profit_potential,
        'total_realized_unit_profit': total_realized_unit_profit,
        'batch_volume': batch_volume,
        'total_expenses': total_expenses,
        'direct_cogs': direct_cogs,
        'indirect_overhead': indirect_overhead,
        'cogs_per_jar': cogs_per_jar,
        'total_cost_per_jar': total_cost_per_jar,
        'packaging_per_jar': packaging_per_jar,
        'raw_produce_per_jar': raw_produce_per_jar,
        'spices_per_jar': spices_per_jar,
        'logistics_per_jar': logistics_per_jar,
        'marketing_per_jar': marketing_per_jar,
        'utilities_other_per_jar': utilities_other_per_jar,
        'overhead_per_jar': overhead_per_jar,
        'packaging_expense': packaging_expense,
        'raw_material_expense': raw_material_expense,
        'spices_brine_expense': spices_brine_expense,
        'logistics_expense': logistics_expense,
        'marketing_expense': marketing_expense,
        'utilities_other_expense': utilities_other_expense,
        'indirect_overhead_expense': indirect_overhead,
        'cost_percentages': cost_percentages,
        'avg_store_price': avg_store_price,
        'min_store_price': min_store_price,
        'max_store_price': max_store_price,
        'current_profit_per_jar': current_profit_per_jar,
        'current_margin_pct': current_margin_pct,
        'pricing_matrix': pricing_matrix,
        'break_even_jars': break_even_jars,
        'jars_remaining_to_breakeven': jars_remaining_to_breakeven,
        'breakeven_progress_pct': breakeven_progress_pct,
        'batch_projected_revenue': batch_projected_revenue,
        'batch_projected_profit': batch_projected_profit,
        'product_profit_list': product_profit_list,
        'all_products': all_products,
    }
    return render(request, 'dashboard/business_profitability.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def admin_users_manager(request):
    if not request.user.is_superuser:
        messages.error(request, 'Permission Denied: শুধুমাত্র অ্যাডমিনিস্ট্রেটরদের জন্য আইডি ও সিকিউরিটি ব্যবস্থাপনা উন্মুক্ত। (Administrator privileges required.)')
        return redirect('dashboard:index')

    security_config = DashboardSecurityConfig.get_config()
    users = User.objects.all().order_by('-is_superuser', '-is_staff', '-date_joined')

    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')

        # 1. CREATE ADMIN / STAFF ID
        if action == 'create_user':
            username = request.POST.get('username', '').strip()
            full_name = request.POST.get('full_name', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '').strip()
            employee_id = request.POST.get('employee_id', '').strip()
            phone = request.POST.get('phone', '').strip()
            notes = request.POST.get('notes', '').strip()
            role = request.POST.get('role', 'staff')
            can_delete = request.POST.get('can_delete') == 'on'
            can_edit = request.POST.get('can_edit') == 'on'
            can_dispatch = request.POST.get('can_dispatch') == 'on'

            is_superuser = (role == 'admin')
            is_staff = (role in ['admin', 'staff'])

            if not username or not password:
                messages.error(request, 'Username এবং Password আবশ্যক।')
            elif User.objects.filter(username__iexact=username).exists():
                messages.error(request, f'Username "{username}" ইতিমধ্যেই বিদ্যমান। অন্য ইউজারনেম নির্বাচন করুন।')
            else:
                new_user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=full_name,
                    is_staff=is_staff,
                    is_superuser=is_superuser
                )
                StaffSecurityProfile.objects.create(
                    user=new_user,
                    employee_id=employee_id,
                    phone=phone,
                    can_delete_records=can_delete if not is_superuser else True,
                    can_edit_records=can_edit if not is_superuser else True,
                    can_dispatch_courier=can_dispatch if not is_superuser else True,
                    notes=notes
                )
                perm_summary = []
                if can_delete or is_superuser:
                    perm_summary.append("ডিলিট")
                if can_edit or is_superuser:
                    perm_summary.append("এডিট")
                if can_dispatch or is_superuser:
                    perm_summary.append("কুরিয়ার বুকিং")
                perm_text = ", ".join(perm_summary) if perm_summary else "কোন বিশেষ অ্যাক্সেস নেই (Restricted)"
                messages.success(request, f'নতুন আইডি "{username}" সফলভাবে তৈরি করা হয়েছে! (অনুমোদিত: {perm_text})')
            return redirect('dashboard:admin_users')

        # 2. UPDATE GLOBAL SECURITY & RESTRICTION POLICIES
        elif action == 'update_security_config':
            strict_mode = request.POST.get('strict_admin_only_delete') == 'on'
            staff_override = request.POST.get('allow_staff_delete_override') == 'on'
            strict_edit = request.POST.get('strict_admin_only_edit') == 'on'
            strict_dispatch = request.POST.get('strict_admin_only_dispatch') == 'on'

            security_config.strict_admin_only_delete = strict_mode
            security_config.allow_staff_delete_override = staff_override
            security_config.strict_admin_only_edit = strict_edit
            security_config.strict_admin_only_dispatch = strict_dispatch
            security_config.updated_by = request.user
            security_config.save()

            messages.success(request, 'নিরাপত্তা পলিসি সফলভাবে সংরক্ষিত ও কার্যকর করা হয়েছে!')
            return redirect('dashboard:admin_users')

        # 3. TOGGLE PER-USER DELETE PERMISSION
        elif action == 'toggle_user_delete':
            target_user = get_object_or_404(User, id=user_id)
            profile, _ = StaffSecurityProfile.objects.get_or_create(user=target_user)
            profile.can_delete_records = not profile.can_delete_records
            profile.save()
            st_text = "অনুমোদিত (Allowed)" if profile.can_delete_records else "নিষিদ্ধ (Restricted)"
            messages.success(request, f'ইউজার {target_user.username}-এর জন্য ডিলিট অনুমতি এখন {st_text}।')
            return redirect('dashboard:admin_users')

        # 3B. TOGGLE PER-USER EDIT PERMISSION
        elif action == 'toggle_user_edit':
            target_user = get_object_or_404(User, id=user_id)
            profile, _ = StaffSecurityProfile.objects.get_or_create(user=target_user)
            profile.can_edit_records = not profile.can_edit_records
            profile.save()
            st_text = "অনুমোদিত (Allowed)" if profile.can_edit_records else "নিষিদ্ধ (Restricted)"
            messages.success(request, f'ইউজার {target_user.username}-এর জন্য এডিট অনুমতি এখন {st_text}।')
            return redirect('dashboard:admin_users')

        # 3C. TOGGLE PER-USER DISPATCH PERMISSION
        elif action == 'toggle_user_dispatch':
            target_user = get_object_or_404(User, id=user_id)
            profile, _ = StaffSecurityProfile.objects.get_or_create(user=target_user)
            profile.can_dispatch_courier = not profile.can_dispatch_courier
            profile.save()
            st_text = "অনুমোদিত (Allowed)" if profile.can_dispatch_courier else "নিষিদ্ধ (Restricted)"
            messages.success(request, f'ইউজার {target_user.username}-এর জন্য কুরিয়ারে পাঠানো অনুমতি এখন {st_text}।')
            return redirect('dashboard:admin_users')

        # 4. EDIT USER / ID DETAILS
        elif action == 'edit_user':
            target_user = get_object_or_404(User, id=user_id)
            full_name = request.POST.get('full_name', '').strip()
            email = request.POST.get('email', '').strip()
            employee_id = request.POST.get('employee_id', '').strip()
            phone = request.POST.get('phone', '').strip()
            notes = request.POST.get('notes', '').strip()
            role = request.POST.get('role', 'staff')
            can_delete = request.POST.get('can_delete') == 'on'
            can_edit = request.POST.get('can_edit') == 'on'
            can_dispatch = request.POST.get('can_dispatch') == 'on'

            target_user.first_name = full_name
            target_user.email = email
            if target_user != request.user:
                if role == 'admin':
                    target_user.is_superuser = True
                    target_user.is_staff = True
                elif role == 'staff':
                    target_user.is_superuser = False
                    target_user.is_staff = True
                else:
                    target_user.is_superuser = False
                    target_user.is_staff = False
            target_user.save()

            profile, _ = StaffSecurityProfile.objects.get_or_create(user=target_user)
            profile.employee_id = employee_id
            profile.phone = phone
            profile.notes = notes
            profile.can_delete_records = can_delete if not target_user.is_superuser else True
            profile.can_edit_records = can_edit if not target_user.is_superuser else True
            profile.can_dispatch_courier = can_dispatch if not target_user.is_superuser else True
            profile.save()

            messages.success(request, f'আইডি "{target_user.username}"-এর বিবরণ ও পারমিশন সফলভাবে আপডেট করা হয়েছে।')
            return redirect('dashboard:admin_users')

        # 5. CHANGE USER PASSWORD
        elif action == 'change_password':
            target_user = get_object_or_404(User, id=user_id)
            new_pw = request.POST.get('new_password', '').strip()
            if new_pw:
                target_user.set_password(new_pw)
                target_user.save()
                messages.success(request, f'{target_user.username}-এর পাসওয়ার্ড সফলভাবে পরিবর্তিত হয়েছে।')
            else:
                messages.error(request, 'Password খালি রাখা যাবে না।')
            return redirect('dashboard:admin_users')

        # 6. TOGGLE STAFF STATUS
        elif action == 'toggle_staff':
            target_user = get_object_or_404(User, id=user_id)
            if target_user == request.user and target_user.is_superuser:
                messages.error(request, 'আপনি নিজের সুপারইউজার অ্যাক্সেস বাতিল করতে পারবেন না।')
            else:
                target_user.is_staff = not target_user.is_staff
                target_user.save()
                messages.success(request, f'{target_user.username}-এর Staff রোল পরিবর্তিত হয়েছে।')
            return redirect('dashboard:admin_users')

        # 7. DELETE USER ACCOUNT
        elif action == 'delete_user':
            target_user = get_object_or_404(User, id=user_id)
            if target_user == request.user:
                messages.error(request, 'আপনি নিজের আইডি ডিলিট করতে পারবেন না।')
            else:
                u_name = target_user.username
                target_user.delete()
                messages.success(request, f'আইডি অ্যাকাউন্ট "{u_name}" সফলভাবে মুছে ফেলা হয়েছে।')
            return redirect('dashboard:admin_users')

    # Prepare user objects with security profiles
    user_list = []
    delete_permitted_count = 0
    edit_permitted_count = 0
    dispatch_permitted_count = 0
    for u in users:
        profile, _ = StaffSecurityProfile.objects.get_or_create(user=u)
        effective_delete = u.is_superuser or (
            not security_config.strict_admin_only_delete and
            security_config.allow_staff_delete_override and
            profile.can_delete_records
        )
        effective_edit = u.is_superuser or (
            not security_config.strict_admin_only_edit and
            profile.can_edit_records
        )
        effective_dispatch = u.is_superuser or (
            not security_config.strict_admin_only_dispatch and
            profile.can_dispatch_courier
        )
        if effective_delete:
            delete_permitted_count += 1
        if effective_edit:
            edit_permitted_count += 1
        if effective_dispatch:
            dispatch_permitted_count += 1

        user_list.append({
            'user': u,
            'profile': profile,
            'effective_delete': effective_delete,
            'effective_edit': effective_edit,
            'effective_dispatch': effective_dispatch,
        })

    context = {
        'user_list': user_list,
        'security_config': security_config,
        'total_users': users.count(),
        'staff_count': users.filter(is_staff=True).count(),
        'superuser_count': users.filter(is_superuser=True).count(),
        'delete_permitted_count': delete_permitted_count,
        'edit_permitted_count': edit_permitted_count,
        'dispatch_permitted_count': dispatch_permitted_count,
        'orders_count': Order.objects.count(),
        'products_count': Product.objects.count(),
        'categories_count': Category.objects.count(),
        'reviews_count': Review.objects.count(),
    }
    return render(request, 'dashboard/admin_users.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def pickle_categories_manager(request):
    categories = Category.objects.all().annotate(product_count=Count('products')).order_by('name')

    if request.method == 'POST':
        action = request.POST.get('action')
        cat_id = request.POST.get('category_id')

        # 1. Create Category
        if action == 'create_category':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: নতুন ক্যাটাগরি তৈরি করার অনুমতি নেই। (Category creation restricted.)')
                return redirect('dashboard:pickle_categories')
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            icon = request.POST.get('icon', 'fa-jar').strip()
            if name:
                Category.objects.create(name=name, description=description, icon=icon)
                messages.success(request, f'Pickle Category "{name}" created successfully!')
            else:
                messages.error(request, 'Category name is required.')
            return redirect('dashboard:pickle_categories')

        # 2. Edit Category
        elif action == 'edit_category':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: ক্যাটাগরি এডিট করার অনুমতি নেই। (Category editing restricted.)')
                return redirect('dashboard:pickle_categories')
            cat = get_object_or_404(Category, id=cat_id)
            cat.name = request.POST.get('name', cat.name).strip()
            cat.description = request.POST.get('description', cat.description).strip()
            cat.icon = request.POST.get('icon', cat.icon).strip()
            cat.save()
            messages.success(request, f'Pickle Category "{cat.name}" updated.')
            return redirect('dashboard:pickle_categories')

        # 3. Delete Category
        elif action == 'delete_category':
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ ক্যাটাগরি ডিলিট করতে পারবেন না। (Only Administrator can delete categories.)')
                return redirect('dashboard:pickle_categories')
            cat = get_object_or_404(Category, id=cat_id)
            c_name = cat.name
            cat.delete()
            messages.success(request, f'Pickle Category "{c_name}" deleted.')
            return redirect('dashboard:pickle_categories')

    context = {
        'categories': categories,
        'total_categories': categories.count(),
    }
    return render(request, 'dashboard/pickle_categories.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def expense_categories_manager(request):
    # Auto-seed standard categories if table is empty
    if ExpenseCategory.objects.count() == 0:
        default_seed = [
            ('Fresh Cucumbers & Veggies 🥒', 'RAW_MATERIAL', 'fa-carrot', 'Fresh cucumbers, garlic cloves, peppers, and raw produce.'),
            ('Fresh Fruits (ফলমূল) 🍎', 'FRUITS', 'fa-apple-whole', 'Fresh pineapples, raw mangoes, grapes, olives, and fruits for pickling.'),
            ('Glass Jars, Lids & Labels 🫙', 'PACKAGING', 'fa-jar', 'Food-grade glass jars, airtight gold metal lids, and stickers.'),
            ('Vinegar, Garlic & Whole Spices 🌿', 'SPICES_BRINE', 'fa-leaf', 'Pure cane vinegar, pickling salt, bay leaf, mustard seeds, and brine spices.'),
            ('Courier & Rider Delivery Cost 🚚', 'LOGISTICS', 'fa-truck-fast', 'Courier parcel shipping fees and direct delivery rider charges.'),
            ('Digital Ads & Marketing 📢', 'MARKETING', 'fa-bullhorn', 'Facebook page sponsored ads, boost campaigns, and promotion.'),
            ('Gas, Electricity & Kitchen Rent ⚡', 'UTILITIES', 'fa-bolt', 'Kitchen utilities, gas cylinders, and production space rent.'),
            ('Damaged & Broken Products Loss 💥', 'DAMAGE_LOSS', 'fa-burst', 'Financial loss from courier breakage, kitchen spills, and unsellable damaged jars.'),
            ('Operational & Miscellaneous 📋', 'OTHER', 'fa-receipt', 'Sanitizing supplies, kitchen tools, and operational expenses.'),
        ]
        for name, slug, icon, desc in default_seed:
            ExpenseCategory.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'icon': icon, 'description': desc}
            )

    if request.method == 'POST':
        action = request.POST.get('action')
        cat_id = request.POST.get('category_id')

        # 1. Add Category
        if action == 'create_category':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: নতুন খরচ ক্যাটাগরি তৈরি করার অনুমতি নেই। (Expense category creation restricted.)')
                return redirect('dashboard:expense_categories')
            name = request.POST.get('name', '').strip()
            parent_id = request.POST.get('parent_id')
            parent = ExpenseCategory.objects.filter(id=parent_id).first() if parent_id else None
            icon = request.POST.get('icon', 'fa-receipt').strip()
            color = request.POST.get('theme_color', '').strip().lower()
            description = request.POST.get('description', '').strip()
            
            clean_icon = icon.split('|')[0] if '|' in icon else (icon or 'fa-receipt')
            stored_icon = f"{clean_icon}|{color}" if color else clean_icon

            if name:
                new_cat = ExpenseCategory.objects.create(name=name, parent=parent, icon=stored_icon, description=description)
                messages.success(request, f'Expense Category "{name}" created successfully!')
                target_head = parent.id if parent else new_cat.id
                return redirect(f"{reverse('dashboard:expense_categories')}?head={target_head}")
            else:
                messages.error(request, 'Category name is required.')
                if parent:
                    return redirect(f"{reverse('dashboard:expense_categories')}?head={parent.id}")
                return redirect('dashboard:expense_categories')

        # 2. Edit Category (Head or Sub-category)
        elif action == 'edit_category':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: খরচ ক্যাটাগরি এডিট করার অনুমতি নেই। (Expense category editing restricted.)')
                return redirect('dashboard:expense_categories')
            cat = get_object_or_404(ExpenseCategory, id=cat_id)
            target_head = cat.parent_id if cat.parent_id else cat.id
            old_name = cat.name
            old_slug = cat.slug
            new_name = request.POST.get('name', '').strip()
            new_slug = request.POST.get('slug', '').strip()
            new_icon = request.POST.get('icon', cat.icon).strip()
            new_color = request.POST.get('theme_color', '').strip().lower()
            new_desc = request.POST.get('description', cat.description).strip()
            parent_id = request.POST.get('parent_id')

            if not new_name:
                messages.error(request, 'Category name is required.')
                return redirect(f"{reverse('dashboard:expense_categories')}?head={target_head}")

            # Uniqueness check for name (excluding self)
            if ExpenseCategory.objects.filter(name__iexact=new_name).exclude(id=cat.id).exists():
                messages.error(request, f'A category with the name "{new_name}" already exists.')
                return redirect(f"{reverse('dashboard:expense_categories')}?head={target_head}")

            cat.name = new_name
            if new_slug:
                import re
                clean_slug = re.sub(r'[^a-zA-Z0-9_\-]', '', new_slug.strip().replace(' ', '_'))
                if clean_slug and not ExpenseCategory.objects.filter(slug__iexact=clean_slug).exclude(id=cat.id).exists():
                    cat.slug = clean_slug
            elif not cat.slug:
                from django.utils.text import slugify
                cat.slug = (slugify(new_name) or f"cat-{cat.id}").upper()

            clean_icon = new_icon.split('|')[0] if '|' in new_icon else (new_icon or 'fa-receipt')
            cat.icon = f"{clean_icon}|{new_color}" if new_color else clean_icon
            cat.description = new_desc

            # Only assign parent if valid and not self
            if parent_id and str(parent_id) != str(cat.id):
                cat.parent = ExpenseCategory.objects.filter(id=parent_id).first()
            elif not parent_id:
                cat.parent = None

            cat.save()

            # Keep historical Expense records in sync if name or slug changed
            if old_name != cat.name or (old_slug and old_slug != cat.slug):
                if old_slug:
                    Expense.objects.filter(category=old_slug).update(category=cat.slug)
                Expense.objects.filter(category=old_name).update(category=cat.slug or cat.name)
                Expense.objects.filter(sub_category=old_name).update(sub_category=cat.name)

            messages.success(request, f'Expense Category "{cat.name}" updated successfully!')
            target_head = cat.parent_id if cat.parent_id else cat.id
            return redirect(f"{reverse('dashboard:expense_categories')}?head={target_head}")

        # 3. Delete Category (Head or Sub-category)
        elif action == 'delete_category':
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ খরচ ক্যাটাগরি ডিলিট করতে পারবেন না। (Only Administrator can delete expense categories.)')
                return redirect('dashboard:expense_categories')
            cat = get_object_or_404(ExpenseCategory, id=cat_id)
            c_name = cat.name
            target_head = cat.parent_id
            cat.delete()
            messages.success(request, f'Expense Category "{c_name}" deleted successfully.')
            if target_head:
                return redirect(f"{reverse('dashboard:expense_categories')}?head={target_head}")
            return redirect('dashboard:expense_categories')

    # Load categories with stats
    categories = ExpenseCategory.objects.all().select_related('parent').order_by('parent__name', 'name')
    
    # 1. Main Category aggregations (grouped by Expense.category)
    exp_summary = Expense.objects.values('category').annotate(spent=Sum('amount'), count=Count('id'))
    exp_map = {row['category']: (row['spent'] or 0, row['count'] or 0) for row in exp_summary}

    # 2. Sub-Category aggregations (grouped by Expense.sub_category)
    sub_summary = Expense.objects.filter(sub_category__isnull=False).exclude(sub_category='').values('sub_category').annotate(spent=Sum('amount'), count=Count('id'))
    sub_map = {row['sub_category']: (row['spent'] or 0, row['count'] or 0) for row in sub_summary}
    sub_map_lower = {k.strip().lower(): v for k, v in sub_map.items()}

    def get_sub_stats(sub_cat):
        spent, count = sub_map.get(sub_cat.name, (0, 0))
        if count == 0 and sub_cat.slug:
            spent, count = sub_map.get(sub_cat.slug, (0, 0))
        if count == 0:
            c_name_lower = sub_cat.name.strip().lower()
            c_slug_lower = sub_cat.slug.strip().lower()
            if c_name_lower in sub_map_lower:
                spent, count = sub_map_lower[c_name_lower]
            elif c_slug_lower in sub_map_lower:
                spent, count = sub_map_lower[c_slug_lower]
            else:
                for k, (s, c) in sub_map.items():
                    k_lower = k.lower()
                    if c_slug_lower in k_lower or k_lower in c_name_lower or c_name_lower in k_lower:
                        spent += s
                        count += c
        return spent, count

    parent_categories = ExpenseCategory.objects.filter(parent__isnull=True).prefetch_related('subcategories').order_by('name')
    
    grouped_categories = []
    total_heads_count = parent_categories.count()
    total_subs_count = 0

    for head in parent_categories:
        spent_slug, count_slug = exp_map.get(head.slug, (0, 0))
        spent_name, count_name = exp_map.get(head.name, (0, 0))
        direct_spent = (spent_slug + spent_name) if head.slug != head.name else spent_slug
        direct_count = (count_slug + count_name) if head.slug != head.name else count_slug

        # Fallback case-insensitive match
        if direct_count == 0:
            for k, (s, c) in exp_map.items():
                if k.strip().lower() == head.slug.lower() or k.strip().lower() == head.name.lower():
                    direct_spent += s
                    direct_count += c

        subs_data = []
        subs_spent_sum = 0
        subs_count_sum = 0
        for sub in head.subcategories.all().order_by('name'):
            total_subs_count += 1
            s_spent, s_count = get_sub_stats(sub)
            subs_spent_sum += s_spent
            subs_count_sum += s_count
            subs_data.append({
                'id': sub.id,
                'name': sub.name,
                'slug': sub.slug,
                'icon': sub.icon or 'fa-tag',
                'description': sub.description,
                'parent_id': head.id,
                'parent_name': head.name,
                'spent': s_spent,
                'count': s_count
            })

        total_head_spent = max(direct_spent, subs_spent_sum)
        total_head_count = max(direct_count, subs_count_sum)

        COLOR_THEMES = {
            'emerald': {
                'key': 'emerald',
                'name': 'Emerald Green',
                'badge': 'bg-emerald-50 text-emerald-800 border-emerald-200',
                'icon_bg': 'bg-emerald-50 text-emerald-700 border-emerald-200',
                'gradient': 'from-emerald-950 via-brand-900 to-emerald-900',
                'accent': 'text-emerald-400',
                'bg_chip': 'bg-emerald-600',
            },
            'rose': {
                'key': 'rose',
                'name': 'Ruby Rose',
                'badge': 'bg-rose-50 text-rose-800 border-rose-200',
                'icon_bg': 'bg-rose-50 text-rose-700 border-rose-200',
                'gradient': 'from-rose-950 via-brand-900 to-rose-900',
                'accent': 'text-rose-400',
                'bg_chip': 'bg-rose-600',
            },
            'indigo': {
                'key': 'indigo',
                'name': 'Indigo Blue',
                'badge': 'bg-indigo-50 text-indigo-800 border-indigo-200',
                'icon_bg': 'bg-indigo-50 text-indigo-700 border-indigo-200',
                'gradient': 'from-indigo-950 via-brand-900 to-indigo-900',
                'accent': 'text-indigo-400',
                'bg_chip': 'bg-indigo-600',
            },
            'amber': {
                'key': 'amber',
                'name': 'Amber Gold',
                'badge': 'bg-amber-50 text-amber-800 border-amber-200',
                'icon_bg': 'bg-amber-50 text-amber-700 border-amber-200',
                'gradient': 'from-amber-950 via-brand-900 to-amber-900',
                'accent': 'text-amber-400',
                'bg_chip': 'bg-amber-500',
            },
            'sky': {
                'key': 'sky',
                'name': 'Sky Cyan',
                'badge': 'bg-sky-50 text-sky-800 border-sky-200',
                'icon_bg': 'bg-sky-50 text-sky-700 border-sky-200',
                'gradient': 'from-sky-950 via-brand-900 to-sky-900',
                'accent': 'text-sky-400',
                'bg_chip': 'bg-sky-500',
            },
            'purple': {
                'key': 'purple',
                'name': 'Royal Purple',
                'badge': 'bg-purple-50 text-purple-800 border-purple-200',
                'icon_bg': 'bg-purple-50 text-purple-700 border-purple-200',
                'gradient': 'from-purple-950 via-brand-900 to-purple-900',
                'accent': 'text-purple-400',
                'bg_chip': 'bg-purple-600',
            },
            'orange': {
                'key': 'orange',
                'name': 'Tangerine Orange',
                'badge': 'bg-orange-50 text-orange-800 border-orange-200',
                'icon_bg': 'bg-orange-50 text-orange-700 border-orange-200',
                'gradient': 'from-orange-950 via-brand-900 to-orange-900',
                'accent': 'text-orange-400',
                'bg_chip': 'bg-orange-500',
            },
            'teal': {
                'key': 'teal',
                'name': 'Deep Teal',
                'badge': 'bg-teal-50 text-teal-800 border-teal-200',
                'icon_bg': 'bg-teal-50 text-teal-700 border-teal-200',
                'gradient': 'from-teal-950 via-brand-900 to-teal-900',
                'accent': 'text-teal-400',
                'bg_chip': 'bg-teal-600',
            },
            'red': {
                'key': 'red',
                'name': 'Crimson Red',
                'badge': 'bg-red-50 text-red-800 border-red-200',
                'icon_bg': 'bg-red-50 text-red-700 border-red-200',
                'gradient': 'from-red-950 via-brand-900 to-red-900',
                'accent': 'text-red-400',
                'bg_chip': 'bg-red-600',
            },
            'fuchsia': {
                'key': 'fuchsia',
                'name': 'Electric Pink',
                'badge': 'bg-fuchsia-50 text-fuchsia-800 border-fuchsia-200',
                'icon_bg': 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200',
                'gradient': 'from-fuchsia-950 via-brand-900 to-fuchsia-900',
                'accent': 'text-fuchsia-400',
                'bg_chip': 'bg-fuchsia-600',
            },
            'slate': {
                'key': 'slate',
                'name': 'Charcoal Slate',
                'badge': 'bg-slate-50 text-slate-800 border-slate-200',
                'icon_bg': 'bg-slate-50 text-slate-700 border-slate-200',
                'gradient': 'from-slate-950 via-brand-900 to-slate-900',
                'accent': 'text-slate-400',
                'bg_chip': 'bg-slate-600',
            },
        }

        DEFAULT_SLUG_COLORS = {
            'RAW_MATERIAL': 'emerald',
            'FRUITS': 'rose',
            'PACKAGING': 'indigo',
            'SPICES_BRINE': 'amber',
            'LOGISTICS': 'sky',
            'MARKETING': 'purple',
            'UTILITIES': 'orange',
            'DAMAGE_LOSS': 'red',
            'OTHER': 'slate',
        }
        AUTO_COLOR_CYCLE = ['teal', 'purple', 'rose', 'sky', 'amber', 'indigo', 'orange', 'fuchsia', 'emerald', 'red', 'slate']

        raw_icon = head.icon or 'fa-receipt'
        if '|' in raw_icon:
            clean_icon, custom_color = raw_icon.split('|', 1)
        else:
            clean_icon, custom_color = raw_icon, ''

        if custom_color and custom_color in COLOR_THEMES:
            color_key = custom_color
        elif head.slug in DEFAULT_SLUG_COLORS:
            color_key = DEFAULT_SLUG_COLORS[head.slug]
        else:
            color_key = AUTO_COLOR_CYCLE[head.id % len(AUTO_COLOR_CYCLE)]

        theme = COLOR_THEMES.get(color_key, COLOR_THEMES['emerald'])

        grouped_categories.append({
            'head': {
                'id': head.id,
                'name': head.name,
                'slug': head.slug,
                'icon': clean_icon or 'fa-receipt',
                'color_key': color_key,
                'description': head.description,
                'direct_spent': direct_spent,
                'direct_count': direct_count,
                'total_spent': total_head_spent,
                'total_count': total_head_count,
                'sub_count': len(subs_data),
                'theme': theme,
            },
            'subcategories': subs_data,
            'is_active': False,
        })

    requested_head = request.GET.get('head', '').strip()
    active_found = False
    if requested_head:
        for item in grouped_categories:
            if str(item['head']['id']) == str(requested_head) or item['head']['slug'].lower() == str(requested_head).lower():
                item['is_active'] = True
                active_found = True
                break
    if not active_found and grouped_categories:
        grouped_categories[0]['is_active'] = True

    context = {
        'grouped_categories': grouped_categories,
        'parent_categories': parent_categories,
        'requested_head': requested_head,
        'color_themes': COLOR_THEMES,
        'total_heads_count': total_heads_count,
        'total_subs_count': total_subs_count,
        'total_categories': total_heads_count + total_subs_count,
        'total_expenses_all': Expense.objects.aggregate(Sum('amount'))['amount__sum'] or 0,
    }
    return render(request, 'dashboard/expense_categories.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def order_notifications_api(request):
    """
    Returns latest order info and pending count for real-time dashboard notifications.
    Supports ?last_id=<int> to detect any newer orders.
    """
    last_id = request.GET.get('last_id')
    try:
        last_id = int(last_id) if last_id else 0
    except (ValueError, TypeError):
        last_id = 0

    latest_order = Order.objects.order_by('-id').first()
    latest_id = latest_order.id if latest_order else 0

    from .context_processors import get_pending_feedback_reminders_count
    pending_count = Order.objects.filter(order_status='PENDING').count()
    pending_reviews_count = Review.objects.filter(is_approved=False).count()
    feedback_reminders_count = get_pending_feedback_reminders_count(min_days=30)

    # New orders that came strictly after last_id
    new_orders_data = []
    if last_id > 0 and latest_id > last_id:
        new_orders = Order.objects.filter(id__gt=last_id).order_by('-id')[:5]
        for o in new_orders:
            new_orders_data.append({
                'id': o.id,
                'order_number': o.order_number,
                'customer_name': o.customer_name,
                'customer_phone': o.customer_phone,
                'total_amount': f"{o.total_amount:,.2f}",
                'delivery_city': o.delivery_city or ('Inside Dhaka' if o.delivery_zone == 'INSIDE_DHAKA' else 'Outside Dhaka'),
                'payment_method': o.get_payment_method_display(),
                'created_at_time': timezone.localtime(o.created_at).strftime('%I:%M %p'),
                'detail_url': reverse('dashboard:order_detail', kwargs={'order_number': o.order_number}),
            })

    # Recent 5 pending orders for dropdown list
    recent_pending = Order.objects.filter(order_status='PENDING').order_by('-id')[:5]
    recent_pending_data = []
    for o in recent_pending:
        recent_pending_data.append({
            'id': o.id,
            'order_number': o.order_number,
            'customer_name': o.customer_name,
            'total_amount': f"{o.total_amount:,.2f}",
            'created_at_time': timezone.localtime(o.created_at).strftime('%d %b, %I:%M %p'),
            'detail_url': reverse('dashboard:order_detail', kwargs={'order_number': o.order_number}),
        })

    return JsonResponse({
        'status': 'ok',
        'latest_id': latest_id,
        'has_new': len(new_orders_data) > 0,
        'new_orders': new_orders_data,
        'pending_count': pending_count,
        'pending_reviews_count': pending_reviews_count,
        'feedback_reminders_count': feedback_reminders_count,
        'recent_pending': recent_pending_data,
    })


@user_passes_test(is_staff_user, login_url='dashboard:login')
def customer_insights_api(request):
    """
    Returns order and courier statistics for a given customer phone number with live Pathao courier status.
    """
    from decimal import Decimal
    from django.db.models import Sum
    from store.pathao import PathaoCourierService
    
    phone = request.GET.get('phone', '').strip()
    if not phone:
        return JsonResponse({'status': 'error', 'message': 'Phone number required'}, status=400)
    
    clean_digits = ''.join(c for c in phone if c.isdigit())
    last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
    
    # Query orders matching this phone
    matching_orders = Order.all_objects.filter(customer_phone__icontains=last_10)
    total_orders = matching_orders.count()
    delivered_count = matching_orders.filter(order_status='DELIVERED').count()
    cancelled_count = matching_orders.filter(order_status='CANCELLED').count()
    pending_count = matching_orders.filter(order_status__in=['PENDING', 'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY']).count()
    
    total_spent = matching_orders.filter(order_status='DELIVERED').aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    all_spent = matching_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    
    first_order = matching_orders.order_by('created_at').first()
    latest_order = matching_orders.order_by('-created_at').first()
    
    success_rate = round((delivered_count / total_orders * 100), 1) if total_orders > 0 else 0
    formatted_phone = f"0{last_10}" if len(last_10) == 10 else phone
    
    # Live Courier Tracking check (Pathao & Steadfast)
    check_live_api = request.GET.get('live', '').lower() in ('1', 'true', 'yes') or request.GET.get('force', '').lower() in ('1', 'true', 'yes')
    pathao_svc = PathaoCourierService() if check_live_api else None
    steadfast_svc = SteadfastCourierService() if check_live_api else None
    courier_consignments = []
    
    orders_data = []
    for o in matching_orders.order_by('-created_at')[:8]:
        c_status = o.active_courier_status or o.steadfast_order_status or o.pathao_order_status or ''
        # If live check is explicitly requested and order has Steadfast consignment, check live info
        if check_live_api and steadfast_svc and o.steadfast_consignment_id and steadfast_svc.is_configured():
            try:
                info_res = steadfast_svc.get_delivery_status_by_cid(o.steadfast_consignment_id)
                if info_res.get('success') and info_res.get('delivery_status'):
                    c_status = info_res.get('delivery_status')
            except Exception:
                pass
        # If live check is explicitly requested and order has Pathao consignment, check live info
        elif check_live_api and pathao_svc and o.pathao_consignment_id and pathao_svc.is_configured():
            try:
                info_res = pathao_svc.get_order_info(o.pathao_consignment_id)
                if info_res.get('success'):
                    p_info = info_res.get('data', {})
                    c_status = p_info.get('order_status') or p_info.get('delivery_status') or c_status
            except Exception:
                pass

        if o.steadfast_consignment_id:
            courier_consignments.append({
                'courier': 'Steadfast',
                'consignment_id': o.steadfast_consignment_id,
                'order_number': o.order_number,
                'status': c_status,
            })
        elif o.pathao_consignment_id:
            courier_consignments.append({
                'courier': 'Pathao',
                'consignment_id': o.pathao_consignment_id,
                'order_number': o.order_number,
                'status': c_status,
            })

        orders_data.append({
            'order_number': o.order_number,
            'status': o.get_order_status_display(),
            'status_code': o.order_status,
            'total_amount': float(o.total_amount),
            'created_at': o.created_at.strftime('%d %b, %Y'),
            'courier': o.active_courier_name,
            'courier_code': o.active_courier,
            'consignment_id': o.active_consignment_id or '',
            'tracking_code': o.active_tracking_code or '',
            'pathao_id': o.pathao_consignment_id or '',
            'steadfast_id': o.steadfast_consignment_id or '',
            'courier_status': c_status,
            'pathao_status': o.pathao_order_status or '',
            'steadfast_status': o.steadfast_order_status or '',
        })
    
    # Identify courier-fault returns vs customer-fault cancellations
    non_customer_fault_reasons = {'COURIER_DELAY', 'DAMAGED_IN_TRANSIT', 'COURIER_FAULT', 'WRONG_ITEM'}
    courier_fault_order_ids = set()
    try:
        from dashboard.models import OrderReturn
        returns_qs = OrderReturn.objects.filter(order__in=matching_orders)
        courier_fault_order_ids = set(
            returns_qs.filter(return_reason__in=non_customer_fault_reasons).values_list('order_id', flat=True)
        )
    except Exception:
        pass

    courier_keywords = ['courier delay', 'damaged in transit', 'courier fault', 'courier rto', 'lost by courier', 'courier return']
    for o in matching_orders.filter(order_status='CANCELLED'):
        note = (o.admin_notes or '').lower()
        if any(kw in note for kw in courier_keywords):
            courier_fault_order_ids.add(o.id)

    courier_fault_count = len(courier_fault_order_ids)

    # Valid countable orders for customer (EXCLUDING courier-fault orders completely)
    valid_matching_orders = matching_orders.exclude(id__in=courier_fault_order_ids)
    valid_total_orders = valid_matching_orders.count()
    if valid_total_orders == 0 and matching_orders.exists():
        valid_total_orders = 1

    customer_cancelled_count = valid_matching_orders.filter(order_status='CANCELLED').count()
    delivered_count = valid_matching_orders.filter(order_status='DELIVERED').count()
    pending_count = valid_matching_orders.filter(order_status__in=['PENDING', 'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY']).count()
    success_rate = round((delivered_count / valid_total_orders * 100), 1) if valid_total_orders > 0 else 100
    
    # Trust & Risk Evaluation
    if customer_cancelled_count > 0:
        trust_level = 'RISK'
        trust_title = '⚠️ সতর্ক থাকুন (কাস্টমার রিফিউজাল রেকর্ড আছে)'
        trust_badge_class = 'bg-rose-100 text-rose-800 border-rose-200'
        trust_desc = f'পূর্বে এই নম্বর থেকে {customer_cancelled_count}টি অর্ডার কাস্টমার নিজে ক্যানসেল/রিফিউজ করেছেন।'
    elif valid_total_orders >= 2:
        trust_level = 'TRUSTED'
        trust_title = '🟢 বিশ্বস্ত ও নিয়মিত কাস্টমার (Safe)'
        trust_badge_class = 'bg-emerald-100 text-emerald-800 border-emerald-200'
        courier_note = f' (পূর্বে কুরিয়ারের ত্রুটিতে ফেরত আসা {courier_fault_count}টি অর্ডার বাদ দেওয়া হয়েছে)' if courier_fault_count > 0 else ''
        trust_desc = f'পূর্বে {valid_total_orders}টি অর্ডার সম্পন্ন হয়েছে (মোট খরচ: ৳{total_spent:,.0f})। কোনো কাস্টমার রিফিউজাল নেই{courier_note}।'
    elif valid_total_orders == 1:
        trust_level = 'NEW'
        trust_title = '🔵 নতুন কাস্টমার (১ম অর্ডার)'
        trust_badge_class = 'bg-blue-100 text-blue-800 border-blue-200'
        courier_note = f' (পূর্বে কুরিয়ারের ত্রুটিতে ক্ষতিগ্রস্ত {courier_fault_count}টি পার্সেল বাদ দেওয়া হয়েছে)' if courier_fault_count > 0 else ''
        trust_desc = f'পিকপিকলসে এটি কাস্টমারের ১ম প্রকৃত অর্ডার{courier_note}। কোনো কাস্টমার রিফিউজাল রেকর্ড নেই।'
    else:
        trust_level = 'CLEAN'
        trust_title = '⚪ ফ্রেশ নম্বর (কোনো ব্যাড হিস্ট্রি নেই)'
        trust_badge_class = 'bg-slate-100 text-slate-800 border-slate-200'
        trust_desc = 'কোনো রেকর্ড পাওয়া যায়নি।'
    courier_api_info = {
        'pathao_connected': pathao_svc.is_configured(),
        'steadfast_connected': steadfast_svc.is_configured(),
        'consignments_checked': len(courier_consignments),
        'consignments': courier_consignments,
    }

    return JsonResponse({
        'status': 'success',
        'phone': phone,
        'clean_phone': formatted_phone,
        'total_orders': valid_total_orders,
        'delivered_count': delivered_count,
        'cancelled_count': customer_cancelled_count,
        'courier_fault_count': courier_fault_count,
        'pending_count': pending_count,
        'success_rate': success_rate,
        'total_spent': float(total_spent),
        'all_spent': float(all_spent),
        'first_order_date': first_order.created_at.strftime('%b %d, %Y') if first_order else None,
        'latest_order_number': latest_order.order_number if latest_order else None,
        'is_repeat_customer': valid_total_orders > 1,
        'trust_level': trust_level,
        'trust_title': trust_title,
        'trust_badge_class': trust_badge_class,
        'trust_desc': trust_desc,
        'courier_api_info': courier_api_info,
        'pathao_api_info': courier_api_info,
        'courier_consignments': courier_consignments,
        'pathao_consignments': courier_consignments,
        'recent_orders': orders_data,
    })


@user_passes_test(is_staff_user, login_url='dashboard:login')
def steadfast_fraud_check_api(request):
    """
    Direct Fraud Check API using Steadfast Courier Developer API + Local Store History.
    """
    phone = request.GET.get('phone', '').strip() or request.POST.get('phone', '').strip()
    if not phone:
        return JsonResponse({'success': False, 'message': 'Phone number is required'}, status=400)

    force = request.GET.get('force', '').lower() in ('1', 'true', 'yes') or request.POST.get('force', '').lower() in ('1', 'true', 'yes')

    clean_digits = ''.join(c for c in phone if c.isdigit())
    last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
    formatted_phone = f"0{last_10}" if len(last_10) == 10 else phone

    steadfast_svc = SteadfastCourierService()
    fraud_result = steadfast_svc.check_fraud(formatted_phone, force_refresh=force)

    # High-performance single database query for local order metrics
    matching_orders = Order.all_objects.filter(customer_phone__icontains=last_10)
    aggs = matching_orders.aggregate(
        total=Count('id'),
        delivered=Count('id', filter=Q(order_status='DELIVERED')),
        cancelled=Count('id', filter=Q(order_status='CANCELLED')),
        pending=Count('id', filter=Q(order_status__in=['PENDING', 'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY'])),
        total_spent=Sum('total_amount', filter=Q(order_status='DELIVERED'))
    )
    total_local = aggs['total'] or 0
    delivered_local = aggs['delivered'] or 0
    cancelled_local = aggs['cancelled'] or 0
    pending_local = aggs['pending'] or 0
    total_spent_local = float(aggs['total_spent'] or 0)
    customer_name = matching_orders.order_by('-created_at').values_list('customer_name', flat=True).first() or 'Customer'

    local_summary = {
        'customer_name': customer_name,
        'total_orders': total_local,
        'delivered_count': delivered_local,
        'cancelled_count': cancelled_local,
        'pending_count': pending_local,
        'total_spent': total_spent_local,
        'success_rate': round((delivered_local / total_local * 100), 1) if total_local > 0 else 100,
    }

    # Check if currently blacklisted
    is_blocked = BlacklistedCustomer.is_phone_blocked(last_10)

    return JsonResponse({
        'success': True,
        'phone': formatted_phone,
        'from_cache': fraud_result.get('from_cache', False),
        'steadfast': fraud_result,
        'local': local_summary,
        'is_blacklisted': is_blocked,
    })


@user_passes_test(is_staff_user, login_url='dashboard:login')
def blacklist_manager(request):
    """
    Manager view for viewing, adding, searching, and managing blacklisted phones & IPs.
    """
    query = request.GET.get('q', '').strip()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: ব্ল্যাকলিস্টে নম্বর যুক্ত করার অনুমতি নেই। (Blacklist creation restricted.)')
                return redirect('dashboard:blacklist_manager')
            phone = request.POST.get('phone', '').strip()
            name = request.POST.get('customer_name', '').strip()
            reason = request.POST.get('reason', '').strip() or "Fake orders / prank harassment"
            ip_addr = request.POST.get('ip_address', '').strip() or None
            
            clean_digits = ''.join(c for c in phone if c.isdigit())
            if clean_digits:
                obj, created = BlacklistedCustomer.objects.update_or_create(
                    phone=clean_digits,
                    defaults={
                        'customer_name': name,
                        'reason': reason,
                        'ip_address': ip_addr,
                        'is_active': True,
                        'blocked_by': request.user if request.user.is_authenticated else None,
                    }
                )
                if created:
                    messages.success(request, f"Phone #{clean_digits} has been added to the Blacklist.")
                else:
                    messages.info(request, f"Blacklist entry for #{clean_digits} updated.")
            else:
                messages.error(request, "Please provide a valid phone number.")
                
        elif action == 'toggle':
            if not can_user_edit(request.user):
                messages.error(request, 'Permission Denied: ব্ল্যাকলিস্ট স্ট্যাটাস পরিবর্তন করার অনুমতি নেই।')
                return redirect('dashboard:blacklist_manager')
            entry_id = request.POST.get('entry_id')
            entry = get_object_or_404(BlacklistedCustomer, id=entry_id)
            entry.is_active = not entry.is_active
            entry.save(update_fields=['is_active'])
            status_txt = "Active Block" if entry.is_active else "Unblocked (Whitelist)"
            messages.success(request, f"Entry for {entry.phone} is now {status_txt}.")
            
        elif action == 'delete':
            if not can_user_delete(request.user):
                messages.error(request, 'Permission Denied: Admin ছাড়া কেউ ব্ল্যাকলিস্ট এন্ট্রি ডিলিট করতে পারবেন না। (Only Administrator can delete blacklist records.)')
                return redirect('dashboard:blacklist_manager')
            entry_id = request.POST.get('entry_id')
            entry = get_object_or_404(BlacklistedCustomer, id=entry_id)
            entry.delete()
            messages.success(request, f"Removed {entry.phone} permanently from Blacklist.")

        return redirect('dashboard:blacklist_manager')

    blacklist_qs = BlacklistedCustomer.objects.all().order_by('-created_at', '-id')
    if query:
        clean_q = ''.join(c for c in query if c.isdigit())
        blacklist_qs = blacklist_qs.filter(
            Q(phone__icontains=clean_q or query) |
            Q(customer_name__icontains=query) |
            Q(reason__icontains=query) |
            Q(ip_address__icontains=query)
        )

    total_count = BlacklistedCustomer.objects.count()
    active_count = BlacklistedCustomer.objects.filter(is_active=True).count()

    # Pagination configuration
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 15)
    try:
        per_page = int(per_page)
        if per_page not in [10, 15, 25, 50, 100]:
            per_page = 15
    except (ValueError, TypeError):
        per_page = 15

    paginator = Paginator(blacklist_qs, per_page)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    elided_page_range = paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1) if paginator.num_pages > 1 else []

    return render(request, 'dashboard/blacklist.html', {
        'blacklist_items': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'elided_page_range': elided_page_range,
        'per_page': per_page,
        'query': query,
        'total_count': total_count,
        'active_count': active_count,
    })


@user_passes_test(is_staff_user, login_url='dashboard:login')
def toggle_blacklist_ajax(request):
    """
    1-Click AJAX API to block or unblock a phone number directly from Order views.
    """
    if request.method == 'POST':
        if not can_user_edit(request.user):
            return JsonResponse({'success': False, 'error': 'Permission Denied: আপনার আইডিতে শুধুমাত্র দেখার অনুমতি রয়েছে।'}, status=403)
        phone = request.POST.get('phone', '').strip()
        name = request.POST.get('customer_name', '').strip()
        reason = request.POST.get('reason', '').strip() or "Fake order / courier refusal"
        
        clean_digits = ''.join(c for c in phone if c.isdigit())
        if not clean_digits:
            return JsonResponse({'success': False, 'error': 'Invalid phone number'}, status=400)
            
        last_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
        existing = BlacklistedCustomer.objects.filter(phone__icontains=last_10).first()
        
        if existing:
            existing.is_active = not existing.is_active
            existing.save(update_fields=['is_active'])
            return JsonResponse({
                'success': True,
                'is_blacklisted': existing.is_active,
                'message': f"Customer {'blocked' if existing.is_active else 'unblocked'} successfully."
            })
        else:
            new_entry = BlacklistedCustomer.objects.create(
                phone=clean_digits,
                customer_name=name,
                reason=reason,
                is_active=True,
                blocked_by=request.user if request.user.is_authenticated else None
            )
            return JsonResponse({
                'success': True,
                'is_blacklisted': True,
                'message': f"Phone {clean_digits} has been blacklisted."
            })
            
    return JsonResponse({'success': False, 'error': 'POST required'}, status=405)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def push_notifications_manager(request):
    """
    Dedicated view for Staff and Admin to manage PWA Installation & Push Notification Subscriptions.
    """
    from django.conf import settings
    subscriptions_count = 0
    if hasattr(request.user, 'webpush_info'):
        subscriptions_count = request.user.webpush_info.count()
        
    vapid_key = getattr(settings, 'WEBPUSH_SETTINGS', {}).get('VAPID_PUBLIC_KEY', '')
    context = {
        'page_title': 'PWA & Push Notifications',
        'subscriptions_count': subscriptions_count,
        'vapid_public_key': vapid_key,
    }
    return render(request, 'dashboard/push_notifications.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def send_test_push_api(request):
    """
    AJAX endpoint to trigger an instant test push notification to verify sound, vibration & popup.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    from store.webpush_sender import send_high_priority_user_notification
    payload = {
        "head": "🔔 Pickpickles Test Alert",
        "body": f"Real-time notifications are active on your device! ({timezone.now().strftime('%I:%M %p')})",
        "icon": "/static/images/icon-192.png",
        "badge": "/static/images/badge-96.png",
        "url": "/dashboard/orders/",
        "tag": "test-alert",
        "timestamp": int(timezone.now().timestamp() * 1000),
        "vibrate": [300, 100, 300, 100, 400]
    }

    try:
        success_cnt, fail_cnt = send_high_priority_user_notification(
            user=request.user,
            payload=payload,
            ttl=3600,
            urgency='high'
        )
        if success_cnt > 0:
            return JsonResponse({
                'success': True,
                'message': f'Test notification sent to {success_cnt} device(s)! Check your phone notification shade.'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No active registered device found for this account. Please tap "Subscribe to Push Messaging" above first.'
            }, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required(login_url='dashboard:login')
@user_passes_test(is_staff_user, login_url='dashboard:login')
def offer_manager(request):
    promo = PromotionSetting.get_settings()
    is_view_only = is_view_only_user(request.user)

    if request.method == 'POST':
        if not can_user_edit(request.user):
            messages.error(request, 'Permission Denied: অফার ও ক্যাম্পেইন সেটিংস পরিবর্তন করার অনুমতি নেই। (View-Only Mode)')
            return redirect('dashboard:offer_manager')

        action = request.POST.get('action')

        # 1. Create Coupon
        if action == 'create_coupon':
            try:
                code = request.POST.get('coupon_code', '').strip().upper()
                if not code:
                    messages.error(request, 'Coupon code is required.')
                    return redirect('dashboard:offer_manager')
                if Coupon.objects.filter(code__iexact=code).exists():
                    messages.error(request, f'Coupon code "{code}" already exists!')
                    return redirect('dashboard:offer_manager')
                
                discount_type = request.POST.get('discount_type', 'FIXED')
                discount_value = Decimal(str(request.POST.get('discount_value', '50.00')).strip() or '0.00')
                min_jars = max(1, int(request.POST.get('min_jars', 1)))
                min_subtotal = Decimal(str(request.POST.get('min_subtotal', '0.00')).strip() or '0.00')
                usage_limit_raw = request.POST.get('usage_limit', '').strip()
                usage_limit = int(usage_limit_raw) if usage_limit_raw else None
                is_active = request.POST.get('is_active') == '1'

                Coupon.objects.create(
                    code=code,
                    discount_type=discount_type,
                    discount_value=discount_value,
                    min_jars=min_jars,
                    min_subtotal=min_subtotal,
                    usage_limit=usage_limit,
                    is_active=is_active,
                )
                messages.success(request, f'🎉 Coupon "{code}" created successfully!')
            except Exception as e:
                messages.error(request, f'Error creating coupon: {str(e)}')
            return redirect(f"{reverse('dashboard:offer_manager')}#coupons")

        # 2. Toggle Coupon Status
        elif action == 'toggle_coupon':
            cid = request.POST.get('coupon_id')
            c = get_object_or_404(Coupon, id=cid)
            c.is_active = not c.is_active
            c.save(update_fields=['is_active'])
            status_text = 'activated' if c.is_active else 'deactivated'
            messages.success(request, f'Coupon "{c.code}" has been {status_text}.')
            return redirect(f"{reverse('dashboard:offer_manager')}#coupons")

        # 3. Delete Coupon
        elif action == 'delete_coupon':
            cid = request.POST.get('coupon_id')
            c = get_object_or_404(Coupon, id=cid)
            code = c.code
            c.delete()
            messages.success(request, f'Coupon "{code}" deleted successfully.')
            return redirect(f"{reverse('dashboard:offer_manager')}#coupons")

        # 4. Edit Coupon
        elif action == 'edit_coupon':
            try:
                cid = request.POST.get('coupon_id')
                c = get_object_or_404(Coupon, id=cid)
                new_code = request.POST.get('coupon_code', '').strip().upper()
                if not new_code:
                    messages.error(request, 'Coupon code cannot be empty.')
                    return redirect(f"{reverse('dashboard:offer_manager')}#coupons")

                # Check uniqueness if code is changed
                if new_code != c.code and Coupon.objects.filter(code__iexact=new_code).exclude(id=c.id).exists():
                    messages.error(request, f'Coupon code "{new_code}" already exists!')
                    return redirect(f"{reverse('dashboard:offer_manager')}#coupons")

                c.code = new_code
                c.discount_type = request.POST.get('discount_type', 'FIXED')
                c.discount_value = Decimal(str(request.POST.get('discount_value', '50.00')).strip() or '0.00')
                c.min_jars = max(1, int(request.POST.get('min_jars', 1)))
                c.min_subtotal = Decimal(str(request.POST.get('min_subtotal', '0.00')).strip() or '0.00')
                usage_limit_raw = request.POST.get('usage_limit', '').strip()
                c.usage_limit = int(usage_limit_raw) if usage_limit_raw else None
                c.is_active = request.POST.get('is_active') == '1'
                c.save()

                messages.success(request, f'🎉 Coupon "{c.code}" updated successfully!')
            except Exception as e:
                messages.error(request, f'Error updating coupon: {str(e)}')
            return redirect(f"{reverse('dashboard:offer_manager')}#coupons")

        # 5. Standard Offer / Promotion Settings Save
        try:
            is_active = request.POST.get('is_active') == '1'
            promo.is_active = is_active
            promo.campaign_name = request.POST.get('campaign_name', '').strip() or 'Special Seasonal Offer'
            
            if not is_active:
                # Campaign is OFF -> Turn all promotional features OFF at once
                promo.hero_badge_enabled = False
                promo.announcement_bar_enabled = False
                promo.bundle_discount_enabled = False
                promo.free_delivery_enabled = False
                promo.advance_payment_discount_enabled = False
            else:
                # 1. Hero & Menu Badges
                promo.hero_badge_enabled = request.POST.get('hero_badge_enabled') == '1'
                promo.hero_badge_text = request.POST.get('hero_badge_text', '').strip()

                # 2. Top Announcement Bar
                promo.announcement_bar_enabled = request.POST.get('announcement_bar_enabled') == '1'
                promo.announcement_bar_text = request.POST.get('announcement_bar_text', '').strip()

                # 3. Bundle / Volume Discount
                promo.bundle_discount_enabled = request.POST.get('bundle_discount_enabled') == '1'
                promo.bundle_min_jars = max(1, int(request.POST.get('bundle_min_jars', 2)))
                promo.bundle_discount_amount = Decimal(str(request.POST.get('bundle_discount_amount', '100.00')).strip() or '0.00')
                raw_label = request.POST.get('bundle_discount_label', '').strip()
                import re
                amount_str = f"{promo.bundle_discount_amount:.0f}"
                if not raw_label:
                    promo.bundle_discount_label = f'{promo.bundle_min_jars}-Jar Flat ৳{amount_str} OFF'
                elif re.search(r'৳\s*\d+', raw_label):
                    promo.bundle_discount_label = re.sub(r'৳\s*\d+', f'৳{amount_str}', raw_label)
                else:
                    promo.bundle_discount_label = raw_label
                promo.bundle_apply_mode = request.POST.get('bundle_apply_mode', 'EXACT')
                if promo.bundle_apply_mode not in ('EXACT', 'AT_LEAST'):
                    promo.bundle_apply_mode = 'EXACT'

                # 4. Delivery Rules
                promo.free_delivery_enabled = request.POST.get('free_delivery_enabled') == '1'
                promo.free_delivery_min_jars = max(1, int(request.POST.get('free_delivery_min_jars', 4)))

                # 5. Advance Payment Offer
                promo.advance_payment_discount_enabled = request.POST.get('advance_payment_discount_enabled') == '1'
                adv_pct_raw = str(request.POST.get('advance_payment_discount_percent', '5')).strip() or '0'
                adv_pct = max(Decimal('0.00'), min(Decimal('100.00'), Decimal(adv_pct_raw)))
                promo.advance_payment_discount_percent = adv_pct
                adv_label_raw = request.POST.get('advance_payment_discount_label', '').strip()
                pct_str = str(int(adv_pct)) if adv_pct == int(adv_pct) else f"{adv_pct:.2f}".rstrip('0').rstrip('.')
                if not adv_label_raw:
                    promo.advance_payment_discount_label = f"{pct_str}% Advance Payment OFF"
                elif re.search(r'\d+(?:\.\d+)?\s*%', adv_label_raw):
                    promo.advance_payment_discount_label = re.sub(r'\d+(?:\.\d+)?\s*%', f"{pct_str}%", adv_label_raw)
                else:
                    promo.advance_payment_discount_label = adv_label_raw

            promo.standard_delivery_fee = Decimal(str(request.POST.get('standard_delivery_fee', '150.00')).strip() or '150.00')
            promo.delivery_notice_text = request.POST.get('delivery_notice_text', '').strip()

            promo.save()
            if not is_active:
                messages.warning(request, '🛑 ক্যাম্পেইন এবং সকল অফার একযোগে বন্ধ (OFF) করা হয়েছে। (All promotions paused live.)')
            else:
                messages.success(request, '🎉 অফার ও ক্যাম্পেইন সেটিংস সফলভাবে আপডেট হয়েছে! (Offers & Campaign settings saved successfully.)')
        except Exception as e:
            messages.error(request, f'ত্রুটি: {str(e)}')

        return redirect('dashboard:offer_manager')

    coupons = Coupon.objects.all().order_by('-created_at')

    context = {
        'title': 'Offers & Campaign Manager',
        'promo': promo,
        'coupons': coupons,
        'is_view_only': is_view_only,
        'can_delete': not is_view_only,
    }
    return render(request, 'dashboard/offer_manager.html', context)






