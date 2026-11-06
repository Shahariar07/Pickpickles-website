import os

# 1. Update templates/store/order_success.html
order_success_path = 'templates/store/order_success.html'
with open(order_success_path, 'r', encoding='utf-8') as f:
    os_content = f.read()

os_target = '''            fbq('init', '{{ META_PIXEL_ID }}', advancedMatchingData);

            // Note: Official Meta 'Purchase' event is dispatched via Meta Conversions API (CAPI)
            // only when the admin accepts/confirms the order in dashboard to filter out fake/unconfirmed COD orders.
            var orderTotal = parseFloat("{{ order.total_amount|stringformat:'.2f' }}") || 0;
            var orderItemsCount = parseInt("{{ order.items.count|default:1 }}", 10) || 1;
            fbq('trackCustom', 'OrderPlaced', {
                value: orderTotal,
                currency: 'BDT',
                order_id: orderNum,
                num_items: orderItemsCount
            });
            console.log("✅ [Meta Pixel] Customer Advanced Matching initialized for Order: " + orderNum);'''

os_replacement = '''            fbq('init', '{{ META_PIXEL_ID }}', advancedMatchingData);

            // Official Meta Pixel Standard 'Purchase' Event
            // Uses exact eventID: orderNum so Meta automatically deduplicates with Server Conversions API (CAPI)
            var orderTotal = parseFloat("{{ order.total_amount|stringformat:'.2f' }}") || 0;
            var orderItemsCount = parseInt("{{ order.items.count|default:1 }}", 10) || 1;
            var catalogItemIds = [{% for item in order.items.all %}'{{ item.product.catalog_id|default:"JAR-1" }}'{% if not forloop.last %}, {% endif %}{% endfor %}];

            if (catalogItemIds.length > 0) {
                fbq('track', 'Purchase', {
                    content_name: 'Pickle Order',
                    content_ids: catalogItemIds,
                    content_type: 'product',
                    value: orderTotal,
                    currency: 'BDT',
                    num_items: orderItemsCount,
                    order_id: orderNum
                }, { eventID: orderNum });
                console.log("🎯 [Meta Pixel] Purchase event fired with eventID: " + orderNum, catalogItemIds);
            }

            // Custom event for internal analytics backup
            fbq('trackCustom', 'OrderPlaced', {
                value: orderTotal,
                currency: 'BDT',
                order_id: orderNum,
                num_items: orderItemsCount
            });
            console.log("✅ [Meta Pixel] Customer Advanced Matching initialized for Order: " + orderNum);'''

os_target_norm = os_target.replace('\r\n', '\n')
os_content_norm = os_content.replace('\r\n', '\n')
if os_target_norm in os_content_norm:
    os_content_norm = os_content_norm.replace(os_target_norm, os_replacement.replace('\r\n', '\n'))
    with open(order_success_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(os_content_norm)
    print("Updated templates/store/order_success.html successfully")
else:
    print("Could not match target in order_success.html")

# 2. Update templates/store/checkout.html to ensure InitiateCheckout never fires with empty content_ids
checkout_path = 'templates/store/checkout.html'
with open(checkout_path, 'r', encoding='utf-8') as f:
    ch_content = f.read()

ch_target = '''            var cartSub = parseFloat("{{ cart_subtotal|default:0|stringformat:'.2f' }}") || 0;
            var cartCount = parseInt("{{ cart_total_items|default:0 }}", 10) || 1;
            if (cartSub > 0) {
                fbq('track', 'InitiateCheckout', {
                    content_name: 'Pickle Order Checkout',
                    content_ids: [{% for item in cart %}'{{ item.product.catalog_id }}'{% if not forloop.last %}, {% endif %}{% endfor %}],
                    value: cartSub,
                    currency: 'BDT',
                    num_items: cartCount,
                    content_type: 'product'
                });
            }'''

ch_replacement = '''            var cartSub = parseFloat("{{ cart_subtotal|default:0|stringformat:'.2f' }}") || 0;
            var cartCount = parseInt("{{ cart_total_items|default:0 }}", 10) || 1;
            var rawIds = [{% for item in cart %}'{{ item.product.catalog_id|default:"" }}'{% if not forloop.last %}, {% endif %}{% endfor %}].filter(function(id) { return id && id.length > 0; });
            if (cartSub > 0 && rawIds.length > 0) {
                fbq('track', 'InitiateCheckout', {
                    content_name: 'Pickle Order Checkout',
                    content_ids: rawIds,
                    value: cartSub,
                    currency: 'BDT',
                    num_items: cartCount,
                    content_type: 'product'
                });
            }'''

ch_target_norm = ch_target.replace('\r\n', '\n')
ch_content_norm = ch_content.replace('\r\n', '\n')
if ch_target_norm in ch_content_norm:
    ch_content_norm = ch_content_norm.replace(ch_target_norm, ch_replacement.replace('\r\n', '\n'))
    with open(checkout_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(ch_content_norm)
    print("Updated templates/store/checkout.html successfully")
else:
    print("Could not match target in checkout.html")

# 3. Update static/js/main.js to make AddToCart resilient with client-side fallback
main_js_path = 'static/js/main.js'
with open(main_js_path, 'r', encoding='utf-8') as f:
    js_content = f.read()

js_target = '''            if (typeof fbq === 'function' && data.added_product) {
                const addPrice = parseFloat(data.added_product.price) || 0;
                const addQty = parseInt(data.added_product.quantity, 10) || 1;
                const totalVal = Math.round(addPrice * addQty * 100) / 100;
                const catalogContentId = String(data.added_product.content_id || ('JAR-' + data.added_product.id));
                fbq('track', 'AddToCart', {
                    content_name: String(data.added_product.name || ''),
                    content_ids: [catalogContentId],
                    content_type: 'product',
                    value: totalVal,
                    currency: 'BDT'
                });
            }'''

js_replacement = '''            if (typeof fbq === 'function' && data.added_product) {
                const addPrice = parseFloat(data.added_product.price) || 0;
                const addQty = parseInt(data.added_product.quantity, 10) || 1;
                const totalVal = Math.round(addPrice * addQty * 100) / 100;
                const CATALOG_MAP = {
                    9: 'JAR-1', 10: 'JAR-2', 11: 'JAR-3', 12: 'JAR-4',
                    14: 'JAR-5', 15: 'JAR-6', 16: 'JAR-7', 17: 'JAR-8',
                    18: 'JAR-9', 19: 'JAR-10', 20: 'JAR-11', 21: 'JAR-12',
                    22: 'JAR-13', 23: 'JAR-14', 24: 'JAR-15', 25: 'JAR-16'
                };
                const pId = parseInt(data.added_product.id, 10);
                const catalogContentId = String(data.added_product.content_id || CATALOG_MAP[pId] || ('JAR-' + pId));
                fbq('track', 'AddToCart', {
                    content_name: String(data.added_product.name || ''),
                    content_ids: [catalogContentId],
                    content_type: 'product',
                    value: totalVal,
                    currency: 'BDT'
                });
            }'''

js_target_norm = js_target.replace('\r\n', '\n')
js_content_norm = js_content.replace('\r\n', '\n')
if js_target_norm in js_content_norm:
    js_content_norm = js_content_norm.replace(js_target_norm, js_replacement.replace('\r\n', '\n'))
    with open(main_js_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(js_content_norm)
    print("Updated static/js/main.js successfully")
else:
    print("Could not match target in static/js/main.js")
