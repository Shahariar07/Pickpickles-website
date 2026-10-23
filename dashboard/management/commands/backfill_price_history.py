from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from store.models import Product, OrderItem
from dashboard.models import PriceHistory

User = get_user_model()


class Command(BaseCommand):
    help = "Reconstruct and backfill historical price revisions from past order transactions and current product prices"

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all existing PriceHistory records before backfilling',
        )

    def handle(self, *args, **options):
        clear_existing = options.get('clear', False)

        if clear_existing:
            count = PriceHistory.objects.count()
            PriceHistory.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Cleared {count} existing PriceHistory records."))

        staff_user = User.objects.filter(is_staff=True).order_by('id').first()
        created_count = 0
        total_products = Product.objects.count()

        self.stdout.write(self.style.NOTICE(f"Scanning {total_products} products and order transaction history..."))

        for product in Product.objects.all().order_by('name'):
            # Fetch all order items chronologically
            order_items = (
                OrderItem.objects.filter(product=product)
                .select_related('order')
                .order_by('order__created_at')
            )

            # Reconstruct distinct price points over time
            price_timeline = []
            last_price = None

            for item in order_items:
                unit_p = Decimal(str(item.unit_price))
                if last_price is None or unit_p != last_price:
                    order_date = item.order.created_at if item.order else timezone.now()
                    order_num = item.order.order_number if item.order else 'N/A'
                    price_timeline.append({
                        'price': unit_p,
                        'date': order_date,
                        'order_number': order_num,
                    })
                    last_price = unit_p

            current_p = Decimal(str(product.price_bdt))
            orig_p = Decimal(str(product.original_price_bdt)) if product.original_price_bdt else None

            # Case A: If orders exist, build step-by-step price revisions
            if price_timeline:
                # 1. Initial price from first recorded order
                first_point = price_timeline[0]
                first_price = first_point['price']

                # Check if initial record already exists
                initial_exists = PriceHistory.objects.filter(
                    product=product,
                    change_type='INITIAL'
                ).exists()

                if not initial_exists:
                    init_rec = PriceHistory.objects.create(
                        product=product,
                        old_price=first_price,
                        new_price=first_price,
                        new_original_price=orig_p,
                        price_delta=Decimal('0.00'),
                        percentage_change=Decimal('0.00'),
                        change_type='INITIAL',
                        reason="Initial launch / earliest order price",
                        notes=f"Reconstructed from Order #{first_point['order_number']}",
                        changed_by=staff_user,
                    )
                    PriceHistory.objects.filter(id=init_rec.id).update(created_at=first_point['date'])
                    created_count += 1

                prev_price = first_price

                # 2. Subsequent order price changes
                for pt in price_timeline[1:]:
                    new_p = pt['price']
                    if new_p != prev_price:
                        delta = new_p - prev_price
                        chg_type = 'INCREASE' if delta > 0 else 'DECREASE'

                        # Check if this transition already logged
                        already_logged = PriceHistory.objects.filter(
                            product=product,
                            old_price=prev_price,
                            new_price=new_p,
                            change_type=chg_type
                        ).exists()

                        if not already_logged:
                            rec = PriceHistory.objects.create(
                                product=product,
                                old_price=prev_price,
                                new_price=new_p,
                                new_original_price=orig_p,
                                change_type=chg_type,
                                reason=f"Price revised to BDT {new_p}",
                                notes=f"Detected from historical order #{pt['order_number']}",
                                changed_by=staff_user,
                            )
                            PriceHistory.objects.filter(id=rec.id).update(created_at=pt['date'])
                            created_count += 1

                        prev_price = new_p

                # 3. Transition from last order price to current catalog price (if changed since then)
                if current_p != prev_price:
                    delta = current_p - prev_price
                    chg_type = 'INCREASE' if delta > 0 else 'DECREASE'

                    already_logged = PriceHistory.objects.filter(
                        product=product,
                        old_price=prev_price,
                        new_price=current_p,
                        change_type=chg_type
                    ).exists()

                    if not already_logged:
                        rec = PriceHistory.objects.create(
                            product=product,
                            old_price=prev_price,
                            new_price=current_p,
                            new_original_price=orig_p,
                            change_type=chg_type,
                            reason="Catalog price revision to current rate",
                            notes="Updated in inventory catalog",
                            changed_by=staff_user,
                        )
                        # Latest change happens shortly after last order or recent time
                        PriceHistory.objects.filter(id=rec.id).update(created_at=timezone.now())
                        created_count += 1

            else:
                # Case B: No past orders exist for this product, create baseline initial record
                initial_exists = PriceHistory.objects.filter(
                    product=product,
                    change_type='INITIAL'
                ).exists()

                if not initial_exists:
                    init_rec = PriceHistory.objects.create(
                        product=product,
                        old_price=current_p,
                        new_price=current_p,
                        new_original_price=orig_p,
                        price_delta=Decimal('0.00'),
                        percentage_change=Decimal('0.00'),
                        change_type='INITIAL',
                        reason="Initial product baseline price",
                        notes="Configured in inventory catalog",
                        changed_by=staff_user,
                    )
                    created_count += 1

        total_now = PriceHistory.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully backfilled price history! Added {created_count} historical entries. Total records now: {total_now}"
            )
        )
