import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()

from django.contrib.auth.models import User
from store.models import Category, Product, Order, OrderItem, Review
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
            'jar_weight_grams': 500,
            'price_bdt': Decimal('350.00'),
            'original_price_bdt': Decimal('400.00'),
            'image_url': '/media/products/classic_dill_pickles.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Cucumbers, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic Cloves, Dill Herbs, Bay Leaf, Yellow Mustard Seeds, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 2–3 months.'
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
            'jar_weight_grams': 500,
            'price_bdt': Decimal('350.00'),
            'original_price_bdt': Decimal('400.00'),
            'image_url': '/media/products/pickled_mixed_veggies.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Cucumbers, Sweet Carrots, Crisp Bell Peppers (Capsicum), Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Brown Cane Sugar, Fresh Garlic Cloves, Yellow Mustard Seeds, Coriander, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 2–3 months.'
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
            'jar_weight_grams': 500,
            'price_bdt': Decimal('220.00'),
            'original_price_bdt': Decimal('260.00'),
            'image_url': '/media/products/pickled_deshi_onions.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Deshi Onions, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic Cloves, Bay Leaf (Tejpata), Yellow Mustard Seeds, Black Peppercorn, Green Chili.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 2–3 months.'
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
            'jar_weight_grams': 500,
            'price_bdt': Decimal('250.00'),
            'original_price_bdt': Decimal('300.00'),
            'image_url': '/media/products/pickled_green_peppers.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Green Chillies / Peppers, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Fresh Garlic Cloves, Bay Leaf (Tejpata), Yellow Mustard Seeds, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 2–3 months.'
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
            'crunch_rating': 5,
            'jar_weight_grams': 500,
            'price_bdt': Decimal('260.00'),
            'original_price_bdt': Decimal('300.00'),
            'image_url': '/media/products/pickled_beetroot.webp',
            'is_featured': True,
            'is_in_stock': True,
            'stock_count': 50,
            'ingredients': 'Fresh Local Beetroots, Filtered Water, Pure Cane Vinegar, Himalayan Pink Salt, Brown Cane Sugar, Fresh Garlic Cloves, Bay Leaf (Tejpata), Yellow Mustard Seeds, Black Peppercorn.',
            'shelf_life': 'Always keep refrigerated for maximum crunch. Best enjoyed within 2–3 months.'
        }
    ]

    created_products = []
    for p_data in products_data:
        p, _ = Product.objects.update_or_create(
            name=p_data['name'],
            defaults=p_data
        )
        created_products.append(p)

    print(f"Populated {len(created_products)} products.")

    # 4. Customer Reviews
    reviews_data = [
        {
            'product': created_products[0],
            'reviewer_name': 'Zuhair Rahman',
            'reviewer_location': 'Gulshan 2, Dhaka',
            'rating': 5,
            'comment': 'Finally, proper crunchy deli-style pickles in Dhaka! The crunch is unbelievable. Put two slices in my homemade smash burger and it gave that pure diner feel.'
        },
        {
            'product': created_products[1],
            'reviewer_name': 'Ayesha Farzana',
            'reviewer_location': 'Dhanmondi, Dhaka',
            'rating': 5,
            'comment': 'The Bread & Butter chips have that perfect sweet and tangy balance without being oily. My whole family finished half the jar in one evening with grilled cheese!'
        },
        {
            'product': created_products[2],
            'reviewer_name': 'Mahir Chowdhury',
            'reviewer_location': 'Banani, Dhaka',
            'rating': 5,
            'comment': 'The Spicy Fire Habanero is fire! It has that ultra crisp snap with a serious spicy kick that pairs amazingly with crispy fried chicken.'
        },
        {
            'product': created_products[3],
            'reviewer_name': 'Tasnim Anjum',
            'reviewer_location': 'Uttara, Dhaka',
            'rating': 5,
            'comment': 'The pickled beetroot is magnificent! The vibrant ruby color and crisp texture elevated my salads and burger nights completely. Truly artisanal.'
        },
    ]

    for r_data in reviews_data:
        Review.objects.get_or_create(
            product=r_data['product'],
            reviewer_name=r_data['reviewer_name'],
            defaults=r_data
        )
    print("Populated customer reviews.")

    # 5. Demo Orders in Admin Dashboard
    orders_data = [
        {
            'order_number': 'PKP-0001',
            'customer_name': 'Tanvir Ahmed',
            'customer_phone': '01711223344',
            'customer_email': 'tanvir@gmail.com',
            'delivery_address': 'House 14, Road 7, Sector 3, Uttara',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'delivery_fee': Decimal('60.00'),
            'subtotal': Decimal('740.00'),
            'total_amount': Decimal('800.00'),
            'payment_method': 'BKASH',
            'payment_status': 'PAID',
            'payment_sender_number': '01711223344',
            'payment_trx_id': 'BKT9812401',
            'order_status': 'CONFIRMED',
            'customer_notes': 'Please deliver after 4 PM if possible.',
            'items': [
                {'product': created_products[0], 'qty': 1, 'price': Decimal('380.00')},
                {'product': created_products[1], 'qty': 1, 'price': Decimal('360.00')},
            ]
        },
        {
            'order_number': 'PKP-0002',
            'customer_name': 'Nabila Karim',
            'customer_phone': '01899887766',
            'customer_email': 'nabila.k@outlook.com',
            'delivery_address': 'Flat 4B, Concord Tower, Road 11, Banani',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'delivery_fee': Decimal('60.00'),
            'subtotal': Decimal('390.00'),
            'total_amount': Decimal('450.00'),
            'payment_method': 'COD',
            'payment_status': 'UNPAID',
            'order_status': 'PENDING',
            'customer_notes': 'Call when rider reaches the building gate.',
            'items': [
                {'product': created_products[2], 'qty': 1, 'price': Decimal('390.00')},
            ]
        },
        {
            'order_number': 'PKP-0003',
            'customer_name': 'Sadman Sakib',
            'customer_phone': '01655443322',
            'customer_email': 'sadman@yahoo.com',
            'delivery_address': 'GEC Circle, Nasirabad',
            'delivery_city': 'Chattogram',
            'delivery_zone': 'OUTSIDE_DHAKA',
            'delivery_fee': Decimal('120.00'),
            'subtotal': Decimal('760.00'),
            'total_amount': Decimal('880.00'),
            'payment_method': 'BKASH',
            'payment_status': 'PAID',
            'payment_sender_number': '01655443322',
            'payment_trx_id': 'BKT6710492',
            'order_status': 'PACKING',
            'items': [
                {'product': created_products[0], 'qty': 2, 'price': Decimal('380.00')},
            ]
        },
        {
            'order_number': 'PKP-0004',
            'customer_name': 'Rafiul Islam',
            'customer_phone': '01911002233',
            'customer_email': '',
            'delivery_address': 'House 8, Road 2, Block A, Bashundhara R/A',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'delivery_fee': Decimal('60.00'),
            'subtotal': Decimal('1130.00'),
            'total_amount': Decimal('1190.00'),
            'payment_method': 'COD',
            'payment_status': 'UNPAID',
            'order_status': 'OUT_FOR_DELIVERY',
            'admin_notes': 'Handed over to Pathao Rider #982',
            'items': [
                {'product': created_products[0], 'qty': 1, 'price': Decimal('380.00')},
                {'product': created_products[1], 'qty': 1, 'price': Decimal('360.00')},
                {'product': created_products[2], 'qty': 1, 'price': Decimal('390.00')},
            ]
        },
        {
            'order_number': 'PKP-0005',
            'customer_name': 'Samira Hossain',
            'customer_phone': '01755667788',
            'customer_email': 'samira.h@gmail.com',
            'delivery_address': 'Apartment 6A, Road 27, Dhanmondi',
            'delivery_city': 'Dhaka',
            'delivery_zone': 'INSIDE_DHAKA',
            'delivery_fee': Decimal('60.00'),
            'subtotal': Decimal('740.00'),
            'total_amount': Decimal('800.00'),
            'payment_method': 'NAGAD',
            'payment_status': 'PAID',
            'payment_sender_number': '01755667788',
            'payment_trx_id': 'NGD3910842',
            'order_status': 'DELIVERED',
            'items': [
                {'product': created_products[0], 'qty': 1, 'price': Decimal('380.00')},
                {'product': created_products[1], 'qty': 1, 'price': Decimal('360.00')},
            ]
        }
    ]

    for o_info in orders_data:
        items_data = o_info.pop('items')
        order, created = Order.objects.get_or_create(
            order_number=o_info['order_number'],
            defaults=o_info
        )
        if created:
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

    print("Populated demo orders for admin dashboard.")
    print("Database seeding completed successfully!")

if __name__ == '__main__':
    seed()
