"""
Pickpickles FIFO (First-In, First-Out) Batch Management & Sales Tracking Engine
Calculates which production batch is currently active and should be sold next,
and tracks cumulative sales progress across all production batches.
"""
from decimal import Decimal
from django.db.models import Sum
from dashboard.models import ProductionBatch, BatchItem
from store.models import Product, OrderItem


def get_fifo_sales_by_product():
    """
    Returns a dictionary mapping product_id -> total jars sold across valid active orders.
    Excludes cancelled orders and deleted orders.
    """
    sales_map = {}
    rows = OrderItem.objects.filter(
        order__is_deleted=False
    ).exclude(
        order__order_status='CANCELLED'
    ).values('product_id').annotate(
        total_qty=Sum('quantity')
    )
    for row in rows:
        pid = row['product_id']
        if pid:
            sales_map[pid] = row['total_qty'] or 0
    return sales_map


def calculate_all_products_fifo():
    """
    Computes FIFO batch state for all catalog products in two efficient database queries.
    Returns:
        dict: {product_id: product_fifo_data}
    """
    sales_by_product = get_fifo_sales_by_product()

    # Pre-fetch all batch items with their parent batch and product
    all_batch_items = list(
        BatchItem.objects.select_related('batch', 'product')
        .order_by('batch__production_date', 'batch__id', 'id')
    )

    items_by_product = {}
    for bi in all_batch_items:
        items_by_product.setdefault(bi.product_id, []).append(bi)

    products = list(Product.objects.all().select_related('category').order_by('name'))
    results = {}

    for prod in products:
        pid = prod.id
        total_sold = sales_by_product.get(pid, 0)
        bi_list = items_by_product.get(pid, [])

        remaining_sales_to_allocate = total_sold
        batch_entries = []
        active_batch_entry = None

        total_produced = sum(item.quantity for item in bi_list)

        for bi in bi_list:
            qty = bi.quantity
            b = bi.batch

            if remaining_sales_to_allocate >= qty:
                sold_qty = qty
                rem_qty = 0
                status = 'SOLD_OUT'
                status_bn = '১০০% বিক্রিত'
                remaining_sales_to_allocate -= qty
            elif remaining_sales_to_allocate > 0:
                sold_qty = remaining_sales_to_allocate
                rem_qty = qty - remaining_sales_to_allocate
                status = 'ACTIVE'
                status_bn = 'বর্তমানে চলছে'
                remaining_sales_to_allocate = 0
            else:
                sold_qty = 0
                rem_qty = qty
                # If no previous batch has remaining jars, this is the first available batch
                if active_batch_entry is None and rem_qty > 0:
                    status = 'ACTIVE'
                    status_bn = 'বর্তমানে চলছে'
                else:
                    status = 'QUEUED'
                    status_bn = 'অপেক্ষমাণ'

            pct = round((sold_qty / qty * 100), 1) if qty > 0 else 100.0

            entry = {
                'batch_id': b.id,
                'batch_number': b.batch_number,
                'production_date': b.production_date,
                'produced_qty': qty,
                'sold_qty': sold_qty,
                'remaining_qty': rem_qty,
                'status': status,
                'status_bn': status_bn,
                'percent_sold': pct,
                'batch_notes': b.notes,
            }
            batch_entries.append(entry)

            if status == 'ACTIVE' and active_batch_entry is None and rem_qty > 0:
                active_batch_entry = entry

        # If all batches were completely sold out, check if there are no batches left
        has_batches = len(batch_entries) > 0
        all_sold = has_batches and all(e['status'] == 'SOLD_OUT' for e in batch_entries)

        results[pid] = {
            'product': prod,
            'product_id': pid,
            'product_name': prod.name,
            'stock_count': prod.stock_count,
            'total_sold': total_sold,
            'total_produced': total_produced,
            'has_batches': has_batches,
            'all_sold_out': all_sold,
            'active_batch': active_batch_entry,
            'batches': batch_entries,
        }

    return results


