import json
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, HttpResponseServerError
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .models import Product, Category, Order, OrderItem, Review
from .cart import Cart
from .forms import CheckoutForm, ReviewForm


from django.db.models import Count, Q, Sum, Value, IntegerField, Case, When
from django.db.models.functions import Coalesce


def index(request):
    # Auto-calculate top 3 best seller products based on total delivered/paid sales (matching dashboard ranking)
    best_sellers_qs = Product.objects.annotate(
        total_sold=Coalesce(
            Sum('order_items__quantity', filter=Q(order_items__order__is_deleted=False) & (
                Q(order_items__order__order_status__in=['DELIVERED', 'OUT_FOR_DELIVERY']) |
                Q(order_items__order__payment_status='PAID')
            )),
            Value(0),
            output_field=IntegerField()
        )
    ).order_by('-total_sold', '-is_featured', 'id')

    top_best_sellers = list(best_sellers_qs[:3])
    if len(top_best_sellers) < 3:
        needed = 3 - len(top_best_sellers)
        existing_ids = [p.id for p in top_best_sellers]
        fallback_products = list(
            Product.objects.exclude(id__in=existing_ids)
            .order_by('-is_featured', 'id')[:needed]
        )
        top_best_sellers.extend(fallback_products)

    top_3_ids = []
    for idx, p in enumerate(top_best_sellers, start=1):
        p.best_seller_rank = idx
        top_3_ids.append(p.id)

    best_seller = top_best_sellers[0] if top_best_sellers else None

    # Products with active custom_badge (sale / promotional message) get top priority in product categories/grid
    has_sale_badge = Case(
        When(Q(custom_badge__isnull=False) & ~Q(custom_badge=''), then=Value(1)),
        default=Value(0),
        output_field=IntegerField()
    )

    featured_products = Product.objects.filter(is_featured=True).order_by('id')
    all_products = Product.objects.annotate(
        total_sold=Coalesce(
            Sum('order_items__quantity', filter=Q(order_items__order__is_deleted=False) & (
                Q(order_items__order__order_status__in=['DELIVERED', 'OUT_FOR_DELIVERY']) |
                Q(order_items__order__payment_status='PAID')
            )),
            Value(0),
            output_field=IntegerField()
        ),
        has_sale_badge=has_sale_badge
    ).order_by('-has_sale_badge', '-is_featured', '-total_sold', 'id')
    total_products_count = all_products.count()
    categories = Category.objects.annotate(
        product_count=Count('products')
    ).order_by('name')
    recent_reviews = Review.objects.filter(is_approved=True).select_related('product')[:6]
    
    # Filter by category if selected
    selected_cat = request.GET.get('category')
    if selected_cat:
        all_products = all_products.filter(category__slug=selected_cat)

    context = {
        'best_seller': best_seller,
        'top_best_sellers': top_best_sellers,
        'top_3_ids': top_3_ids,
        'featured_products': featured_products,
        'all_products': all_products,
        'total_products_count': total_products_count,
        'categories': categories,
        'selected_cat': selected_cat,
        'recent_reviews': recent_reviews,
    }
    return render(request, 'store/index.html', context)


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    has_sale_badge = Case(
        When(Q(custom_badge__isnull=False) & ~Q(custom_badge=''), then=Value(1)),
        default=Value(0),
        output_field=IntegerField()
    )
    related_products = Product.objects.exclude(id=product.id).annotate(has_sale_badge=has_sale_badge).order_by('-has_sale_badge', '-is_featured', 'id')[:3]
    reviews = product.reviews.filter(is_approved=True).order_by('-created_at')

    best_seller = Product.objects.annotate(
        total_sold=Coalesce(
            Sum('order_items__quantity', filter=Q(order_items__order__is_deleted=False) & (
                Q(order_items__order__order_status__in=['DELIVERED', 'OUT_FOR_DELIVERY']) |
                Q(order_items__order__payment_status='PAID')
            )),
            Value(0),
            output_field=IntegerField()
        )
    ).order_by('-total_sold', '-is_featured', 'id').first()

    is_best_seller = (best_seller and best_seller.id == product.id)

    context = {
        'product': product,
        'is_best_seller': is_best_seller,
        'best_seller': best_seller,
        'related_products': related_products,
        'reviews': reviews,
    }
    return render(request, 'store/product_detail.html', context)


