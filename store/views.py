import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, HttpResponseServerError
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import Product, Category, Order, OrderItem, Review
from .cart import Cart
from .forms import CheckoutForm, ReviewForm


from django.db.models import Count, Q


def index(request):
    featured_products = Product.objects.filter(is_in_stock=True, is_featured=True).order_by('id')
    all_products = Product.objects.filter(is_in_stock=True).order_by('id')
    total_products_count = all_products.count()
    categories = Category.objects.annotate(
        product_count=Count('products', filter=Q(products__is_in_stock=True))
    ).order_by('name')
    recent_reviews = Review.objects.filter(is_approved=True).select_related('product')[:6]
    
    # Filter by category if selected
    selected_cat = request.GET.get('category')
    if selected_cat:
        all_products = all_products.filter(category__slug=selected_cat)

    context = {
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
    related_products = Product.objects.filter(is_in_stock=True).exclude(id=product.id)[:3]
    reviews = product.reviews.filter(is_approved=True)
    review_form = ReviewForm()

    if request.method == 'POST':
        review_form = ReviewForm(request.POST)
        if review_form.is_valid():
            new_review = review_form.save(commit=False)
            new_review.product = product
            new_review.save()
            messages.success(request, 'Thank you! Your pickle review has been posted.')
            return redirect('store:product_detail', slug=slug)

    context = {
        'product': product,
        'related_products': related_products,
        'reviews': reviews,
        'review_form': review_form,
    }
    return render(request, 'store/product_detail.html', context)


def cart_view(request):
    cart = Cart(request)
    subtotal = cart.get_subtotal()
    delivery_fee = Decimal('130.00')
    grand_total = subtotal + delivery_fee
    return render(request, 'store/cart.html', {
        'cart': cart,
        'cart_subtotal': subtotal,
        'delivery_fee': delivery_fee,
        'grand_total': grand_total,
    })


@require_POST
def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    
    quantity = int(request.POST.get('quantity', 1))
    override = request.POST.get('override', 'false') == 'true'
    
    cart.add(product=product, quantity=quantity, override_quantity=override)
    
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
            }
            for item in cart
        ]
        return JsonResponse({
            'success': True,
            'message': f'Added {product.name} to your pickle jar bag!',
            'cart_total_items': len(cart),
            'cart_subtotal': float(cart.get_subtotal()),
            'items': items_data,
            'added_product': {
                'id': product.id,
                'name': product.name,
                'price': float(product.price_bdt),
                'quantity': quantity,
            }
        })
        
    messages.success(request, f'Added "{product.name}" to your jar cart!')
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'store:cart_view'
    return redirect(next_url)


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
            }
            for item in cart
        ]
        return JsonResponse({
            'success': True,
            'cart_total_items': len(cart),
            'cart_subtotal': float(cart.get_subtotal()),
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
        
        product = get_object_or_404(Product, id=product_id)
        current_qty = cart.cart.get(str(product_id), {}).get('quantity', 0)
        
        if action == 'increase':
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
            }
            for item in cart
        ]

        return JsonResponse({
            'success': True,
            'cart_total_items': len(cart),
            'cart_subtotal': float(cart.get_subtotal()),
            'item_quantity': item_qty,
            'item_total': item_total,
            'items': items_data,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


def checkout(request):
    cart = Cart(request)
    if len(cart) == 0:
        messages.warning(request, 'Your cart is empty. Pick some crunch first!')
        return redirect('store:index')

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            
            subtotal = cart.get_subtotal()
            delivery_zone = form.cleaned_data['delivery_zone']
            delivery_fee = Decimal('130.00')
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

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    product_name=product.name,
                    jar_weight_grams=product.jar_weight_grams,
                    unit_price=item['price'],
                    quantity=qty,
                    total_price=item['total_price']
                )

            # Clear cart session
            cart.clear()
            
            messages.success(request, f"Order #{order.order_number} confirmed successfully!")
            return redirect('store:order_success', order_number=order.order_number)
        else:
            messages.error(request, 'Please verify your contact and delivery address details.')
    else:
        form = CheckoutForm(initial={'delivery_zone': 'INSIDE_DHAKA', 'payment_method': 'COD'})

    subtotal = cart.get_subtotal()
    delivery_fee = Decimal('130.00')
    total = subtotal + delivery_fee

    context = {
        'cart': cart,
        'form': form,
        'cart_subtotal': subtotal,
        'delivery_fee': delivery_fee,
        'grand_total': total,
        'total_amount': total,
    }
    return render(request, 'store/checkout.html', context)


def order_success(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    return render(request, 'store/order_success.html', {'order': order})


def order_track(request):
    order = None
    query = request.GET.get('q', '').strip()
    
    if query:
        import re
        clean_q = query.lstrip('#').strip()
        num_match = re.search(r'(\d+)', clean_q)
        q_filter = (
            Q(order_number__iexact=query) |
            Q(order_number__iexact=clean_q) |
            Q(order_number__icontains=clean_q) |
            Q(customer_phone__icontains=query)
        )
        if num_match:
            try:
                padded_val = f"PKP-{int(num_match.group(1)):04d}"
                q_filter |= Q(order_number__iexact=padded_val)
            except Exception:
                pass

        order = Order.objects.filter(q_filter).first()
        
        if not order:
            messages.error(request, f'No order found matching "{query}". Please verify your Order ID (e.g. PKP-0001) or Phone number.')

    return render(request, 'store/order_track.html', {'order': order, 'query': query})


def about_story(request):
    return render(request, 'store/about_faq.html')


def sitemap_xml(request):
    """
    Dynamically generates a standard XML Sitemap for search engines like Google, Bing, etc.
    Includes homepage, product pages, category pages, static content with lastmod and priorities.
    """
    domain = f"{request.scheme}://{request.get_host()}"
    
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
    products = Product.objects.filter(is_in_stock=True).order_by('-updated_at')
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
    domain = f"{request.scheme}://{request.get_host()}"
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

