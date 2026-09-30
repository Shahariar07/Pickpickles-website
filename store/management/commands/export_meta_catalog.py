import os
import csv
from django.core.management.base import BaseCommand
from django.conf import settings
from store.models import Product

class Command(BaseCommand):
    help = 'Export all products to a CSV file compatible with Meta Commerce Manager (Facebook / Instagram Shop Catalog).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default='meta_products_catalog.csv',
            help='Output CSV filename or path (default: meta_products_catalog.csv)'
        )
        parser.add_argument(
            '--base-url',
            type=str,
            default='https://pickpickles.xyz',
            help='Base website domain URL (default: https://pickpickles.xyz)'
        )

    def handle(self, *args, **options):
        output_file = options['output']
        base_url = options['base_url'].rstrip('/')

        fields = [
            'id',
            'title',
            'description',
            'availability',
            'condition',
            'price',
            'link',
            'image_link',
            'brand',
            'google_product_category',
            'fb_product_category',
            'product_type',
            'inventory',
            'sale_price',
            'weight'
        ]

        products = Product.objects.all().order_by('id')
        rows = []

        for p in products:
            raw_img = p.primary_image_url.split('?')[0] if p.primary_image_url else ''
            if raw_img.startswith('/'):
                image_link = f'{base_url}{raw_img}'
            elif raw_img.startswith('http'):
                image_link = raw_img
            else:
                image_link = f'{base_url}/media/{raw_img}'

            product_link = f'{base_url}/product/{p.slug}/'
            avail = 'in stock' if (p.is_in_stock and p.stock_count > 0) else 'out of stock'
            price_val = f'{p.price_bdt:.2f} BDT'
            title = f'{p.name} ({p.jar_weight_grams}g)'
            cat_name = p.category.name if p.category else 'Pickles'
            weight_str = f'{p.jar_weight_grams} g'

            row = {
                'id': f'PKP-{p.id}',
                'title': title,
                'description': p.description.strip(),
                'availability': avail,
                'condition': 'new',
                'price': price_val,
                'link': product_link,
                'image_link': image_link,
                'brand': 'Pickpickles',
                'google_product_category': 'Food, Beverages & Tobacco > Food Items > Condiments & Sauces > Pickles & Relishes',
                'fb_product_category': 'Food & Beverage > Food Items > Condiments & Sauces > Pickles & Relishes',
                'product_type': cat_name,
                'inventory': p.stock_count,
                'sale_price': price_val,
                'weight': weight_str
            }
            rows.append(row)

        target_path = os.path.join(settings.BASE_DIR, output_file) if not os.path.isabs(output_file) else output_file

        with open(target_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(self.style.SUCCESS(
            f'Successfully exported {len(rows)} products to {target_path} for Meta Commerce Manager.'
        ))