def reviews_view(request):
    """
    Dedicated public Reviews / Wall of Love page.
    Displays all approved customer reviews with overall ratings and a quick review submission form.
    """
    reviews = Review.objects.filter(is_approved=True).select_related('product').order_by('-created_at')
    total_reviews_count = reviews.count()
    
    avg_rating = 5.0
    if total_reviews_count > 0:
        total_stars = sum(r.rating for r in reviews)
        avg_rating = round(total_stars / total_reviews_count, 1)

    five_star_count = reviews.filter(rating=5).count()
    five_star_pct = round((five_star_count / total_reviews_count) * 100) if total_reviews_count > 0 else 100

    initial_data = {}
    selected_prod_id = request.GET.get('product')
    if selected_prod_id and selected_prod_id.isdigit():
        initial_data['product'] = int(selected_prod_id)

    review_form = ReviewForm(initial=initial_data)

    if request.method == 'POST':
        # 1. Rate Limiting & Honeypot Bot Protection for Public Reviews
        from store.security import verify_cloudflare_turnstile, check_review_rate_limit, record_review_submission
        is_rev_allowed, rev_err = check_review_rate_limit(request)
        if not is_rev_allowed:
            messages.error(request, rev_err)
            return redirect('store:reviews')

        # 2. Cloudflare Turnstile Bot Protection
        is_turnstile_valid, cf_err = verify_cloudflare_turnstile(request, expected_action="review")
        if not is_turnstile_valid:
            messages.error(request, cf_err or "Please complete the Cloudflare security verification.")
            return redirect('store:reviews')

        review_form = ReviewForm(request.POST)
        if review_form.is_valid():
            new_rev = review_form.save(commit=False)
            # Moderation Protection: New public reviews require admin approval before going live
            new_rev.is_approved = False
            new_rev.save()
            record_review_submission(request)
            messages.success(request, 'Thank you! Your review has been submitted and will appear on the Wall of Love upon verification. 🥒✨')
            return redirect('store:reviews')
        else:
            messages.error(request, 'Please check your review form details and try again.')

    # Pagination (12 reviews per page)
    paginator = Paginator(reviews, 12)
    page_number = request.GET.get('page', 1)
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
        'reviews': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'elided_page_range': elided_page_range,
        'total_reviews_count': total_reviews_count,
        'avg_rating': avg_rating,
        'five_star_count': five_star_count,
        'five_star_pct': five_star_pct,
        'review_form': review_form,
    }
    return render(request, 'store/reviews.html', context)


from .models import Product, Category, Order, OrderItem, Review, calculate_pathao_delivery_fee
from .pathao import PathaoCourierService


def cart_view(request):
    cart = Cart(request)
    subtotal = cart.get_subtotal()
    total_weight_grams = cart.get_total_weight_grams()
    total_weight_kg = cart.get_total_weight_kg()
    billing_weight_kg = cart.get_billing_weight_kg()
    delivery_fee = cart.get_delivery_fee('INSIDE_DHAKA')
    grand_total = subtotal + delivery_fee
    return render(request, 'store/cart.html', {
        'cart': cart,
        'cart_subtotal': subtotal,
        'cart_total_items': len(cart),
        'total_weight_grams': total_weight_grams,
        'total_weight_kg': total_weight_kg,
        'billing_weight_kg': billing_weight_kg,
        'delivery_fee': delivery_fee,
        'grand_total': grand_total,
        'free_delivery_unlocked': cart.is_free_delivery(),
        'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
    })


