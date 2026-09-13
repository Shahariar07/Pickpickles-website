import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()

from django.contrib.auth.models import User
from store.models import Category, Product, Order, OrderItem
from decimal import Decimal

def seed():
    print("Seeding Pickpickles Database...")

    # 1. Create Superuser / Admin
    if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser('admin', 'admin@pickpickles.com', 'pickles123')
        print("Created superuser: admin / pickles123")
    else:
        print("Superuser admin already exists.")

    # 2. Categories
    cat_dill, _ = Category.objects.get_or_create(
        name="Classic Dill Pickles",
        defaults={'description': 'Authentic American-style kosher garlic dill spears, whole dills, and chips.', 'icon': 'fa-seedling'}
    )
    cat_sweet, _ = Category.objects.get_or_create(
        name="Sweet & Tangy Pickles",
        defaults={'description': 'Bread & butter crinkle chips with sweet onions.', 'icon': 'fa-jar'}
    )
    cat_spicy, _ = Category.objects.get_or_create(
        name="Spicy & Fire Hot Pickles",
        defaults={'description': 'Infused with fresh habanero, naga chili, and red peppers.', 'icon': 'fa-fire'}
    )
    cat_relish, _ = Category.objects.get_or_create(
        name="Relish & Specialty Cuts",
        defaults={'description': 'Finely chopped pickle relish for hot dogs and burgers.', 'icon': 'fa-burger'}
    )

    # 3. Products
    products_data = [
        {
            'name': 'Classic Dill Pickles',
            'category': cat_dill,
            'tagline': 'Authentic American-Style Kosher Garlic Dill Pickles with Aromatic Herbs & Whole Spices',
            'description': 'Handcrafted with fresh crisp local cucumbers, whole garlic cloves, fragrant dill herbs, bay leaves, yellow mustard seeds, and black peppercorns in an artisanal cold vinegar brine. Loud audible crunch and authentic deli flavor with zero heavy oils.',
            'flavor_profile': 'Garlic Infused, Tangy Deli Brine, Aromatic Dill & Mustard Seed',
            'pairing_suggestions': 'Smash Burgers, Fried Chicken, Sandwiches, Shawarma, Beef Tehari & Daal-Rice',
            'cut_style': 'CHIPS',
            'spice_level': 'MILD',
            'crunch_rating': 5,
            'jar_weight_grams': 600,
            'price_bdt': Decimal('350.00'),
            'original_price_bdt': Decimal('400.00'),
            'image_url': '/media/products/classic_dill_pickles.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Cucumbers, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic Cloves, Dill Herbs, Bay Leaf, Yellow Mustard Seeds, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 1 month.'
        },
        {
            'name': 'Pickled Mixed Veggies',
            'category': cat_sweet,
            'tagline': 'Crisp Cucumbers, Sweet Carrots & Bell Peppers with a Tangy-Sweet Snap!',
            'description': 'Our signature jar crafted with hand-selected crunchy local cucumbers, sweet carrots, vibrant bell peppers, whole garlic cloves, and yellow mustard seeds. Infused in a perfectly balanced sweet, tangy, and savory vinegar brine with zero heavy oils.',
            'flavor_profile': 'Tangy, Crisp, Mild Sweet & Mustard-Spiced',
            'pairing_suggestions': 'Smash Burgers, Fried Chicken, Shawarma, Beef Tehari, Biryani, Bhuna Khichuri, Kebabs & Daal-Bhat',
            'cut_style': 'CHIPS',
            'spice_level': 'MILD',
            'crunch_rating': 5,
            'jar_weight_grams': 600,
            'price_bdt': Decimal('350.00'),
            'original_price_bdt': Decimal('400.00'),
            'image_url': '/media/products/pickled_mixed_veggies.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Cucumbers, Sweet Carrots, Crisp Bell Peppers (Capsicum), Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Brown Cane Sugar, Fresh Garlic Cloves, Yellow Mustard Seeds, Coriander, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 1 month.'
        },
        {
            'name': 'Pickled Deshi Onions',
            'category': cat_sweet,
            'tagline': 'Crunchy Local Deshi Onion Rings in Spiced Herb & Bay Leaf Vinegar Brine',
            'description': 'Handcrafted with sliced local deshi onion rings steeped in artisanal cane vinegar brine infused with whole garlic cloves, bay leaf, yellow mustard seeds, black peppercorns, and fresh green chili. Tangy, zesty, and naturally crunchy — the authentic deshi touch for beef tehari, kacchi biryani, bhuna khichuri, kebabs, and smash burgers with zero heavy oils.',
            'flavor_profile': 'Tangy, Crisp, Mild Zesty & Herb Infused',
            'pairing_suggestions': 'Beef Tehari, Kacchi Biryani, Bhuna Khichuri, Kebabs, Smash Burgers, Fried Chicken & Dal-Rice',
            'cut_style': 'CHIPS',
            'spice_level': 'MEDIUM',
            'crunch_rating': 4,
            'jar_weight_grams': 600,
            'price_bdt': Decimal('220.00'),
            'original_price_bdt': Decimal('260.00'),
            'image_url': '/media/products/pickled_deshi_onions.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Deshi Onions, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic Cloves, Bay Leaf (Tejpata), Yellow Mustard Seeds, Black Peppercorn, Green Chili.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 1 month.'
        },
        {
            'name': 'Pickled Green Peppers',
            'category': cat_spicy,
            'tagline': 'Fiery Local Green Chillies & Garlic Slices in Tangy Spiced Vinegar Brine!',
            'description': 'Crisp sliced local green chillies, whole garlic cloves, fragrant bay leaf (tejpata), yellow mustard seeds, and black peppercorn infused in an artisanal cane vinegar brine. Delivers a vibrant, zesty crunch with a clean fiery kick that elevates rich and fried foods with zero heavy oils.',
            'flavor_profile': 'Fiery Heat, Tangy Vinegary Snap, Aromatic Bay Leaf & Garlic',
            'pairing_suggestions': 'Smash Burgers, Fried Chicken, Shawarma, Beef Tehari, Khichuri, Kebab Rolls & Daal-Bhat',
            'cut_style': 'CHIPS',
            'spice_level': 'HOT',
            'crunch_rating': 4,
            'jar_weight_grams': 600,
            'price_bdt': Decimal('250.00'),
            'original_price_bdt': Decimal('300.00'),
            'image_url': '/media/products/pickled_green_peppers.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Green Chillies / Peppers, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic Cloves, Bay Leaf (Tejpata), Yellow Mustard Seeds, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 1 month.'
        },
        {
            'name': 'Pickled Beetroot',
            'category': cat_sweet,
            'tagline': 'Earthy, Crisp Ruby Beetroot Slices Infused with Spices & Tangy Cane Vinegar Brine!',
            'description': 'Handcrafted with fresh local ruby-red beetroot slices steeped in an artisanal spiced cane vinegar brine with whole garlic cloves, yellow mustard seeds, black peppercorns, and fragrant whole spices. Boasting an intense ruby-crimson hue, clean sweet-earthy tang, and a crisp bite — perfect for smash burgers, fresh salads, shawarma, beef tehari, and rice bowls with zero heavy oils.',
            'flavor_profile': 'Sweet Tang, Earthy Richness, Mustard Seed Snap & Garlic Infusion',
            'pairing_suggestions': 'Smash Burgers, Fresh Green Salads, Grilled Meats, Shawarma, Beef Tehari, Khichuri & Cheese Sandwiches',
            'cut_style': 'CHIPS',
            'spice_level': 'MILD',
            'crunch_rating': 4,
            'jar_weight_grams': 600,
            'price_bdt': Decimal('260.00'),
            'original_price_bdt': Decimal('300.00'),
            'image_url': '/media/products/pickled_beetroot.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Beetroots, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Brown Cane Sugar, Fresh Garlic Cloves, Bay Leaf (Tejpata), Yellow Mustard Seeds, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 1 month.'
        }
    ]

    product_map = {}
    for p_data in products_data:
        p, _ = Product.objects.update_or_create(
            name=p_data['name'],
            defaults=p_data
        )
        product_map[p.name] = p

    print(f"Populated {len(product_map)} products.")

    # 4. Actual 4 Orders from Dashboard
    orders_data = [
        {
            'order_number': 'PKP-0001',
            'customer_name': 'Shahariar Imtiaz',
            'customer_phone': '01739804566',
            'customer_email': 'shahariar07@hotmail.com',
            'delivery_address': '7/C,City Tower ,south jiltuly , Faridpur',
            'delivery_city': 'Faridpur',
            'delivery_zone': 'OUTSIDE_DHAKA',
            'delivery_fee': Decimal('150.00'),
            'subtotal': Decimal('350.00'),
            'total_amount': Decimal('500.00'),
            'payment_method': 'COD',
            'payment_status': 'PAID',
            'order_status': 'DELIVERED',
            'customer_notes': '',
            'admin_notes': '',
            'items': [
                {'product': product_map['Pickled Mixed Veggies'], 'qty': 1, 'price': Decimal('350.00')},
            ]
        },
        {
            'order_number': 'PKP-0002',
            'customer_name': 'Ameena Mortoza',
            'customer_phone': '01339511158',
            'customer_email': None,
            'delivery_address': 'House 51, Road 2, Park house (2ns floor), Old Dohs Banani, Kakoli, Dhaka',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'delivery_fee': Decimal('150.00'),
            'subtotal': Decimal('470.00'),
            'total_amount': Decimal('620.00'),
            'payment_method': 'COD',
            'payment_status': 'UNPAID',
            'order_status': 'CONFIRMED',
            'customer_notes': '',
            'admin_notes': 'Manual order created by staff',
            'items': [
                {'product': product_map['Pickled Deshi Onions'], 'qty': 1, 'price': Decimal('220.00')},
                {'product': product_map['Pickled Green Peppers'], 'qty': 1, 'price': Decimal('250.00')},
            ]
        },
        {
            'order_number': 'PKP-0003',
            'customer_name': 'Yasir Ahmed',
            'customer_phone': '01817169889',
            'customer_email': None,
            'delivery_address': '93 Chatteswari road. Chowdhury Nibash. Flat 5A. Chawkbazar',
            'delivery_city': 'Chattogram',
            'delivery_zone': 'INSIDE_DHAKA',
            'delivery_fee': Decimal('150.00'),
            'subtotal': Decimal('350.00'),
            'total_amount': Decimal('500.00'),
            'payment_method': 'COD',
            'payment_status': 'UNPAID',
            'order_status': 'OUT_FOR_DELIVERY',
            'customer_notes': '',
            'admin_notes': '',
            'items': [
                {'product': product_map['Pickled Mixed Veggies'], 'qty': 1, 'price': Decimal('350.00')},
            ]
        },
        {
            'order_number': 'PKP-0004',
            'customer_name': 'Shahariar Imtiaz',
            'customer_phone': '01739804566',
            'customer_email': 'shahariar07@hotmail.com',
            'delivery_address': '7/C,City Tower ,south jiltuly , Faridpur',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'delivery_fee': Decimal('150.00'),
            'subtotal': Decimal('250.00'),
            'total_amount': Decimal('400.00'),
            'payment_method': 'COD',
            'payment_status': 'UNPAID',
            'order_status': 'PENDING',
            'customer_notes': '',
            'admin_notes': '',
            'items': [
                {'product': product_map['Pickled Green Peppers'], 'qty': 1, 'price': Decimal('250.00')},
            ]
        }
    ]

    for o_info in orders_data:
        items_data = o_info.pop('items')
        order, created = Order.objects.update_or_create(
            order_number=o_info['order_number'],
            defaults=o_info
        )
        # Re-sync items
        order.items.all().delete()
        for item in items_data:
            OrderItem.objects.create(
                order=order,
                product=item['product'],
                product_name=item['product'].name,
                jar_weight_grams=item['product'].jar_weight_grams,
                unit_price=item['price'],
                quantity=item['qty'],
                total_price=item['price'] * item['qty']
            )

    print(f"Populated {len(orders_data)} dashboard orders.")
    print("Database seeding completed successfully!")

if __name__ == '__main__':
    seed()
