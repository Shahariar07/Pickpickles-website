import os
import re
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils.text import slugify
from store.models import Product


class Command(BaseCommand):
    help = 'Auto-link each product in the database to its corresponding image in media/products/'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate linking without saving changes to the database'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        products_dir = os.path.join(settings.MEDIA_ROOT, 'products')

        if not os.path.exists(products_dir):
            self.stderr.write(self.style.ERROR(f"Media products directory not found at: {products_dir}"))
            return

        available_files = [f for f in os.listdir(products_dir) if os.path.isfile(os.path.join(products_dir, f))]
        self.stdout.write(self.style.NOTICE(f"Found {len(available_files)} files in {products_dir}"))

        products = Product.objects.all().order_by('id')
        updated_count = 0

        for product in products:
            matched_file = None

            # Possible candidate basenames
            candidate_names = []

            # 1. From slug
            if product.slug:
                s = product.slug.strip()
                candidate_names.append(s.replace('-', '_'))
                candidate_names.append(s.replace('_', '-'))

            # 2. From name
            if product.name:
                ns = slugify(product.name)
                candidate_names.append(ns.replace('-', '_'))
                candidate_names.append(ns.replace('_', '-'))

            # 3. From current image if present (clean hash suffix)
            if product.image and product.image.name:
                raw_base = os.path.basename(product.image.name)
                root_no_ext, _ = os.path.splitext(raw_base)
                cleaned_root = re.sub(r'_[a-zA-Z0-9]{5,12}$', '', root_no_ext)
                candidate_names.append(cleaned_root)
                candidate_names.append(cleaned_root.replace('-', '_'))
                candidate_names.append(cleaned_root.replace('_', '-'))

            # Try exact match or extension match
            for base in candidate_names:
                for ext in ['.webp', '.jpg', '.png', '.jpeg']:
                    target = f"{base}{ext}"
                    for actual_file in available_files:
                        if actual_file.lower() == target.lower():
                            matched_file = actual_file
                            break
                    if matched_file:
                        break
                if matched_file:
                    break

            if matched_file:
                new_image_field = f"products/{matched_file}"
                new_image_url = f"/media/products/{matched_file}"

                old_image = str(product.image or '')
                old_url = str(product.image_url or '')

                has_changed = (old_image != new_image_field) or (old_url != new_image_url)

                if has_changed:
                    if not dry_run:
                        product.image = new_image_field
                        product.image_url = new_image_url
                        product.save(update_fields=['image', 'image_url'])
                    updated_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"✓ [{product.id}] {product.name} -> Linked to: {new_image_url}"
                    ))
                else:
                    self.stdout.write(
                        f"• [{product.id}] {product.name} already correctly linked ({new_image_url})"
                    )
            else:
                self.stdout.write(self.style.WARNING(
                    f"⚠ [{product.id}] {product.name}: No matching image found in media/products!"
                ))

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\n[DRY RUN] {updated_count} products would be updated."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nSuccessfully linked/verified {updated_count} products!"))
