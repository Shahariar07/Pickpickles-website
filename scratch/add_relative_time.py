import os

path = 'H:/My Drive/Pickpickles website/templates/dashboard/orders_list.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

target = '{{ order.delivery_city }} ({{ order.get_delivery_zone_display }})</span>'
replacement = '{{ order.delivery_city }} ({{ order.get_delivery_zone_display }})</span>\n                            <span class="text-gray-300">•</span>\n                            <span class="text-slate-500 font-bold text-[10px] whitespace-nowrap shrink-0"><i class="fa-regular fa-clock text-[8.5px]"></i> {{ order.created_at|timesince }} ago</span>'

if target in content:
    content = content.replace(target, replacement, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("SUCCESS")
else:
    print("NOT FOUND")