@require_POST
def cart_add(request, product_id):
    from django.utils.http import url_has_allowed_host_and_scheme
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    
    try:
        raw_qty = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        raw_qty = 1
    quantity = max(1, min(raw_qty, 100))
    override = request.POST.get('override', 'false') == 'true'
    
    cart.add(product=product, quantity=quantity, override_quantity=override)
    is_preorder = False
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        items_data = [
            {
                'product_id': item['product'].id,
                'name': item['product'].name,
                'price': float(item['price']),
                'quantity': item['quantity'],
                'total_price': float(item['total_price']),
                'image_url': item['product'].primary_image_url,
                'weight': item['product'].jar_weight_grams,
                'slug': item['product'].slug,
                'is_preorder': False,
            }
            for item in cart
        ]
        msg = f'Added {product.name} to your pickle jar bag!'
        return JsonResponse({
            'success': True,
            'message': msg,
            'cart_total_items': len(cart),
            'cart_subtotal': float(cart.get_subtotal()),
            'total_weight_grams': cart.get_total_weight_grams(),
            'total_weight_kg': cart.get_total_weight_kg(),
            'billing_weight_kg': cart.get_billing_weight_kg(),
            'delivery_fee': float(cart.get_delivery_fee('INSIDE_DHAKA')),
            'grand_total': float(cart.get_total_price('INSIDE_DHAKA')),
            'free_delivery_unlocked': cart.is_free_delivery(),
            'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
            'items': items_data,
            'added_product': {
                'id': product.id,
                'name': product.name,
                'price': float(product.price_bdt),
                'quantity': quantity,
                'is_preorder': False,
            }
        })
        
    flash_msg = f'Added "{product.name}" to your jar cart!'
    messages.success(request, flash_msg)
    if request.POST.get('buy_now') == '1':
        return redirect('store:checkout')
    raw_next = request.POST.get('next') or request.META.get('HTTP_REFERER') or ''
    if raw_next and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(raw_next)
    return redirect('store:cart_view')


@require_POST
def cart_remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        items_data = [
            {
                'product_id': item['product'].id,
                'name': item['product'].name,
                'price': float(item['price']),
                'quantity': item['quantity'],
                'total_price': float(item['total_price']),
                'image_url': item['product'].primary_image_url,
                'weight': item['product'].jar_weight_grams,
                'slug': item['product'].slug,
                'is_preorder': False,
            }
            for item in cart
        ]
        return JsonResponse({
            'success': True,
            'cart_total_items': len(cart),
            'cart_subtotal': float(cart.get_subtotal()),
            'total_weight_grams': cart.get_total_weight_grams(),
            'total_weight_kg': cart.get_total_weight_kg(),
            'billing_weight_kg': cart.get_billing_weight_kg(),
            'delivery_fee': float(cart.get_delivery_fee('INSIDE_DHAKA')),
            'grand_total': float(cart.get_total_price('INSIDE_DHAKA')),
            'free_delivery_unlocked': cart.is_free_delivery(),
            'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
            'items': items_data,
        })

    messages.info(request, f'Removed "{product.name}" from your cart.')
    return redirect('store:cart_view')


