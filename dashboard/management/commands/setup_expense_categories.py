from django.core.management.base import BaseCommand
from django.db import transaction
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
                    ('Raw Mango (কাঁচা আম)', 'raw-mango', 'fa-leaf', 'Fresh green mangoes'),
                    ('Pineapple & Fruits (আনারস ও ফল)', 'pineapple-fruits', 'fa-apple-whole', 'Fresh pineapples, grapes & fruits'),
                    ('Quail Eggs (কোয়েল পাখির ডিম)', 'quail-eggs', 'fa-egg', 'Farm fresh quail eggs'),
                    ('Beetroot (বিটমূল)', 'beetroot', 'fa-seedling', 'Fresh organic beetroots'),
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
            # 1. Parent Categories
            parent_map = {}
            for p_slug, p_data in TAXONOMY.items():
                p_obj, _ = ExpenseCategory.objects.update_or_create(
                    slug=p_slug,
                    defaults={
                        'name': p_data['name'],
                        'icon': p_data['icon'],
                        'description': p_data['desc'],
                        'parent': None
                    }
                )
                parent_map[p_slug] = p_obj

            # 2. Subcategories
            valid_sub_ids = []
            for p_slug, p_data in TAXONOMY.items():
                p_obj = parent_map[p_slug]
                for sub_name, sub_slug, sub_icon, sub_desc in p_data['subcategories']:
                    sub_obj = ExpenseCategory.objects.filter(slug=sub_slug).first()
                    if not sub_obj:
                        sub_obj = ExpenseCategory.objects.filter(name=sub_name).first()

                    if sub_obj:
                        sub_obj.name = sub_name
                        sub_obj.slug = sub_slug
                        sub_obj.parent = p_obj
                        sub_obj.icon = sub_icon
                        sub_obj.description = sub_desc
                        sub_obj.save()
                    else:
                        sub_obj = ExpenseCategory.objects.create(
                            name=sub_name,
                            slug=sub_slug,
                            parent=p_obj,
                            icon=sub_icon,
                            description=sub_desc
                        )
                    valid_sub_ids.append(sub_obj.id)

            # 3. Clean up obsolete legacy categories
            all_valid_ids = [p.id for p in parent_map.values()] + valid_sub_ids
            deleted_count, _ = ExpenseCategory.objects.exclude(id__in=all_valid_ids).delete()
            if deleted_count:
                self.stdout.write(self.style.SUCCESS(f'Removed {deleted_count} obsolete duplicate category records.'))

            # 4. Map legacy categories on Expenses
            legacy_mappings = [
                # salt -> SPICES_BRINE + Salt & Pink Salt
                ({'category__iexact': 'salt'}, 'SPICES_BRINE', 'Salt & Pink Salt (লবণ ও পিংক সল্ট)'),
                # sugar -> SPICES_BRINE + Sugar
                ({'category__iexact': 'sugar'}, 'SPICES_BRINE', 'Sugar (চিনি)'),
                # herb -> SPICES_BRINE + Dill & Dry Herbs
                ({'category__iexact': 'herb'}, 'SPICES_BRINE', 'Dill & Dry Herbs (ডিল ও ভেষজ)'),
                # water -> SPICES_BRINE + Purified Water
                ({'category__iexact': 'water'}, 'SPICES_BRINE', 'Purified Water (ফিল্টার পানি)'),
                # communication -> LOGISTICS or MARKETING
                ({'category__iexact': 'communication', 'title__icontains': 'ads'}, 'MARKETING', 'Facebook / Meta Ads (ফেসবুক বুস্টিং)'),
                ({'category__iexact': 'communication'}, 'LOGISTICS', 'Local Transport & Conveyance (যাতায়াত)'),
            ]

            for filter_kwargs, cat_slug, sub_name in legacy_mappings:
                updated = Expense.objects.filter(**filter_kwargs).update(category=cat_slug, sub_category=sub_name)
                if updated:
                    self.stdout.write(f'Updated {updated} legacy expenses to {cat_slug} ➔ {sub_name}')

            # Auto-assign subcategories for common raw material / packaging items without subcategories
            Expense.objects.filter(category='RAW_MATERIAL', sub_category='', title__icontains='cucumber').update(sub_category='Cucumber (শসা)')
            Expense.objects.filter(category='RAW_MATERIAL', sub_category='', title__icontains='shosa').update(sub_category='Cucumber (শসা)')
            Expense.objects.filter(category='RAW_MATERIAL', sub_category='', title__icontains='quail').update(sub_category='Quail Eggs (কোয়েল পাখির ডিম)')
            Expense.objects.filter(category='RAW_MATERIAL', sub_category='', title__icontains='mango').update(sub_category='Raw Mango (কাঁচা আম)')
            Expense.objects.filter(category='RAW_MATERIAL', sub_category='', title__icontains='pineapple').update(sub_category='Pineapple & Fruits (আনারস ও ফল)')
            Expense.objects.filter(category='RAW_MATERIAL', sub_category='', title__icontains='grapes').update(sub_category='Pineapple & Fruits (আনারস ও ফল)')
            Expense.objects.filter(category='RAW_MATERIAL', sub_category='', title__icontains='morich').update(sub_category='Green Chilli & Capsicum (কাঁচামরিচ ও ক্যাপসিকাম)')

            Expense.objects.filter(category='SPICES_BRINE', sub_category='', title__icontains='vinegar').update(sub_category='Vinegar (ভিনেগার)')
            Expense.objects.filter(category='PACKAGING', sub_category='', title__icontains='jar').update(sub_category='Glass Jars (কাচের বৈয়াম)')
            Expense.objects.filter(category='PACKAGING', sub_category='', title__icontains='cardboard').update(sub_category='Cardboard Boxes (কার্টন ও বক্স)')
            Expense.objects.filter(category='PACKAGING', sub_category='', title__icontains='cartboard').update(sub_category='Cardboard Boxes (কার্টন ও বক্স)')
            Expense.objects.filter(category='PACKAGING', sub_category='', title__icontains='bubble').update(sub_category='Bubble Wrap & Tape (বাবল র‍্যাপ ও টেপ)')
            Expense.objects.filter(category='PACKAGING', sub_category='', title__icontains='sealing').update(sub_category='Sealing Machine & Tools (সিলিং মেশিন ও সরঞ্জাম)')

            Expense.objects.filter(category='LOGISTICS', sub_category='', title__icontains='delivery').update(sub_category='Courier Delivery Fee (ডেলিভারি চার্জ)')
            Expense.objects.filter(category='LOGISTICS', sub_category='', title__icontains='return fee').update(sub_category='Courier Return Fee (রিটার্ন কুরিয়ার চার্জ)')
            Expense.objects.filter(category='DAMAGE_LOSS', sub_category='').update(sub_category='Damaged Customer Return (রিটার্ন প্রোডাক্ট ক্ষতি)')

        self.stdout.write(self.style.SUCCESS('Successfully configured all Expense Categories and Subcategories!'))
