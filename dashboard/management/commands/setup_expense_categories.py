from django.core.management.base import BaseCommand
from django.db import transaction, models
from dashboard.models import ExpenseCategory, Expense


class Command(BaseCommand):
    help = 'Sets up canonical Expense Categories, Subcategories, and maps legacy expenses.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Starting Expense Categories & Subcategories setup...'))

        TAXONOMY = {
            'RAW_MATERIAL': {
                'name': 'Fresh Cucumbers & Veggies 🥒',
                'icon': 'fa-carrot',
                'desc': 'Fresh cucumbers, garlic, peppers, veggies, quail eggs and raw produce.',
                'subcategories': [
                    ('Cucumber (শসা)', 'cucumber', 'fa-carrot', 'Fresh green pickling cucumbers'),
                    ('Carrot (গাজর)', 'carrot', 'fa-carrot', 'Fresh carrots'),
                    ('Green Chilli & Capsicum (কাঁচামরিচ ও ক্যাপসিকাম)', 'green-chilli', 'fa-pepper-hot', 'Green chillies, bell peppers & jalapeños'),
                    ('Garlic & Ginger (রসুন ও আদা)', 'garlic-ginger', 'fa-seedling', 'Garlic cloves, ginger roots'),
                    ('Onions (পেঁয়াজ)', 'onions', 'fa-egg', 'Pickling baby shallots & onions'),
                    ('Quail Eggs (কোয়েল পাখির ডিম)', 'quail-eggs', 'fa-egg', 'Farm fresh quail eggs'),
                    ('Beetroot (বিটমূল)', 'beetroot', 'fa-seedling', 'Fresh organic beetroots'),
                ]
            },
            'FRUITS': {
                'name': 'Fresh Fruits (ফলমূল) 🍎',
                'icon': 'fa-apple-whole',
                'desc': 'Fresh pineapples, raw mangoes, grapes, olives, and fruits for artisan pickling.',
                'subcategories': [
                    ('Pineapple & Fruits (আনারস ও ফল)', 'pineapple-fruits', 'fa-apple-whole', 'Fresh pineapples, grapes & fruits'),
                    ('Raw Mango (কাঁচা আম)', 'raw-mango', 'fa-leaf', 'Fresh green sour mangoes'),
                    ('Pineapple (আনারস)', 'pineapple', 'fa-apple-whole', 'Fresh pineapples for sweet & sour relish'),
                    ('Grapes & Berries (আঙ্গুর ও বেরি)', 'grapes-berries', 'fa-apple-whole', 'Seedless green grapes & berries'),
                    ('Olive / Jalpai (জলপাই ও অন্যান্য ফল)', 'jalpai-olive', 'fa-seedling', 'Green olives, jujube (boroi) & seasonal sour fruits'),
                ]
            },
            'PACKAGING': {
                'name': 'Glass Jars, Lids & Labels 🫙',
                'icon': 'fa-jar',
                'desc': 'Food-grade glass jars, airtight gold metal lids, bottles, boxes & sealing supplies.',
                'subcategories': [
                    ('Glass Jars (কাচের বৈয়াম)', 'glass-jars', 'fa-jar', 'Food grade glass jars'),
                    ('Plastic Jars & Bottles (বোতল ও জার)', 'plastic-jars', 'fa-bottle-water', 'Plastic jars and bottles'),
                    ('Lids & Caps (মেটাল ক্যাপ ও ঢাকনা)', 'lids-caps', 'fa-shield-halved', 'Airtight gold caps & seals'),
                    ('Labels & Stickers (স্টিকার ও লেবেল)', 'labels-stickers', 'fa-tag', 'Product label stickers & seals'),
                    ('Cardboard Boxes (কার্টন ও বক্স)', 'cardboard-boxes', 'fa-box-open', 'Shipping cartons & packaging boxes'),
                    ('Bubble Wrap & Tape (বাবল র‍্যাপ ও টেপ)', 'bubble-wrap-tape', 'fa-tape', 'Bubble sheets, scotch tapes & dispensers'),
                    ('Sealing Machine & Tools (সিলিং মেশিন ও সরঞ্জাম)', 'sealing-machine', 'fa-gears', 'Induction sealers & packaging tools'),
                ]
            },
            'SPICES_BRINE': {
                'name': 'Vinegar, Spices & Brine 🌿',
                'icon': 'fa-leaf',
                'desc': 'Pure cane vinegar, pickling salt, pink salt, sugar, whole spices & brine herbs.',
                'subcategories': [
                    ('Vinegar (ভিনেগার)', 'vinegar', 'fa-bottle-droplet', 'Pure cane and white vinegar'),
                    ('Dill & Dry Herbs (ডিল ও ভেষজ)', 'dill-herbs', 'fa-spa', 'Fresh dill weed, bay leaves & dried herbs'),
                    ('Salt & Pink Salt (লবণ ও পিংক সল্ট)', 'salt-pink-salt', 'fa-cubes-stacked', 'Pickling salt, crystal salt & Himalayan pink salt'),
                    ('Sugar (চিনি)', 'sugar', 'fa-cube', 'Refined white & brown sugar'),
                    ('Mustard Oil & Seeds (সরিষার তেল ও সরিষা)', 'mustard-oil-seeds', 'fa-droplet', 'Cold-pressed mustard oil & whole mustard seeds'),
                    ('Whole Spices & Peppercorn (গোলমরিচ ও গোটা মসলা)', 'whole-spices', 'fa-pepper-hot', 'Black peppercorns, coriander & whole spices'),
                    ('Purified Water (ফিল্টার পানি)', 'purified-water', 'fa-glass-water', 'Clean purified water for brine preparation'),
                ]
            },
            'LOGISTICS': {
                'name': 'Courier & Logistics 🚚',
                'icon': 'fa-truck-fast',
                'desc': 'Courier parcel shipping fees, return fees, and local transport conveyance.',
                'subcategories': [
                    ('Courier Delivery Fee (ডেলিভারি চার্জ)', 'courier-delivery-fee', 'fa-truck', 'Courier shipping and doorstep delivery fees'),
                    ('Courier Return Fee (রিটার্ন কুরিয়ার চার্জ)', 'courier-return-fee', 'fa-rotate-left', 'Courier charge on customer return parcels'),
                    ('Local Transport & Conveyance (যাতায়াত)', 'local-transport', 'fa-van-shuttle', 'Rickshaw, pickup van & market transport'),
                ]
            },
            'MARKETING': {
                'name': 'Digital Ads & Marketing 📢',
                'icon': 'fa-bullhorn',
                'desc': 'Facebook page sponsored boost ads, creative content and digital promotions.',
                'subcategories': [
                    ('Facebook / Meta Ads (ফেসবুক বুস্টিং)', 'facebook-ads', 'fa-rectangle-ad', 'Meta boost campaigns & sponsored ads'),
                    ('Promotions & Content (প্রোমোশন ও কনটেন্ট)', 'content-promo', 'fa-photo-film', 'Photography, video content & promotional creatives'),
                ]
            },
            'UTILITIES': {
                'name': 'Gas, Electricity & Rent ⚡',
                'icon': 'fa-bolt',
                'desc': 'Kitchen utilities, gas cylinders, electricity, water bills and production space rent.',
                'subcategories': [
                    ('Gas Cylinder (গ্যাস সিলিন্ডার)', 'gas-cylinder', 'fa-fire-flame-curved', 'LPG gas cylinder refills for pickling'),
                    ('Electricity & Water Bill (বিদ্যুৎ ও পানি)', 'electricity-water', 'fa-lightbulb', 'Monthly utilities bill for kitchen prep'),
                    ('Kitchen Rent (কিচেন ভাড়া)', 'kitchen-rent', 'fa-house-chimney', 'Monthly rent for pickle processing workspace'),
                ]
            },
            'DAMAGE_LOSS': {
                'name': 'Damaged & Broken Products Loss 💥',
                'icon': 'fa-burst',
                'desc': 'Financial loss from courier breakage, kitchen spills, and damaged returns.',
                'subcategories': [
                    ('Courier Breakage Loss (কুরিয়ার ভাঙচুর ক্ষতি)', 'courier-breakage', 'fa-box-tissue', 'Jars broken during delivery transit'),
                    ('Damaged Customer Return (রিটার্ন প্রোডাক্ট ক্ষতি)', 'return-damaged', 'fa-box-archive', 'Returned parcels with leaked or unsellable jars'),
                    ('Kitchen Spoilage & Spill (কিচেন নষ্ট ক্ষতি)', 'kitchen-spoilage', 'fa-trash-can', 'Kitchen prep spills or cap seal defects'),
                ]
            },
            'OTHER': {
                'name': 'Operational & Miscellaneous 📋',
                'icon': 'fa-receipt',
                'desc': 'Sanitizing supplies, kitchen tools, maintenance and miscellaneous expenses.',
                'subcategories': [
                    ('Kitchen Tools & Cleaning (পরিষ্কার সরঞ্জাম ও টুলস)', 'kitchen-tools', 'fa-broom', 'Gloves, sanitizers, cutting boards, knives'),
                    ('Miscellaneous & Stationery (বিবিধ ও স্টেশনারি)', 'miscellaneous', 'fa-receipt', 'Stationery, markers, adhesive tapes and sundries'),
                ]
            }
        }

        with transaction.atomic():
            # 1. Parent Categories - strictly preserve existing database entries
            parent_map = {}
            for p_slug, p_data in TAXONOMY.items():
                p_obj = ExpenseCategory.objects.filter(slug=p_slug).first()
                if not p_obj:
                    p_obj = ExpenseCategory.objects.filter(name=p_data['name']).first()

                if not p_obj:
                    # Only create if completely absent in database
                    p_obj = ExpenseCategory.objects.create(
                        slug=p_slug,
                        name=p_data['name'],
                        icon=p_data['icon'],
                        description=p_data['desc'],
                        parent=None
                    )
                # If already exists in database, do NOT modify p_obj.name, icon, or anything!
                parent_map[p_slug] = p_obj

            # 2. Subcategories - strictly preserve existing database entries
            for p_slug, p_data in TAXONOMY.items():
                p_obj = parent_map[p_slug]
                for sub_name, sub_slug, sub_icon, sub_desc in p_data['subcategories']:
                    sub_obj = ExpenseCategory.objects.filter(slug=sub_slug).first()
                    if not sub_obj:
                        sub_obj = ExpenseCategory.objects.filter(name=sub_name).first()

                    if not sub_obj:
                        # Only create if completely absent in database
                        ExpenseCategory.objects.create(
                            name=sub_name,
                            slug=sub_slug,
                            parent=p_obj,
                            icon=sub_icon,
                            description=sub_desc
                        )
                    # If already exists, do not touch or alter!

        self.stdout.write(self.style.SUCCESS('Expense Categories verified. Existing database entries were preserved.'))
