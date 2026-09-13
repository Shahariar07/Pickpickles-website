import csv
import json
import datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from decimal import Decimal
from django.contrib.auth.models import User
from store.models import Order, OrderItem, Product, Category, Review, calculate_pathao_delivery_fee
from store.pathao import PathaoCourierService
from .models import Expense, ExpenseCategory, DamageLog, OrderReturn


def is_staff_user(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def dashboard_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dashboard:index')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None and (user.is_staff or user.is_superuser):
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            next_url = request.GET.get('next') or 'dashboard:index'
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid credentials or non-staff account.')

    return render(request, 'dashboard/login.html')


def dashboard_logout(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('dashboard:login')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def dashboard_index(request):
    now = timezone.now()
    today = now.date()
    
    # Basic Metrics
    total_orders_count = Order.objects.count()
    today_orders = Order.objects.filter(created_at__date=today)
    today_orders_count = today_orders.count()
    
    # Realized / Collected Revenue (Only orders that are DELIVERED or PAID)
    delivered_paid_orders = Order.objects.filter(Q(order_status='DELIVERED') | Q(payment_status='PAID'))
    total_revenue = delivered_paid_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    today_revenue = delivered_paid_orders.filter(created_at__date=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Pipeline Revenue (Uncollected active orders currently in delivery queue)
    pipeline_orders = Order.objects.filter(~Q(order_status__in=['DELIVERED', 'CANCELLED']) & ~Q(payment_status='PAID'))
    pipeline_revenue = pipeline_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Expenses & Net Profit
    total_expenses = Expense.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    net_profit = float(total_revenue) - float(total_expenses)
    profit_margin = round((net_profit / float(total_revenue)) * 100, 1) if float(total_revenue) > 0 else 0
    
    pending_count = Order.objects.filter(order_status='PENDING').count()
    confirmed_count = Order.objects.filter(order_status='CONFIRMED').count()
    packing_count = Order.objects.filter(order_status='PACKING').count()
    out_for_delivery_count = Order.objects.filter(order_status='OUT_FOR_DELIVERY').count()
    delivered_count = Order.objects.filter(order_status='DELIVERED').count()
    cancelled_count = Order.objects.filter(order_status='CANCELLED').count()
    
    # Advanced KPIs
    avg_order_val = round(float(total_revenue) / delivered_count, 1) if delivered_count > 0 else 0
    total_jars_sold = OrderItem.objects.filter(order__in=delivered_paid_orders).aggregate(Sum('quantity'))['quantity__sum'] or 0
    delivery_rate = round((delivered_count / total_orders_count) * 100, 1) if total_orders_count > 0 else 0
    low_stock_count = Product.objects.filter(stock_count__lt=15).count()
    total_products_count = Product.objects.count()

    # 1. 10-Day Sales & Revenue Trend Calculation (Real Database Queries from Delivered/Paid orders)
    days_to_plot = 10
    date_labels = []
    revenue_series = []
    orders_series = []
    
    for i in range(days_to_plot - 1, -1, -1):
        target_date = today - datetime.timedelta(days=i)
        day_label = target_date.strftime('%b %d')
        date_labels.append(day_label)
        
        day_qs = Order.objects.filter(~Q(order_status='CANCELLED'), created_at__date=target_date)
        day_collected_qs = Order.objects.filter(Q(order_status='DELIVERED') | Q(payment_status='PAID'), created_at__date=target_date)
        day_rev = float(day_collected_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
        day_cnt = day_qs.count()
        
        revenue_series.append(day_rev)
        orders_series.append(day_cnt)

    # 2. Dynamic Product Sales Performance Breakdown (Real OrderItem Counts)
    # Query sales per product name from non-cancelled orders
    top_products_qs = OrderItem.objects.filter(
        ~Q(order__order_status='CANCELLED')
    ).values('product_name').annotate(
        total_qty=Sum('quantity'),
        total_sales=Sum('total_price')
    ).order_by('-total_qty')

    product_labels = []
    product_qty_data = []
    best_seller = None

    if top_products_qs.exists():
        for item in top_products_qs:
            product_labels.append(item['product_name'])
            product_qty_data.append(item['total_qty'])
        best_seller = {
            'name': top_products_qs[0]['product_name'],
            'quantity': top_products_qs[0]['total_qty'],
            'sales': top_products_qs[0]['total_sales'],
        }
    else:
        # If no orders yet, list all current products from catalog with 0 sales
        all_prods = Product.objects.all().order_by('name')
        for prod in all_prods:
            product_labels.append(prod.name)
            product_qty_data.append(0)
        if not product_labels:
            product_labels = ['No Products Added']
            product_qty_data = [0]

    # 3. Payment Methods Breakdown (Real database counts)
    cod_count = Order.objects.filter(payment_method='COD').count()
    bkash_count = Order.objects.filter(payment_method='BKASH').count()
    nagad_count = Order.objects.filter(payment_method='NAGAD').count()
    payment_data = [cod_count, bkash_count, nagad_count]

    # 4. Delivery Zone Breakdown (Real database counts)
    inside_dhaka_count = Order.objects.filter(delivery_zone='INSIDE_DHAKA').count()
    outside_dhaka_count = Order.objects.filter(delivery_zone='OUTSIDE_DHAKA').count()

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

    # JSON Serialized for Chart.js
    chart_data = {
        'trendLabels': date_labels,
        'revenueData': revenue_series,
        'ordersData': orders_series,
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
        'comparisonLabels': ['Gross Revenue (৳)', 'Total Costs (৳)', 'Net Profit / Balance (৳)'],
        'comparisonData': [float(total_revenue), float(total_expenses), float(net_profit)],
    }

    # Recent orders preview for analytics dashboard
    recent_orders = Order.objects.all().prefetch_related('items')[:5]

    context = {
        'recent_orders': recent_orders,
        'best_seller': best_seller,
        'total_orders_count': total_orders_count,
        'today_orders_count': today_orders_count,
        'today_revenue': today_revenue,
        'total_revenue': total_revenue,
        'pipeline_revenue': pipeline_revenue,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'avg_order_val': avg_order_val,
        'total_jars_sold': total_jars_sold,
        'delivery_rate': delivery_rate,
        'low_stock_count': low_stock_count,
        'total_products_count': total_products_count,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'packing_count': packing_count,
        'out_for_delivery_count': out_for_delivery_count,
        'delivered_count': delivered_count,
        'cancelled_count': cancelled_count,
        'chart_data_json': json.dumps(chart_data),
    }
    return render(request, 'dashboard/index.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def orders_list(request):
    total_orders_count = Order.objects.count()
    pending_count = Order.objects.filter(order_status='PENDING').count()
    confirmed_count = Order.objects.filter(order_status='CONFIRMED').count()
    packing_count = Order.objects.filter(order_status='PACKING').count()
    out_for_delivery_count = Order.objects.filter(order_status='OUT_FOR_DELIVERY').count()
    delivered_count = Order.objects.filter(order_status='DELIVERED').count()
    cancelled_count = Order.objects.filter(order_status='CANCELLED').count()

    orders = Order.objects.all().prefetch_related('items')
    status_filter = request.GET.get('status', 'ALL')
    search_query = request.GET.get('q', '').strip()
    zone_filter = request.GET.get('zone', 'ALL')

    if status_filter and status_filter != 'ALL':
        orders = orders.filter(order_status=status_filter)
        
    if zone_filter and zone_filter != 'ALL':
        orders = orders.filter(delivery_zone=zone_filter)

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

    context = {
        'orders': orders[:200],
        'total_orders_count': total_orders_count,
        'pending_count': pending_count,
        'confirmed_count': confirmed_count,
        'packing_count': packing_count,
        'out_for_delivery_count': out_for_delivery_count,
        'delivered_count': delivered_count,
        'cancelled_count': cancelled_count,
        'trash_count': Order.trash_objects.count(),
        'status_filter': status_filter,
        'zone_filter': zone_filter,
        'search_query': search_query,
        'status_choices': Order.ORDER_STATUS_CHOICES,
        'payment_status_choices': Order.PAYMENT_STATUS_CHOICES,
        'products': Product.objects.all(),
    }
    return render(request, 'dashboard/orders_list.html', context)


ACCEPTED_ORDER_STATUSES = {'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY', 'DELIVERED'}

def adjust_inventory_for_order_status_change(order, old_status, new_status):
    """
    Deducts stock when an order is accepted/confirmed (transitions from PENDING/CANCELLED to CONFIRMED/PACKING/etc.).
    Restores stock when an accepted order is cancelled or reverted (transitions to CANCELLED/PENDING).
    """
    was_accepted = old_status in ACCEPTED_ORDER_STATUSES
    now_accepted = new_status in ACCEPTED_ORDER_STATUSES

    if not was_accepted and now_accepted:
        # Deduct stock when accepted
        for itm in order.items.all():
            if itm.product:
                if itm.product.stock_count >= itm.quantity:
                    itm.product.stock_count -= itm.quantity
                else:
                    itm.product.stock_count = 0
                if itm.product.stock_count == 0:
                    itm.product.is_in_stock = False
                itm.product.save()
    elif was_accepted and not now_accepted:
        # Restore stock when cancelled or reverted
        for itm in order.items.all():
            if itm.product:
                itm.product.stock_count += itm.quantity
                itm.product.is_in_stock = True
                itm.product.save()


@user_passes_test(is_staff_user, login_url='dashboard:login')
def order_detail(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), order_number=order_number)
    
    if request.method == 'POST':
        new_status = request.POST.get('order_status')
        new_payment_status = request.POST.get('payment_status')
        admin_notes = request.POST.get('admin_notes')
        
        if new_status and new_status != order.order_status:
            # Adjust inventory based on acceptance / cancellation transition
            adjust_inventory_for_order_status_change(order, order.order_status, new_status)

            order.order_status = new_status
            # Auto-mark payment as collected/PAID when delivered
            if new_status == 'DELIVERED' and not new_payment_status and order.payment_status == 'UNPAID':
                order.payment_status = 'PAID'

        if new_payment_status:
            order.payment_status = new_payment_status
        if admin_notes is not None:
            order.admin_notes = admin_notes
            
        order.save()
        messages.success(request, f'Order #{order.order_number} details successfully updated.')
        return redirect('dashboard:order_detail', order_number=order.order_number)

    return render(request, 'dashboard/order_detail.html', {'order': order})


@user_passes_test(is_staff_user, login_url='dashboard:login')
def update_order_status_quick(request, order_number):
    if request.method == 'POST':
        order = get_object_or_404(Order, order_number=order_number)
        new_status = request.POST.get('status')
        if new_status in dict(Order.ORDER_STATUS_CHOICES) and new_status != order.order_status:
            # Adjust inventory based on acceptance / cancellation transition
            adjust_inventory_for_order_status_change(order, order.order_status, new_status)

            order.order_status = new_status
            # When marked as DELIVERED, automatically mark money as collected (PAID)
            if new_status == 'DELIVERED' and order.payment_status == 'UNPAID':
                order.payment_status = 'PAID'
            order.save()
            messages.success(request, f'Order #{order.order_number} status changed to {order.get_order_status_display()}')
            
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'new_status': new_status, 'status_display': order.get_order_status_display()})
            
    return redirect(request.META.get('HTTP_REFERER') or 'dashboard:index')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def edit_order_customer(request, order_number):
    """
    Allows admin to edit customer name, phone, address, city, zone, and recalculate delivery fee.
    """
    order = get_object_or_404(Order, order_number=order_number)
    if request.method == 'POST':
        name = request.POST.get('customer_name', '').strip()
        phone = request.POST.get('customer_phone', '').strip()
        address = request.POST.get('delivery_address', '').strip()
        city = request.POST.get('delivery_city', '').strip()
        zone = request.POST.get('delivery_zone', '').strip()
        email = request.POST.get('customer_email', '').strip()
        notes = request.POST.get('customer_notes', '').strip()
        custom_fee = request.POST.get('delivery_fee', '').strip()

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

        if zone and zone in dict(Order.ZONE_CHOICES):
            order.delivery_zone = zone
            
        if custom_fee:
            try:
                order.delivery_fee = Decimal(str(custom_fee))
            except Exception:
                pass
        elif zone:
            from store.models import calculate_pathao_delivery_fee
            order.delivery_fee = calculate_pathao_delivery_fee(order.total_weight_grams, order.delivery_zone)

        order.total_amount = order.subtotal + order.delivery_fee
        order.save()
        messages.success(request, f"Customer & Delivery Address details updated for Order #{order.order_number}!")

    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def order_invoice(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related('items'), order_number=order_number)
    return render(request, 'dashboard/order_invoice.html', {'order': order})


@user_passes_test(is_staff_user, login_url='dashboard:login')
def dispatch_order_to_pathao(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    fallback_url = request.META.get('HTTP_REFERER') or reverse('dashboard:order_detail', kwargs={'order_number': order_number})
    
    if request.method == 'POST':
        pathao_service = PathaoCourierService()
        
        if not pathao_service.is_configured():
            messages.warning(request, "Pathao API is not configured. Please add PATHAO_CLIENT_ID, PATHAO_CLIENT_SECRET, PATHAO_USERNAME, PATHAO_PASSWORD, and PATHAO_STORE_ID in your environment or settings.")
            return redirect(fallback_url)
            
        result = pathao_service.create_order(order)
        if result.get('success'):
            # Automatically confirm order and adjust inventory if currently pending
            if order.order_status == 'PENDING':
                adjust_inventory_for_order_status_change(order, 'PENDING', 'CONFIRMED')
                order.order_status = 'CONFIRMED'
                order.save(update_fields=['order_status'])
                
            messages.success(request, result.get('message', f'Order #{order.order_number} dispatched to Pathao Courier!'))
        else:
            messages.error(request, result.get('message', 'Failed to dispatch to Pathao.'))
            
    return redirect(fallback_url)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def sync_all_pathao_orders(request):
    """
    1-Click Bulk Sync: Query Pathao Courier API for all active orders with consignment IDs.
    Automatically marks orders as DELIVERED and payment as PAID when delivered.
    """
    active_orders = Order.objects.filter(
        pathao_consignment_id__isnull=False,
        order_status__in=['PENDING', 'CONFIRMED', 'PACKING', 'OUT_FOR_DELIVERY']
    )
    synced_count = 0
    delivered_count = 0

    for order in active_orders:
        old_status = order.order_status
        new_status = order.sync_pathao_status()
        if new_status:
            synced_count += 1
            if old_status != 'DELIVERED' and order.order_status == 'DELIVERED':
                delivered_count += 1

    if synced_count > 0:
        messages.success(request, f"Synced {synced_count} active Pathao orders. {delivered_count} newly marked as Delivered 🎉")
    else:
        messages.info(request, "No active Pathao orders needed syncing, or Pathao API is not configured.")

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
        status = order.sync_pathao_status()
        if status:
            messages.success(request, f"Pathao status updated: {order.pathao_order_status} (Order status: {order.get_order_status_display()})")
        else:
            messages.info(request, "Could not fetch updated status from Pathao Courier API.")
            
    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def create_manual_order(request):
    if request.method == 'POST':
        try:
            customer_name = request.POST.get('customer_name', '').strip()
            customer_phone = request.POST.get('customer_phone', '').strip()
            delivery_address = request.POST.get('delivery_address', '').strip()
            delivery_city = request.POST.get('delivery_city', 'Faridpur').strip()
            delivery_zone = request.POST.get('delivery_zone', 'INSIDE_FARIDPUR')
            payment_method = request.POST.get('payment_method', 'COD')
            payment_status = request.POST.get('payment_status', 'UNPAID')
            payment_trx_id = request.POST.get('payment_trx_id', '').strip()
            customer_notes = request.POST.get('customer_notes', '').strip()
            admin_notes = request.POST.get('admin_notes', 'Manual order created by staff').strip()

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
                        'jar_weight_grams': product.jar_weight_grams
                    })

            if not valid_items:
                messages.error(request, 'None of the selected products were found in the database.')
                return redirect('dashboard:orders')

            # Delivery Fee based on Pathao weight calculation
            total_weight_grams = sum(itm['jar_weight_grams'] * itm['quantity'] for itm in valid_items)
            default_fee = calculate_pathao_delivery_fee(total_weight_grams, delivery_zone)
            delivery_fee_str = request.POST.get('delivery_fee', '').strip()
            try:
                delivery_fee = Decimal(delivery_fee_str) if delivery_fee_str else default_fee
                if delivery_fee < 0:
                    delivery_fee = Decimal('0.00')
            except Exception:
                delivery_fee = default_fee

            total_amount = subtotal + delivery_fee

            order = Order.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                delivery_address=delivery_address,
                delivery_city=delivery_city,
                delivery_zone=delivery_zone,
                delivery_fee=delivery_fee,
                subtotal=subtotal,
                total_amount=total_amount,
                payment_method=payment_method,
                payment_status=payment_status,
                payment_trx_id=payment_trx_id,
                order_status='CONFIRMED',
                customer_notes=customer_notes,
                admin_notes=admin_notes
            )

            # Create OrderItems and deduct stock
            for itm in valid_items:
                prod = itm['product']
                qty = itm['quantity']
                OrderItem.objects.create(
                    order=order,
                    product=prod,
                    product_name=prod.name,
                    jar_weight_grams=itm['jar_weight_grams'],
                    unit_price=itm['unit_price'],
                    quantity=qty,
                    total_price=itm['total_price']
                )

                if prod.stock_count >= qty:
                    prod.stock_count -= qty
                else:
                    prod.stock_count = 0
                if prod.stock_count == 0:
                    prod.is_in_stock = False
                prod.save()

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
    if not request.user.is_superuser:
        messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting orders. Only Administrator can delete orders.')
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
    if not request.user.is_superuser:
        messages.error(request, 'Permission Denied: Staff accounts cannot access the Trash Archive. Administrator privileges required.')
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
    if not request.user.is_superuser:
        messages.error(request, 'Permission Denied: Only Administrator can restore orders from Trash.')
        return redirect('dashboard:orders')

    if request.method == 'POST':
        order = get_object_or_404(Order.trash_objects, order_number=order_number)
        order.restore()
        messages.success(request, f'Order #{order.order_number} for {order.customer_name} has been successfully restored!')
        return redirect('dashboard:orders_trash')
    return redirect('dashboard:orders_trash')