def calculate_all_batches_fifo():
    """
    Computes FIFO batch state grouped by ProductionBatch.
    Returns:
        dict: {batch_id: batch_fifo_data}
    """
    products_fifo = calculate_all_products_fifo()

    # We map back into batches
    batch_map = {}

    for pid, pdata in products_fifo.items():
        for b_entry in pdata['batches']:
            bid = b_entry['batch_id']
            if bid not in batch_map:
                batch_map[bid] = {
                    'batch_id': bid,
                    'batch_number': b_entry['batch_number'],
                    'production_date': b_entry['production_date'],
                    'notes': b_entry['batch_notes'],
                    'total_produced': 0,
                    'total_sold': 0,
                    'total_remaining': 0,
                    'items': [],
                    'active_flavors': [],
                }

            batch_map[bid]['total_produced'] += b_entry['produced_qty']
            batch_map[bid]['total_sold'] += b_entry['sold_qty']
            batch_map[bid]['total_remaining'] += b_entry['remaining_qty']

            item_info = dict(b_entry)
            item_info['product_name'] = pdata['product_name']
            item_info['product_id'] = pid
            item_info['stock_count'] = pdata['stock_count']
            batch_map[bid]['items'].append(item_info)

            if b_entry['status'] == 'ACTIVE' and b_entry['remaining_qty'] > 0:
                batch_map[bid]['active_flavors'].append({
                    'product_name': pdata['product_name'],
                    'product_id': pid,
                    'remaining_qty': b_entry['remaining_qty'],
                    'produced_qty': b_entry['produced_qty'],
                    'sold_qty': b_entry['sold_qty'],
                })

    for bid, binfo in batch_map.items():
        produced = binfo['total_produced']
        sold = binfo['total_sold']
        remaining = binfo['total_remaining']

        pct = round((sold / produced * 100), 1) if produced > 0 else 0.0
        binfo['percent_sold'] = pct

        if produced > 0 and sold >= produced:
            binfo['status'] = 'COMPLETED'
            binfo['status_bn'] = '১০০% বিক্রিত'
            binfo['status_badge_class'] = 'bg-gray-100 text-gray-700 border-gray-200'
        elif len(binfo['active_flavors']) > 0 or (sold > 0 and remaining > 0):
            binfo['status'] = 'ACTIVE'
            binfo['status_bn'] = 'বর্তমানে চলছে'
            binfo['status_badge_class'] = 'bg-emerald-100 text-emerald-800 border-emerald-300 animate-pulse'
        else:
            binfo['status'] = 'QUEUED'
            binfo['status_bn'] = 'অপেক্ষমাণ'
            binfo['status_badge_class'] = 'bg-amber-100 text-amber-900 border-amber-300'

    return batch_map


def get_active_selling_recommendations():
    """
    Returns an organized list of active batches to sell right now across all products.
    Used for top recommendation widgets on Stock Manager, Dashboard, and Production Batches.
    """
    products_fifo = calculate_all_products_fifo()
    active_list = []

    for pid, pdata in sorted(products_fifo.items(), key=lambda x: x[1]['product_name']):
        active_b = pdata['active_batch']
        if active_b:
            active_list.append({
                'product_id': pid,
                'product_name': pdata['product_name'],
                'product': pdata['product'],
                'stock_count': pdata['stock_count'],
                'total_sold': pdata['total_sold'],
                'batch_id': active_b['batch_id'],
                'batch_number': active_b['batch_number'],
                'production_date': active_b['production_date'],
                'remaining_in_batch': active_b['remaining_qty'],
                'produced_in_batch': active_b['produced_qty'],
                'sold_from_batch': active_b['sold_qty'],
                'percent_sold': active_b['percent_sold'],
            })
        elif pdata['all_sold_out']:
            active_list.append({
                'product_id': pid,
                'product_name': pdata['product_name'],
                'product': pdata['product'],
                'stock_count': pdata['stock_count'],
                'total_sold': pdata['total_sold'],
                'batch_id': None,
                'batch_number': 'All Batches Sold Out (স্টক শেষ / নতুন ব্যাচ প্রয়োজন)',
                'production_date': None,
                'remaining_in_batch': 0,
                'produced_in_batch': 0,
                'sold_from_batch': pdata['total_sold'],
                'percent_sold': 100.0,
                'is_sold_out': True,
            })

    return active_list