@require_POST
def cart_update_ajax(request):
    cart = Cart(request)
    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        action = data.get('action') # 'increase', 'decrease', 'remove'
        zone = data.get('zone', 'INSIDE_DHAKA')
        
        product = get_object_or_404(Product, id=product_id)
        current_qty = cart.cart.get(str(product_id), {}).get('quantity', 0)
        
        if action == 'increase':
            if current_qty < 100:
                cart.add(product=product, quantity=1, override_quantity=False)
        elif action == 'decrease':
            if current_qty > 1:
                cart.add(product=product, quantity=current_qty - 1, override_quantity=True)
            else:
                cart.remove(product)
        elif action == 'remove':
            cart.remove(product)

        item_qty = cart.cart.get(str(product_id), {}).get('quantity', 0)
        item_total = float(Decimal(cart.cart.get(str(product_id), {}).get('price', 0)) * item_qty) if str(product_id) in cart.cart else 0

        items_data = [
            {
                'product_id': item['product'].id,
                'name': item['product'].name,
                'price': float(item['price']),
                'quantity': item['quantity'],
                'total_price': float(item['total_price']),
                'image_url': item['product'].primary_image_url,
                'weight': item['product'].jar_weight_grams,
                'slug': item['product'].slug,
                'is_preorder': False,
            }
            for item in cart
        ]

        delivery_fee = float(cart.get_delivery_fee(zone))
        subtotal = float(cart.get_subtotal())
        grand_total = subtotal + delivery_fee

        return JsonResponse({
            'success': True,
            'cart_total_items': len(cart),
            'cart_subtotal': subtotal,
            'total_weight_grams': cart.get_total_weight_grams(),
            'total_weight_kg': cart.get_total_weight_kg(),
            'billing_weight_kg': cart.get_billing_weight_kg(),
            'delivery_fee': delivery_fee,
            'grand_total': grand_total,
            'free_delivery_unlocked': cart.is_free_delivery(),
            'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
            'item_quantity': item_qty,
            'item_total': item_total,
            'items': items_data,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def shipping_calc_ajax(request):
    cart = Cart(request)
    zone = request.GET.get('zone', 'INSIDE_DHAKA')
    weight_grams = cart.get_total_weight_grams()
    weight_kg = cart.get_total_weight_kg()
    
    delivery_fee = cart.get_delivery_fee(zone)
    subtotal = cart.get_subtotal()
    total = subtotal + delivery_fee
    
    return JsonResponse({
        'success': True,
        'zone': zone,
        'total_weight_grams': weight_grams,
        'total_weight_kg': weight_kg,
        'billing_weight_kg': cart.get_billing_weight_kg(),
        'delivery_fee': float(delivery_fee),
        'subtotal': float(subtotal),
        'total': float(total),
        'free_delivery_unlocked': cart.is_free_delivery(),
        'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
    })


def checkout(request):
    cart = Cart(request)
    if len(cart) == 0:
        messages.warning(request, 'Your cart is empty. Pick some crunch first!')
        return redirect('store:cart_view')

    total_weight_grams = cart.get_total_weight_grams()
    total_weight_kg = cart.get_total_weight_kg()
    billing_weight_kg = cart.get_billing_weight_kg()

    if request.method == 'POST':
        # 1. Anti-Fraud & Security Verification (Honeypot, Blacklist, Rate Limiting)
        from store.security import check_rate_limit_and_blacklist, verify_cloudflare_turnstile, record_successful_order_rate
        
        submitted_phone = request.POST.get('customer_phone', '').strip()
        is_allowed, sec_err = check_rate_limit_and_blacklist(request, submitted_phone)
        if not is_allowed:
            messages.error(request, sec_err)
            return redirect('store:checkout')

        is_turnstile_valid, cf_err = verify_cloudflare_turnstile(request)
        if not is_turnstile_valid:
            messages.error(request, cf_err)
            return redirect('store:checkout')

        form = CheckoutForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            
            subtotal = cart.get_subtotal()
            delivery_zone = form.cleaned_data.get('delivery_zone') or 'INSIDE_DHAKA'
            delivery_fee = cart.get_delivery_fee(delivery_zone)
            total = subtotal + delivery_fee
            
            order.subtotal = subtotal
            order.delivery_fee = delivery_fee
            order.total_amount = total
            
            # Payment status determination
            if order.payment_method == 'COD':
                order.payment_status = 'UNPAID'
            else:
                order.payment_status = 'PENDING_VERIFICATION'
                
            order.save()

            # Create Order Items (Stock will be deducted when admin accepts/confirms order)
            for item in cart:
                product = item['product']
                qty = item['quantity']
                current_unit_price = product.price_bdt

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name=product.name,
                    jar_weight_grams=product.jar_weight_grams,
                    unit_price=current_unit_price,
                    quantity=qty,
                    total_price=current_unit_price * qty
                )

            # Record order attempt for rate limiting
            record_successful_order_rate(request, order.customer_phone)

            # Authorize current session to view full receipt for this order
            request.session['last_placed_order_number'] = order.order_number

            # Store normalized customer data in session for Meta Pixel Manual Advanced Matching
            raw_ph = ''.join(c for c in (order.customer_phone or '') if c.isdigit())
            if raw_ph.startswith('01') and len(raw_ph) == 11:
                raw_ph = '88' + raw_ph
            name_parts = (order.customer_name or '').strip().split()
            request.session['meta_advanced_matching'] = {
                'em': (order.customer_email or '').strip().lower(),
                'ph': raw_ph,
                'fn': name_parts[0].lower() if name_parts else '',
                'ln': ' '.join(name_parts[1:]).lower() if len(name_parts) > 1 else '',
                'ct': (order.delivery_city or 'dhaka').strip().lower(),
                'country': 'bd',
                'external_id': order.order_number,
            }

            # Clear cart session
            cart.clear()
            
            messages.success(request, f"Order #{order.order_number} confirmed successfully!")
            return redirect('store:order_success', order_number=order.order_number)
        else:
            messages.error(request, 'Please verify your contact and delivery address details.')
    else:
        form = CheckoutForm(initial={'delivery_zone': 'INSIDE_DHAKA', 'payment_method': 'COD'})

    selected_zone = request.GET.get('zone', 'INSIDE_DHAKA')
    delivery_fee_inside = cart.get_delivery_fee('INSIDE_DHAKA')
    delivery_fee_outside = cart.get_delivery_fee('OUTSIDE_DHAKA')
    
    delivery_fee = delivery_fee_inside if selected_zone == 'INSIDE_DHAKA' else delivery_fee_outside
    subtotal = cart.get_subtotal()
    total = subtotal + delivery_fee

    context = {
        'cart': cart,
        'form': form,
        'cart_subtotal': subtotal,
        'cart_total_items': len(cart),
        'total_weight_grams': total_weight_grams,
        'total_weight_kg': total_weight_kg,
        'billing_weight_kg': billing_weight_kg,
        'delivery_fee': delivery_fee,
        'delivery_fee_inside': delivery_fee_inside,
        'delivery_fee_outside': delivery_fee_outside,
        'grand_total': total,
        'total_amount': total,
        'free_delivery_unlocked': cart.is_free_delivery(),
        'items_needed_for_free_delivery': cart.items_needed_for_free_delivery(),
    }
    return render(request, 'store/checkout.html', context)


def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    # Prevent strangers from enumerating /order/success/PKP-00001/ to view unmasked customer PII
    is_owner_session = (request.session.get('last_placed_order_number') == order.order_number)
    is_staff = request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
    if not is_owner_session and not is_staff:
        return redirect(f"{reverse('store:order_track')}?q={order.order_number}")
    return render(request, 'store/order_success.html', {'order': order})


def _mask_customer_name(name: str) -> str:
    """Masks customer name for public order tracking privacy (e.g. 'Tanvir Ahmed' -> 'Tan*** A***')."""
    raw = (name or '').strip()
    if not raw:
        return 'Valued Customer'
    parts = raw.split()
    masked_parts = []
    for idx, part in enumerate(parts):
        if idx == 0:
            visible = part[:3] if len(part) > 3 else part[:1]
            masked_parts.append(f"{visible}***")
        else:
            masked_parts.append(f"{part[:1]}***")
    return ' '.join(masked_parts)


def _mask_delivery_address(address: str, city: str) -> str:
    """Masks street/house address on public tracking page while preserving city."""
    raw_addr = (address or '').strip()
    raw_city = (city or '').strip()
    if not raw_addr:
        return raw_city or 'Bangladesh'
    visible_prefix = raw_addr[:4] if len(raw_addr) > 4 else raw_addr[:2]
    if raw_city:
        return f"{visible_prefix}••••••, {raw_city}"
    return f"{visible_prefix}••••••"


def order_track(request):
    order = None
    query = request.GET.get('q', '').strip()
    masked_name = ''
    masked_address = ''
    
    if query:
        import re
        clean_q = query.lstrip('#').strip()
        digits_only = ''.join(c for c in clean_q if c.isdigit())

        # Match exact Order ID (e.g. PKP-00001) or exact Courier Consignment/Tracking Code
        is_exact_order_id = bool(re.match(r'^PKP-\d{4,6}$', clean_q, re.IGNORECASE))
        # Match full Bangladeshi phone number (10 or 11 digits)
        is_valid_full_phone = len(digits_only) >= 10 and clean_q.replace('+', '').replace('-', '').replace(' ', '').isdigit()
        # Match courier tracking / consignment code (minimum 5 alphanumeric chars, not just 1-3 digits)
        is_tracking_code = len(clean_q) >= 5 and not is_valid_full_phone and not is_exact_order_id

        if is_exact_order_id:
            order = Order.objects.filter(order_number__iexact=clean_q).first()
        elif is_valid_full_phone:
            last_10 = digits_only[-10:]
            order = Order.objects.filter(customer_phone__endswith=last_10).order_by('-created_at').first()
        elif is_tracking_code:
            order = Order.objects.filter(
                Q(steadfast_tracking_code__iexact=clean_q) |
                Q(steadfast_consignment_id__iexact=clean_q) |
                Q(pathao_tracking_code__iexact=clean_q) |
                Q(pathao_consignment_id__iexact=clean_q)
            ).first()
        else:
            messages.error(
                request,
                'Please enter a complete Order ID (e.g. PKP-00001), full 11-digit mobile number, or Courier Tracking Code.'
            )
            return render(request, 'store/order_track.html', {'order': None, 'query': query})
        
        if order:
            try:
                order.sync_courier_status()
                order.refresh_from_db()
            except Exception:
                pass
            masked_name = _mask_customer_name(order.customer_name)
            masked_address = _mask_delivery_address(order.delivery_address, order.delivery_city)
        else:
            messages.error(request, f'No order found matching "{query}". Please verify your full Order ID (e.g. PKP-00001), 11-digit Phone number, or Courier Tracking Code.')

    return render(request, 'store/order_track.html', {
        'order': order,
        'query': query,
        'masked_name': masked_name,
        'masked_address': masked_address,
    })


def about_story(request):
    return render(request, 'store/about_faq.html')


def policies_view(request):
    """
    Renders customer satisfaction, damage replacement, delivery and problem resolution policy.
    """
    return render(request, 'store/policies.html')


def sitemap_xml(request):
    """
    Dynamically generates a standard XML Sitemap for search engines like Google, Bing, etc.
    Includes homepage, product pages, category pages, static content with lastmod and priorities.
    """
    host = request.get_host()
    # Force HTTPS for all production/live traffic
    if settings.DEBUG and ('127.0.0.1' in host or 'localhost' in host):
        domain = f"{request.scheme}://{host}"
    else:
        domain = f"https://{host}"
    
    # 1. Main / Static pages
    urls = [
        {
            'loc': domain + reverse('store:index'),
            'changefreq': 'daily',
            'priority': '1.0',
            'lastmod': timezone.now().strftime('%Y-%m-%d'),
        },
        {
            'loc': domain + reverse('store:about_story'),
            'changefreq': 'monthly',
            'priority': '0.7',
            'lastmod': timezone.now().strftime('%Y-%m-%d'),
        },
        {
            'loc': domain + reverse('store:policies'),
            'changefreq': 'monthly',
            'priority': '0.7',
            'lastmod': timezone.now().strftime('%Y-%m-%d'),
        },
        {
            'loc': domain + reverse('store:order_track'),
            'changefreq': 'monthly',
            'priority': '0.5',
            'lastmod': timezone.now().strftime('%Y-%m-%d'),
        },
    ]

    # 2. Category list / filter URLs
    categories = Category.objects.all()
    for cat in categories:
        urls.append({
            'loc': f"{domain}/?category={cat.slug}",
            'changefreq': 'weekly',
            'priority': '0.8',
            'lastmod': timezone.now().strftime('%Y-%m-%d'),
        })

    # 3. Dynamic Product detail pages
    products = Product.objects.all().order_by('-updated_at')
    for product in products:
        lastmod = product.updated_at.strftime('%Y-%m-%d') if product.updated_at else timezone.now().strftime('%Y-%m-%d')
        urls.append({
            'loc': domain + reverse('store:product_detail', kwargs={'slug': product.slug}),
            'changefreq': 'daily',
            'priority': '0.9',
            'lastmod': lastmod,
        })

    # Generate XML output
    xml_output = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for url in urls:
        xml_output.append('  <url>')
        xml_output.append(f'    <loc>{url["loc"]}</loc>')
        if 'lastmod' in url and url['lastmod']:
            xml_output.append(f'    <lastmod>{url["lastmod"]}</lastmod>')
        if 'changefreq' in url and url['changefreq']:
            xml_output.append(f'    <changefreq>{url["changefreq"]}</changefreq>')
        if 'priority' in url and url['priority']:
            xml_output.append(f'    <priority>{url["priority"]}</priority>')
        xml_output.append('  </url>')
    xml_output.append('</urlset>')

    return HttpResponse('\n'.join(xml_output), content_type='application/xml')


def robots_txt(request):
    """
    Dynamically generates robots.txt for search engine crawlers with a pointer to sitemap.xml.
    """
    host = request.get_host()
    # Force HTTPS for all production/live traffic
    if settings.DEBUG and ('127.0.0.1' in host or 'localhost' in host):
        domain = f"{request.scheme}://{host}"
    else:
        domain = f"https://{host}"
    content = f"""User-agent: *
Disallow: /admin/
Disallow: /dashboard/
Disallow: /cart/
Disallow: /checkout/
Disallow: /order/

Sitemap: {domain}/sitemap.xml
"""
    return HttpResponse(content.strip() + '\n', content_type='text/plain')


def custom_404_view(request, exception=None):
    """
    Custom 404 Page Not Found error handler.
    """
    return render(request, '404.html', status=404)


def custom_500_view(request):
    """
    Custom 500 Internal Server Error handler with resilient emergency fallback.
    """
    try:
        return render(request, '500.html', status=500)
    except Exception:
        return HttpResponseServerError(
            """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>500 - Server Error | Pickpickles</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #092d18; color: #ffffff; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; text-align: center; }
        .card { background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 24px; padding: 40px; max-width: 480px; box-shadow: 0 20px 40px rgba(0,0,0,0.3); }
        h1 { color: #86efac; font-size: 2.2rem; margin: 15px 0 10px; }
        p { color: #d1d5db; line-height: 1.6; font-size: 1rem; margin-bottom: 25px; }
        .btn { display: inline-block; background: #16a34a; color: #fff; text-decoration: none; padding: 12px 28px; border-radius: 12px; font-weight: 700; transition: background 0.2s; }
        .btn:hover { background: #15803d; }
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 3.5rem;">🥒💥</div>
        <h1>500 - Server Error</h1>
        <p>Our pickle kitchen hit an unexpected snag! Please refresh the page or head back to the home page.</p>
        <a href="/" class="btn">Return to Home</a>
    </div>
</body>
</html>""",
            content_type="text/html"
        )


@csrf_exempt
def pathao_webhook(request):
    """
    Pathao Courier Webhook Endpoint.
    Receives instant parcel status updates from Pathao.
    Protected by webhook secret verification, consignment ID matching, and live API verification.
    """
    import hmac
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST method is accepted'}, status=405)

    # 1. Verify Webhook Secret if configured in settings/.env
    webhook_secret = getattr(settings, 'PATHAO_WEBHOOK_SECRET', '').strip()
    if webhook_secret:
        provided_secret = (
            request.headers.get('X-PATHAO-Signature') or
            request.headers.get('X-Webhook-Secret') or
            request.headers.get('Authorization', '').replace('Bearer ', '')
        ).strip()
        if not provided_secret or not hmac.compare_digest(provided_secret, webhook_secret):
            return JsonResponse({'status': 'error', 'message': 'Unauthorized webhook signature'}, status=403)
    
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST.dict()

    consignment_id = str(data.get('consignment_id') or '').strip()
    merchant_order_id = str(data.get('merchant_order_id') or '').strip()
    raw_status = str(data.get('order_status') or data.get('delivery_status') or data.get('event') or '').strip()

    # 2. Require consignment_id (prevent spoofing by guessing sequential PKP-00001 order numbers)
    if not consignment_id:
        return JsonResponse({'status': 'error', 'message': 'Valid consignment_id is required'}, status=400)

    order = Order.all_objects.filter(pathao_consignment_id=consignment_id).first()
    if not order and merchant_order_id:
        # Only match by merchant_order_id if its pathao_consignment_id matches
        order = Order.all_objects.filter(
            order_number=merchant_order_id,
            pathao_consignment_id=consignment_id
        ).first()

    if not order:
        return JsonResponse({'status': 'error', 'message': 'Matching dispatched order not found'}, status=404)

    # 3. Cross-verify status directly with Pathao API when configured, fallback to verified consignment payload
    verified_status = order.sync_pathao_status()
    effective_raw_status = verified_status or raw_status

    if effective_raw_status:
        order.pathao_order_status = effective_raw_status
        clean = effective_raw_status.lower().replace('-', '_').replace(' ', '_')
        
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
            order.order_status = mapped
            if mapped == 'DELIVERED' and order.payment_status == 'UNPAID':
                order.payment_status = 'PAID'
        
        order.save(update_fields=['pathao_order_status', 'order_status', 'payment_status'])
        
    return JsonResponse({
        'status': 'success',
        'order_number': order.order_number,
        'order_status': order.order_status,
        'payment_status': order.payment_status,
        'pathao_order_status': order.pathao_order_status,
    })


@csrf_exempt
def steadfast_webhook(request):
    """
    Steadfast Courier Webhook / Callback Endpoint.
    Receives instant parcel status updates from Steadfast Courier.
    Protected by webhook secret verification, consignment/tracking matching, and live API verification.
    Endpoint: POST /api/steadfast/webhook/
    """
    import hmac
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST method is accepted'}, status=405)

    # 1. Verify Webhook Secret if configured in settings/.env
    webhook_secret = getattr(settings, 'STEADFAST_WEBHOOK_SECRET', '').strip()
    if webhook_secret:
        provided_secret = (
            request.headers.get('X-Steadfast-Signature') or
            request.headers.get('X-Webhook-Secret') or
            request.headers.get('Authorization', '').replace('Bearer ', '')
        ).strip()
        if not provided_secret or not hmac.compare_digest(provided_secret, webhook_secret):
            return JsonResponse({'status': 'error', 'message': 'Unauthorized webhook signature'}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST.dict()

    consignment_id = str(data.get('consignment_id') or '').strip()
    invoice = str(data.get('invoice') or data.get('order_number') or data.get('merchant_order_id') or '').strip()
    tracking_code = str(data.get('tracking_code') or '').strip()
    raw_status = str(data.get('status') or data.get('delivery_status') or data.get('event') or '').strip()

    # 2. Require unguessable consignment_id or tracking_code (do not allow invoice-only spoofing)
    if not consignment_id and not tracking_code:
        return JsonResponse({'status': 'error', 'message': 'consignment_id or tracking_code required'}, status=400)

    order = None
    if consignment_id:
        order = Order.all_objects.filter(steadfast_consignment_id=consignment_id).first()
    if not order and tracking_code:
        order = Order.all_objects.filter(steadfast_tracking_code=tracking_code).first()

    if not order:
        return JsonResponse({'status': 'error', 'message': 'Matching dispatched order not found'}, status=404)

    # Verify invoice matches if provided
    if invoice and order.order_number.lower() != invoice.lower():
        return JsonResponse({'status': 'error', 'message': 'Order invoice mismatch'}, status=400)

    # 3. Cross-verify status with Steadfast API if configured, otherwise save status from verified consignment
    verified_status = order.sync_steadfast_status()
    if not verified_status and raw_status:
        order.steadfast_order_status = raw_status
        order.save(update_fields=['steadfast_order_status'])

    return JsonResponse({
        'status': 'success',
        'order_number': order.order_number,
        'order_status': order.order_status,
        'payment_status': order.payment_status,
        'steadfast_order_status': order.steadfast_order_status,
    })


def courier_live_status_ajax(request, order_number):
    """
    AJAX endpoint to query live courier tracking status directly from Steadfast / Pathao API.
    Used by the Track Order page modal and interactive widgets.
    """
    clean_val = str(order_number or '').strip()
    order = Order.all_objects.filter(
        Q(order_number__iexact=clean_val) |
        Q(steadfast_tracking_code__iexact=clean_val) |
        Q(steadfast_consignment_id__iexact=clean_val) |
        Q(pathao_tracking_code__iexact=clean_val) |
        Q(pathao_consignment_id__iexact=clean_val)
    ).first()

    if not order:
        return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)

    # Sync live from courier
    try:
        order.sync_courier_status()
        order.refresh_from_db()
    except Exception:
        pass

    return JsonResponse({
        'success': True,
        'order_number': order.order_number,
        'courier_name': order.active_courier_name,
        'courier_provider': order.active_courier,
        'consignment_id': order.active_consignment_id or '',
        'tracking_code': order.active_tracking_code or '',
        'raw_status': order.active_courier_status or 'in_review',
        'status_display': order.active_courier_status_display,
        'status_badge_class': order.active_courier_status_badge_class,
        'customer_name': _mask_customer_name(order.customer_name),
        'destination': _mask_delivery_address(order.delivery_address, order.delivery_city),
        'total_amount': str(order.total_amount),
        'payment_status': order.get_payment_status_display(),
        'active_tracking_url': order.active_tracking_url or 'https://steadfast.com.bd/tracking',
    })