@user_passes_test(is_staff_user, login_url='dashboard:login')
def permanent_delete_order(request, order_number):
    if not request.user.is_superuser:
        messages.error(request, 'Permission Denied: Staff accounts are restricted from permanently deleting orders. Only Administrator can delete.')
        return redirect('dashboard:orders_trash')

    if request.method == 'POST':
        order = get_object_or_404(Order.trash_objects, order_number=order_number)
        o_num = order.order_number
        if order.order_status in ACCEPTED_ORDER_STATUSES:
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
def edit_order_customer(request, order_number):
    if request.method == 'POST':
        order = get_object_or_404(Order, order_number=order_number)
        order.customer_name = request.POST.get('customer_name', order.customer_name).strip()
        order.customer_phone = request.POST.get('customer_phone', order.customer_phone).strip()
        order.delivery_address = request.POST.get('delivery_address', order.delivery_address).strip()
        order.delivery_city = request.POST.get('delivery_city', order.delivery_city).strip()
        order.save()
        messages.success(request, f'Customer shipping details for #{order.order_number} updated.')
        return redirect('dashboard:order_detail', order_number=order.order_number)
    return redirect('dashboard:order_detail', order_number=order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def stock_manager(request):
    selected_cat = request.GET.get('category')
    all_products = Product.objects.all().select_related('category').order_by('name')
    categories = Category.objects.annotate(product_count=Count('products')).order_by('name')
    
    if selected_cat:
        products = all_products.filter(category__slug=selected_cat)
    else:
        products = all_products

    if request.method == 'POST':
        action = request.POST.get('action')
        product_id = request.POST.get('product_id')

        # 1. DELETE PRODUCT
        if action == 'delete_product' or 'delete_product' in request.POST:
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting products. Only Administrator can delete.')
                return redirect('dashboard:stock_manager')
            product = get_object_or_404(Product, id=product_id)
            prod_name = product.name
            product.delete()
            messages.success(request, f'Pickle product "{prod_name}" has been permanently deleted.')
            return redirect('dashboard:stock_manager')

        # 2. FULL EDIT PRODUCT
        elif action == 'edit_product' or 'edit_product' in request.POST:
            product = get_object_or_404(Product, id=product_id)
            try:
                product.name = request.POST.get('name', product.name).strip()
                product.tagline = request.POST.get('tagline', product.tagline).strip()
                product.description = request.POST.get('description', product.description).strip()
                
                cat_id = request.POST.get('category_id')
                if cat_id:
                    product.category = Category.objects.filter(id=cat_id).first()
                else:
                    product.category = None
                    
                product.cut_style = request.POST.get('cut_style', product.cut_style)
                product.spice_level = request.POST.get('spice_level', product.spice_level)
                product.crunch_rating = int(request.POST.get('crunch_rating', product.crunch_rating or 5))
                product.jar_weight_grams = int(request.POST.get('jar_weight_grams', product.jar_weight_grams))
                product.price_bdt = float(request.POST.get('price_bdt', product.price_bdt))
                
                orig_price = request.POST.get('original_price_bdt')
                product.original_price_bdt = float(orig_price) if orig_price else None
                
                product.stock_count = int(request.POST.get('stock_count', product.stock_count))
                product.is_in_stock = request.POST.get('is_in_stock') == 'on' or request.POST.get('is_in_stock') == 'true'
                product.is_featured = request.POST.get('is_featured') == 'on' or request.POST.get('is_featured') == 'true'
                
                image_url = request.POST.get('image_url')
                if image_url:
                    product.image_url = image_url.strip()
                    
                if 'image' in request.FILES:
                    product.image = request.FILES['image']
                    
                product.ingredients = request.POST.get('ingredients', product.ingredients).strip()
                product.flavor_profile = request.POST.get('flavor_profile', product.flavor_profile).strip()
                product.pairing_suggestions = request.POST.get('pairing_suggestions', product.pairing_suggestions).strip()

                product.save()
                messages.success(request, f'Product "{product.name}" has been successfully updated.')
            except Exception as e:
                messages.error(request, f'Failed to update product: {str(e)}')
            return redirect('dashboard:stock_manager')

        # 3. CREATE NEW PRODUCT
        elif action == 'create_product' or 'create_product' in request.POST:
            try:
                name = request.POST.get('name').strip()
                tagline = request.POST.get('tagline', '').strip()
                description = request.POST.get('description', '').strip()
                cat_id = request.POST.get('category_id')
                category = Category.objects.filter(id=cat_id).first() if cat_id else None
                cut_style = request.POST.get('cut_style', 'SPEARS')
                spice_level = request.POST.get('spice_level', 'MILD')
                crunch_rating = int(request.POST.get('crunch_rating', 5))
                jar_weight_grams = int(request.POST.get('jar_weight_grams', 600))
                price_bdt = float(request.POST.get('price_bdt', 380))
                orig_price = request.POST.get('original_price_bdt')
                original_price_bdt = float(orig_price) if orig_price else None
                stock_count = int(request.POST.get('stock_count', 50))
                is_in_stock = request.POST.get('is_in_stock') == 'on' or request.POST.get('is_in_stock') == 'true'
                is_featured = request.POST.get('is_featured') == 'on' or request.POST.get('is_featured') == 'true'
                image_url = request.POST.get('image_url', '').strip()
                ingredients = request.POST.get('ingredients', '').strip()
                flavor_profile = request.POST.get('flavor_profile', '').strip()
                pairing_suggestions = request.POST.get('pairing_suggestions', '').strip()

                new_prod = Product.objects.create(
                    name=name,
                    tagline=tagline or f"Handcrafted {name}",
                    description=description or f"Crisp, delicious handcrafted {name}.",
                    category=category,
                    cut_style=cut_style,
                    spice_level=spice_level,
                    crunch_rating=crunch_rating,
                    jar_weight_grams=jar_weight_grams,
                    price_bdt=price_bdt,
                    original_price_bdt=original_price_bdt,
                    stock_count=stock_count,
                    is_in_stock=is_in_stock,
                    is_featured=is_featured,
                    image_url=image_url or "/static/images/pickle_default.png",
                    ingredients=ingredients or "Fresh Local Cucumbers, Pure Cane Vinegar, Himalayan Pink Salt, Garlic, Spices.",
                    flavor_profile=flavor_profile or "Crisp, Tangy, Garlic & Whole Spices",
                    pairing_suggestions=pairing_suggestions or "Burgers, Sandwiches, Snacks"
                )
                if 'image' in request.FILES:
                    new_prod.image = request.FILES['image']
                    new_prod.save()

                messages.success(request, f'New pickle jar "{new_prod.name}" successfully added to catalog!')
            except Exception as e:
                messages.error(request, f'Failed to create product: {str(e)}')
            return redirect('dashboard:stock_manager')

        # 4. TOGGLE IN-STOCK STATUS
        elif 'toggle_stock' in request.POST or action == 'toggle_stock':
            product = get_object_or_404(Product, id=product_id)
            product.is_in_stock = not product.is_in_stock
            product.save()
            messages.success(request, f'Updated stock availability for "{product.name}".')
            return redirect('dashboard:stock_manager')

        # 5. QUICK PRICE & STOCK UPDATE
        elif 'update_pricing' in request.POST or action == 'update_pricing':
            product = get_object_or_404(Product, id=product_id)
            try:
                new_price = request.POST.get('price_bdt')
                new_stock = request.POST.get('stock_count')
                if new_price:
                    product.price_bdt = float(new_price)
                if new_stock:
                    product.stock_count = int(new_stock)
                product.save()
                messages.success(request, f'Updated price & inventory for "{product.name}".')
            except ValueError:
                messages.error(request, 'Invalid price or stock count format.')
            return redirect('dashboard:stock_manager')

        # 6. CREATE CATEGORY
        elif action == 'create_category' or 'create_category' in request.POST:
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
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting categories. Only Administrator can delete.')
                return redirect('dashboard:stock_manager')
            cat_id = request.POST.get('category_id')
            cat = get_object_or_404(Category, id=cat_id)
            c_name = cat.name
            cat.delete()
            messages.success(request, f'Category "{c_name}" deleted successfully.')
            return redirect('dashboard:stock_manager')

    context = {
        'products': products,
        'categories': categories,
        'selected_cat': selected_cat,
        'spice_choices': Product.SPICE_CHOICES,
        'cut_choices': Product.CUT_CHOICES,
        'total_products_count': all_products.count(),
        'in_stock_count': all_products.filter(is_in_stock=True).count(),
        'out_of_stock_count': all_products.filter(is_in_stock=False).count(),
    }
    return render(request, 'dashboard/stock_manager.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def damage_returns_manager(request):
    """Manager for recording broken/damaged pickle jars and courier returned parcels."""
    now = timezone.now()
    today = now.date()
    
    damage_logs = DamageLog.objects.all().select_related('product').order_by('-incident_date', '-created_at')
    order_returns = OrderReturn.objects.all().select_related('order').prefetch_related('order__items').order_by('-created_at')
    products = Product.objects.all().order_by('name')
    orders = Order.objects.all().order_by('-created_at')[:100]

    if request.method == 'POST':
        action = request.POST.get('action')

        # 1. RECORD DAMAGE LOG
        if action == 'record_damage':
            try:
                prod_id = request.POST.get('product_id')
                product = get_object_or_404(Product, id=prod_id)
                quantity = int(request.POST.get('quantity', 1))
                estimated_cost = float(request.POST.get('estimated_cost_per_jar', 200.00))
                reason = request.POST.get('reason', 'TRANSIT_BREAKAGE')
                incident_date = request.POST.get('incident_date') or today
                order_ref = request.POST.get('order_ref', '').strip()
                notes = request.POST.get('notes', '').strip()
                deduct_stock = request.POST.get('deduct_stock') == 'on'

                # Deduct from product stock if requested
                if deduct_stock and product.stock_count >= quantity:
                    product.stock_count = max(0, product.stock_count - quantity)
                    if product.stock_count == 0:
                        product.is_in_stock = False
                    product.save()

                DamageLog.objects.create(
                    product=product,
                    quantity=quantity,
                    estimated_cost_per_jar=estimated_cost,
                    reason=reason,
                    incident_date=incident_date,
                    order_ref=order_ref,
                    notes=notes
                )
                messages.success(request, f'Logged {quantity}x {product.name} damage. Stock updated.')
            except Exception as e:
                messages.error(request, f'Failed to record damage: {str(e)}')
            return redirect('dashboard:damage_returns')

        # 2. DELETE DAMAGE LOG
        elif action == 'delete_damage':
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting damage logs. Only Administrator can delete.')
                return redirect('dashboard:damage_returns')
            damage_id = request.POST.get('damage_id')
            log = get_object_or_404(DamageLog, id=damage_id)
            log.delete()
            messages.success(request, 'Damage record deleted.')
            return redirect('dashboard:damage_returns')

        # 3. RECORD COURIER RETURN
        elif action == 'record_return':
            try:
                order_id = request.POST.get('order_id')
                order = get_object_or_404(Order, id=order_id)
                return_reason = request.POST.get('return_reason', 'CUSTOMER_REFUSED')
                return_status = request.POST.get('return_status', 'RETURNING')
                courier_return_fee = float(request.POST.get('courier_return_fee', 0.00))
                notes = request.POST.get('notes', '').strip()
                restock_now = request.POST.get('restock_now') == 'on'

                is_restocked = False
                if return_status == 'RECEIVED_INTACT' and restock_now:
                    # Restock ordered items back to products
                    for item in order.items.all():
                        if item.product:
                            item.product.stock_count += item.quantity
                            item.product.is_in_stock = True
                            item.product.save()
                    is_restocked = True

                # If received damaged, log as damage loss automatically
                if return_status == 'RECEIVED_DAMAGED':
                    for item in order.items.all():
                        if item.product:
                            DamageLog.objects.create(
                                product=item.product,
                                quantity=item.quantity,
                                estimated_cost_per_jar=200.00,
                                reason='RETURN_DAMAGED',
                                incident_date=today,
                                order_ref=order.order_number,
                                notes=f"Automatic damage log from returned Order #{order.order_number}"
                            )

                # Set order status to CANCELLED / RETURNED
                order.order_status = 'CANCELLED'
                order.admin_notes = f"{order.admin_notes}\n[RETURN LOGGED: {return_reason} - Status: {return_status}]".strip()
                order.save()

                OrderReturn.objects.create(
                    order=order,
                    return_reason=return_reason,
                    return_status=return_status,
                    courier_return_fee=courier_return_fee,
                    is_restocked=is_restocked,
                    notes=notes
                )
                messages.success(request, f'Return logged for Order #{order.order_number}.')
            except Exception as e:
                messages.error(request, f'Failed to record return: {str(e)}')
            return redirect('dashboard:damage_returns')

        # 4. UPDATE RETURN STATUS
        elif action == 'update_return_status':
            try:
                ret_id = request.POST.get('return_id')
                ret = get_object_or_404(OrderReturn, id=ret_id)
                new_status = request.POST.get('new_status')
                courier_fee = float(request.POST.get('courier_return_fee', ret.courier_return_fee))
                notes = request.POST.get('notes', ret.notes)
                
                # If marking as received intact and not previously restocked
                if new_status == 'RECEIVED_INTACT' and not ret.is_restocked:
                    for item in ret.order.items.all():
                        if item.product:
                            item.product.stock_count += item.quantity
                            item.product.is_in_stock = True
                            item.product.save()
                    ret.is_restocked = True

                # If marking as received damaged
                if new_status == 'RECEIVED_DAMAGED' and ret.return_status != 'RECEIVED_DAMAGED':
                    for item in ret.order.items.all():
                        if item.product:
                            DamageLog.objects.create(
                                product=item.product,
                                quantity=item.quantity,
                                estimated_cost_per_jar=200.00,
                                reason='RETURN_DAMAGED',
                                incident_date=today,
                                order_ref=ret.order.order_number,
                                notes=f"Automatic damage log from returned Order #{ret.order.order_number}"
                            )

                ret.return_status = new_status
                ret.courier_return_fee = courier_fee
                ret.notes = notes
                ret.save()
                messages.success(request, f'Return for #{ret.order.order_number} updated to {ret.get_return_status_display()}.')
            except Exception as e:
                messages.error(request, f'Failed to update return: {str(e)}')
            return redirect('dashboard:damage_returns')

    # Aggregations
    total_damaged_jars = damage_logs.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_damage_loss = float(damage_logs.aggregate(Sum('total_loss_bdt'))['total_loss_bdt__sum'] or 0)
    
    total_returns_count = order_returns.count()
    total_courier_fees = float(order_returns.aggregate(Sum('courier_return_fee'))['courier_return_fee__sum'] or 0)
    intact_returns_count = order_returns.filter(return_status='RECEIVED_INTACT').count()
    damaged_returns_count = order_returns.filter(return_status='RECEIVED_DAMAGED').count()
    pending_returning_count = order_returns.filter(return_status='RETURNING').count()

    total_combined_loss = total_damage_loss + total_courier_fees

    context = {
        'damage_logs': damage_logs,
        'order_returns': order_returns,
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
        reason = request.POST.get('return_reason', 'CUSTOMER_REFUSED')
        status = request.POST.get('return_status', 'RETURNING')
        fee = float(request.POST.get('courier_return_fee', 0.00))
        notes = request.POST.get('notes', '').strip()

        order.order_status = 'CANCELLED'
        order.save()

        OrderReturn.objects.create(
            order=order,
            return_reason=reason,
            return_status=status,
            courier_return_fee=fee,
            notes=notes
        )
        messages.success(request, f'Order #{order.order_number} marked as return in progress.')
    return redirect('dashboard:order_detail', order_number=order.order_number)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def reviews_manager(request):
    reviews = Review.objects.all().select_related('product').order_by('-created_at')
    products = Product.objects.all().order_by('name')

    if request.method == 'POST':
        action = request.POST.get('action')
        review_id = request.POST.get('review_id')

        # 1. Toggle Approve
        if action == 'toggle_approve':
            review = get_object_or_404(Review, id=review_id)
            review.is_approved = not review.is_approved
            review.save()
            status_txt = 'approved & visible' if review.is_approved else 'hidden'
            messages.success(request, f'Review by {review.reviewer_name} is now {status_txt}.')
            return redirect('dashboard:reviews')

        # 2. Delete Review
        elif action == 'delete_review':
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting reviews. Only Administrator can delete.')
                return redirect('dashboard:reviews')
            review = get_object_or_404(Review, id=review_id)
            r_name = review.reviewer_name
            review.delete()
            messages.success(request, f'Review from {r_name} deleted successfully.')
            return redirect('dashboard:reviews')

        # 3. Add Manual Review
        elif action == 'create_review':
            prod_id = request.POST.get('product_id')
            product = get_object_or_404(Product, id=prod_id)
            name = request.POST.get('reviewer_name', 'Verified Customer').strip()
            location = request.POST.get('reviewer_location', 'Dhaka').strip()
            rating = int(request.POST.get('rating', 5))
            crunch_score = int(request.POST.get('crunch_score', 5))
            comment = request.POST.get('comment', '').strip()

            Review.objects.create(
                product=product,
                reviewer_name=name,
                reviewer_location=location,
                rating=rating,
                comment=comment,
                is_approved=True
            )
            messages.success(request, f'Review for {product.name} added successfully!')
            return redirect('dashboard:reviews')

    context = {
        'reviews': reviews,
        'products': products,
        'total_reviews': reviews.count(),
        'approved_count': reviews.filter(is_approved=True).count(),
    }
    return render(request, 'dashboard/reviews.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def expense_manager(request):
    now = timezone.now()
    today = now.date()

    if request.method == 'POST':
        action = request.POST.get('action')
        expense_id = request.POST.get('expense_id')

        # 1. CREATE EXPENSE
        if action == 'create_expense' or 'create_expense' in request.POST:
            try:
                title = request.POST.get('title').strip()
                category = request.POST.get('category', 'RAW_MATERIAL')
                amount = float(request.POST.get('amount'))
                expense_date = request.POST.get('expense_date') or today
                payment_method = request.POST.get('payment_method', 'CASH')
                receipt_reference = request.POST.get('receipt_reference', '').strip()
                notes = request.POST.get('notes', '').strip()

                Expense.objects.create(
                    title=title,
                    category=category,
                    amount=amount,
                    expense_date=expense_date,
                    payment_method=payment_method,
                    receipt_reference=receipt_reference,
                    notes=notes
                )
                messages.success(request, f'Expense "৳{amount} - {title}" successfully recorded.')
            except Exception as e:
                messages.error(request, f'Failed to record expense: {str(e)}')
            return redirect('dashboard:expenses')

        # 2. EDIT EXPENSE
        elif action == 'edit_expense' or 'edit_expense' in request.POST:
            expense = get_object_or_404(Expense, id=expense_id)
            try:
                expense.title = request.POST.get('title', expense.title).strip()
                expense.category = request.POST.get('category', expense.category)
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
            return redirect('dashboard:expenses')

        # 3. DELETE EXPENSE
        elif action == 'delete_expense' or 'delete_expense' in request.POST:
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting expense records. Only Administrator can delete.')
                return redirect('dashboard:expenses')
            expense = get_object_or_404(Expense, id=expense_id)
            title = expense.title
            amount = expense.amount
            expense.delete()
            messages.success(request, f'Expense record "৳{amount} - {title}" has been deleted.')
            return redirect('dashboard:expenses')

    # Query & Filters
    expenses = Expense.objects.all()
    category_filter = request.GET.get('category', 'ALL')
    search_query = request.GET.get('q', '').strip()

    if category_filter and category_filter != 'ALL':
        expenses = expenses.filter(category=category_filter)

    if search_query:
        expenses = expenses.filter(
            Q(title__icontains=search_query) |
            Q(receipt_reference__icontains=search_query) |
            Q(notes__icontains=search_query)
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
            ('Glass Jars, Lids & Labels 🫙', 'PACKAGING', 'fa-jar', 'Food-grade glass jars, airtight gold metal lids, and stickers.'),
            ('Vinegar, Garlic & Whole Spices 🌿', 'SPICES_BRINE', 'fa-leaf', 'Pure cane vinegar, pickling salt, bay leaf, mustard seeds, and brine spices.'),
            ('Courier & Rider Delivery Cost 🚚', 'LOGISTICS', 'fa-truck-fast', 'Courier parcel shipping fees and direct delivery rider charges.'),
            ('Digital Ads & Marketing 📢', 'MARKETING', 'fa-bullhorn', 'Facebook page sponsored ads, boost campaigns, and promotion.'),
            ('Gas, Electricity & Kitchen Rent ⚡', 'UTILITIES', 'fa-bolt', 'Kitchen utilities, gas cylinders, and production space rent.'),
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

    expense_chart_data = {
        'catLabels': chart_cat_labels,
        'catData': chart_cat_data,
        'comparisonLabels': ['Gross Revenue (৳)', 'Total Costs (৳)', 'Net Profit (৳)'],
        'comparisonData': [float(total_revenue), float(total_expenses), max(0, net_profit)]
    }

    context = {
        'expenses': expenses,
        'dynamic_categories': ExpenseCategory.objects.all(),
        'category_choices': Expense.CATEGORY_CHOICES,
        'payment_choices': Expense.PAYMENT_CHOICES,
        'category_filter': category_filter,
        'search_query': search_query,
        'total_expenses': total_expenses,
        'total_revenue': total_revenue,
        'pipeline_revenue': pipeline_revenue,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'this_month_expenses': this_month_expenses,
        'expense_count': expenses.count(),
        'expense_chart_json': json.dumps(expense_chart_data),
    }
    return render(request, 'dashboard/expenses.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def financial_statement(request):
    now = timezone.now()
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
        
    cat_expenses = []
    for item in cat_summary:
        cat_name = cat_map.get(item['category'], item['category'])
        cat_expenses.append({
            'name': cat_name,
            'category_code': item['category'],
            'amount': float(item['total']),
            'count': item['count'],
            'percentage': round((float(item['total']) / total_expenses) * 100, 1) if total_expenses > 0 else 0
        })

    # 3. Net Profit / Loss
    net_profit = gross_revenue - total_expenses
    profit_margin = round((net_profit / gross_revenue) * 100, 1) if gross_revenue > 0 else 0
    is_profitable = net_profit >= 0

    # 4. Combined Transaction Stream (Delivered Orders + Expenses in chronological order)
    combined_transactions = []
    
    for order in delivered_qs.order_by('-created_at')[:150]:
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

    for exp in expenses_qs.order_by('-expense_date', '-created_at')[:150]:
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
        'transactions': combined_transactions,
        'now': now,
    }
    return render(request, 'dashboard/statement.html', context)


@user_passes_test(is_staff_user, login_url='dashboard:login')
def financial_statement_print(request):
    """Standalone, clean printable view for saving as PDF or printing on paper."""
    now = timezone.now()
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
        
    cat_expenses = []
    for item in cat_summary:
        cat_name = cat_map.get(item['category'], item['category'])
        cat_expenses.append({
            'name': cat_name,
            'amount': float(item['total']),
            'count': item['count'],
            'percentage': round((float(item['total']) / total_expenses) * 100, 1) if total_expenses > 0 else 0
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
def admin_users_manager(request):
    if not request.user.is_superuser:
        messages.error(request, 'Permission Denied: Only Administrator has access to Staff & Admin user management.')
        return redirect('dashboard:index')

    users = User.objects.all().order_by('-date_joined')

    if request.method == 'POST':
        action = request.POST.get('action')
        user_id = request.POST.get('user_id')

        # 1. CREATE ADMIN / STAFF USER
        if action == 'create_user':
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '').strip()
            is_staff = request.POST.get('is_staff') == 'on'
            is_superuser = request.POST.get('is_superuser') == 'on'

            if not username or not password:
                messages.error(request, 'Username and password are required.')
            elif User.objects.filter(username=username).exists():
                messages.error(request, f'Username "{username}" already exists.')
            else:
                new_user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    is_staff=is_staff or is_superuser,
                    is_superuser=is_superuser
                )
                messages.success(request, f'Admin user "{username}" created successfully!')
            return redirect('dashboard:admin_users')

        # 2. CHANGE USER PASSWORD
        elif action == 'change_password':
            target_user = get_object_or_404(User, id=user_id)
            new_pw = request.POST.get('new_password', '').strip()
            if new_pw:
                target_user.set_password(new_pw)
                target_user.save()
                messages.success(request, f'Password for {target_user.username} updated successfully.')
            else:
                messages.error(request, 'Password cannot be empty.')
            return redirect('dashboard:admin_users')

        # 3. TOGGLE STAFF STATUS
        elif action == 'toggle_staff':
            target_user = get_object_or_404(User, id=user_id)
            if target_user == request.user and target_user.is_superuser:
                messages.error(request, 'You cannot remove your own superuser access.')
            else:
                target_user.is_staff = not target_user.is_staff
                target_user.save()
                messages.success(request, f'Staff status for {target_user.username} updated.')
            return redirect('dashboard:admin_users')

        # 4. DELETE USER
        elif action == 'delete_user':
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting users. Only Administrator can delete.')
                return redirect('dashboard:admin_users')
            target_user = get_object_or_404(User, id=user_id)
            if target_user == request.user:
                messages.error(request, 'You cannot delete your own account.')
            else:
                u_name = target_user.username
                target_user.delete()
                messages.success(request, f'User account "{u_name}" deleted.')
            return redirect('dashboard:admin_users')

    context = {
        'users': users,
        'total_users': users.count(),
        'staff_count': users.filter(is_staff=True).count(),
        'superuser_count': users.filter(is_superuser=True).count(),
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
            cat = get_object_or_404(Category, id=cat_id)
            cat.name = request.POST.get('name', cat.name).strip()
            cat.description = request.POST.get('description', cat.description).strip()
            cat.icon = request.POST.get('icon', cat.icon).strip()
            cat.save()
            messages.success(request, f'Pickle Category "{cat.name}" updated.')
            return redirect('dashboard:pickle_categories')

        # 3. Delete Category
        elif action == 'delete_category':
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting categories. Only Administrator can delete.')
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
            ('Glass Jars, Lids & Labels 🫙', 'PACKAGING', 'fa-jar', 'Food-grade glass jars, airtight gold metal lids, and stickers.'),
            ('Vinegar, Garlic & Whole Spices 🌿', 'SPICES_BRINE', 'fa-leaf', 'Pure cane vinegar, pickling salt, bay leaf, mustard seeds, and brine spices.'),
            ('Courier & Rider Delivery Cost 🚚', 'LOGISTICS', 'fa-truck-fast', 'Courier parcel shipping fees and direct delivery rider charges.'),
            ('Digital Ads & Marketing 📢', 'MARKETING', 'fa-bullhorn', 'Facebook page sponsored ads, boost campaigns, and promotion.'),
            ('Gas, Electricity & Kitchen Rent ⚡', 'UTILITIES', 'fa-bolt', 'Kitchen utilities, gas cylinders, and production space rent.'),
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
            name = request.POST.get('name', '').strip()
            icon = request.POST.get('icon', 'fa-receipt').strip()
            description = request.POST.get('description', '').strip()
            if name:
                ExpenseCategory.objects.create(name=name, icon=icon, description=description)
                messages.success(request, f'Expense Category "{name}" created successfully!')
            else:
                messages.error(request, 'Category name is required.')
            return redirect('dashboard:expense_categories')

        # 2. Edit Category
        elif action == 'edit_category':
            cat = get_object_or_404(ExpenseCategory, id=cat_id)
            cat.name = request.POST.get('name', cat.name).strip()
            cat.icon = request.POST.get('icon', cat.icon).strip()
            cat.description = request.POST.get('description', cat.description).strip()
            cat.save()
            messages.success(request, f'Expense Category "{cat.name}" updated.')
            return redirect('dashboard:expense_categories')

        # 3. Delete Category
        elif action == 'delete_category':
            if not request.user.is_superuser:
                messages.error(request, 'Permission Denied: Staff accounts are restricted from deleting categories. Only Administrator can delete.')
                return redirect('dashboard:expense_categories')
            cat = get_object_or_404(ExpenseCategory, id=cat_id)
            c_name = cat.name
            cat.delete()
            messages.success(request, f'Expense Category "{c_name}" deleted.')
            return redirect('dashboard:expense_categories')

    # Load categories with stats
    categories = ExpenseCategory.objects.all().order_by('name')
    category_stats = []
    for cat in categories:
        # Match both by slug and by name
        spent = Expense.objects.filter(
            Q(category=cat.slug) | Q(category=cat.name)
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        count = Expense.objects.filter(
            Q(category=cat.slug) | Q(category=cat.name)
        ).count()
        category_stats.append({
            'id': cat.id,
            'slug': cat.slug,
            'name': cat.name,
            'icon': cat.icon or 'fa-receipt',
            'description': cat.description,
            'spent': spent,
            'count': count
        })

    context = {
        'category_stats': category_stats,
        'total_categories': len(category_stats),
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

    pending_count = Order.objects.filter(order_status='PENDING').count()

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
                'created_at_time': o.created_at.strftime('%I:%M %p'),
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
            'created_at_time': o.created_at.strftime('%d %b, %I:%M %p'),
            'detail_url': reverse('dashboard:order_detail', kwargs={'order_number': o.order_number}),
        })

    return JsonResponse({
        'status': 'ok',
        'latest_id': latest_id,
        'has_new': len(new_orders_data) > 0,
        'new_orders': new_orders_data,
        'pending_count': pending_count,
        'recent_pending': recent_pending_data,
    })


def launch_pos_driver(request):
    """
    Launch the local RongTa POS thermal printer driver installer directly on Windows.
    """
    if not (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
        return JsonResponse({'status': 'error', 'message': 'Staff authorization required.'}, status=403)

    import os
    from django.conf import settings
    driver_path = os.path.join(settings.BASE_DIR, 'static', 'driver', 'RongTaDriverInstall_V2.70.exe')
    if not os.path.exists(driver_path):
        alt_path = os.path.join(settings.BASE_DIR, 'static', 'driver', 'Thermal Printer Driver（Windows）', 'RongTaDriverInstall V2.70.exe')
        if os.path.exists(alt_path):
            driver_path = alt_path

    if os.path.exists(driver_path):
        try:
            if hasattr(os, 'startfile'):
                os.startfile(driver_path)
            else:
                import subprocess
                subprocess.Popen([driver_path])
            return JsonResponse({'status': 'success', 'message': 'Installer window opened! Please check your Windows taskbar or screen.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Could not launch installer: {str(e)}'}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Driver installer file not found in static/driver/'}, status=404)


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
    
    # Live Pathao Tracking check on latest consignment
    pathao_svc = PathaoCourierService()
    pathao_consignments = []
    
    orders_data = []
    for o in matching_orders.order_by('-created_at')[:8]:
        p_status = o.pathao_order_status or ''
        # If order has consignment ID, check live info from Pathao
        if o.pathao_consignment_id and pathao_svc.is_configured():
            try:
                info_res = pathao_svc.get_order_info(o.pathao_consignment_id)
                if info_res.get('success'):
                    p_info = info_res.get('data', {})
                    p_status = p_info.get('order_status') or p_info.get('delivery_status') or p_status
                    pathao_consignments.append({
                        'consignment_id': o.pathao_consignment_id,
                        'order_number': o.order_number,
                        'status': p_status,
                    })
            except Exception:
                pass

        orders_data.append({
            'order_number': o.order_number,
            'status': o.get_order_status_display(),
            'status_code': o.order_status,
            'total_amount': float(o.total_amount),
            'created_at': o.created_at.strftime('%d %b, %Y'),
            'pathao_id': o.pathao_consignment_id or '',
            'pathao_status': p_status,
        })
    
    # Trust & Risk Evaluation
    if cancelled_count > 0:
        trust_level = 'RISK'
        trust_title = '⚠️ সতর্ক থাকুন (রিটার্ন/ক্যানসেল রেকর্ড আছে)'
        trust_badge_class = 'bg-rose-100 text-rose-800 border-rose-200'
        trust_desc = f'পূর্বে এই নম্বর থেকে {cancelled_count}টি অর্ডার ক্যানসেল বা রিটার্ন হয়েছে। পার্সেল পাঠানোর আগে ফোনে কথা বলে বা ডেলিভারি চার্জ অগ্রিম নিয়ে নিশ্চিত হওয়া নিরাপদ।'
    elif total_orders >= 2:
        trust_level = 'TRUSTED'
        trust_title = '🟢 বিশ্বস্ত ও নিয়মিত কাস্টমার (Safe)'
        trust_badge_class = 'bg-emerald-100 text-emerald-800 border-emerald-200'
        trust_desc = f'পূর্বে {total_orders}টি সফল অর্ডার সম্পন্ন হয়েছে (মোট খরচ: ৳{total_spent:,.0f})। কোনো রিটার্ন নেই, নিশ্চিন্তে পার্সেল পাঠাতে পারেন।'
    elif total_orders == 1:
        trust_level = 'NEW'
        trust_title = '🔵 নতুন কাস্টমার (১ম অর্ডার)'
        trust_badge_class = 'bg-blue-100 text-blue-800 border-blue-200'
        trust_desc = 'পিকপিকলসে এটি কাস্টমারের ১ম অর্ডার। কোনো খারাপ রেকর্ড নেই। ডেলিভারি লোকেশন ও ফোন নম্বর চেক করে পাঠিয়ে দিন।'
    else:
        trust_level = 'CLEAN'
        trust_title = '⚪ ফ্রেশ নম্বর (কোনো ব্যাড হিস্ট্রি নেই)'
        trust_badge_class = 'bg-slate-100 text-slate-800 border-slate-200'
    pathao_api_info = {
        'connected': pathao_svc.is_configured(),
        'store_id': pathao_svc.store_id or '446187',
        'store_name': 'Pick pickles',
        'hub_name': 'Faridpur Hub',
        'api_host': pathao_svc.base_url,
        'consignments_checked': len(pathao_consignments),
        'consignments': pathao_consignments,
    }

    return JsonResponse({
        'status': 'success',
        'phone': phone,
        'clean_phone': formatted_phone,
        'total_orders': total_orders,
        'delivered_count': delivered_count,
        'cancelled_count': cancelled_count,
        'pending_count': pending_count,
        'success_rate': success_rate,
        'total_spent': float(total_spent),
        'all_spent': float(all_spent),
        'first_order_date': first_order.created_at.strftime('%b %d, %Y') if first_order else None,
        'latest_order_number': latest_order.order_number if latest_order else None,
        'is_repeat_customer': total_orders > 1,
        'trust_level': trust_level,
        'trust_title': trust_title,
        'trust_badge_class': trust_badge_class,
        'trust_desc': trust_desc,
        'pathao_api_info': pathao_api_info,
        'pathao_consignments': pathao_consignments,
        'recent_orders': orders_data,
    })



