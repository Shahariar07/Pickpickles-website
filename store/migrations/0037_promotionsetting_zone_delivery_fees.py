from decimal import Decimal
from django.db import migrations, models


def migrate_existing_promo_delivery(apps, schema_editor):
    PromotionSetting = apps.get_model('store', 'PromotionSetting')
    for promo in PromotionSetting.objects.all():
        updated = False
        if promo.standard_delivery_fee == Decimal('150.00'):
            promo.inside_dhaka_delivery_fee = Decimal('80.00')
            promo.outside_dhaka_delivery_fee = Decimal('130.00')
            promo.standard_delivery_fee = Decimal('130.00')
            updated = True
        else:
            promo.inside_dhaka_delivery_fee = promo.standard_delivery_fee
            promo.outside_dhaka_delivery_fee = promo.standard_delivery_fee
            updated = True

        if promo.delivery_notice_text and 'flat ৳150 nationwide' in promo.delivery_notice_text.lower():
            promo.delivery_notice_text = ''
            updated = True

        if promo.announcement_bar_text and 'Nationwide Delivery Flat ৳150' in promo.announcement_bar_text:
            promo.announcement_bar_text = promo.announcement_bar_text.replace(
                'Nationwide Delivery Flat ৳150',
                'Inside Dhaka ৳80 & Outside Dhaka ৳130'
            )
            updated = True

        if updated:
            promo.save()


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0036_order_cancel_reason_order_cancel_reason_note_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='promotionsetting',
            name='inside_dhaka_delivery_fee',
            field=models.DecimalField(decimal_places=2, default=Decimal('80.00'), help_text='Base delivery fee for 1st jar Inside Dhaka City (৳).', max_digits=10),
        ),
        migrations.AddField(
            model_name='promotionsetting',
            name='inside_dhaka_extra_per_jar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Extra delivery fee for each additional jar after the 1st Inside Dhaka (৳).', max_digits=10),
        ),
        migrations.AddField(
            model_name='promotionsetting',
            name='outside_dhaka_delivery_fee',
            field=models.DecimalField(decimal_places=2, default=Decimal('130.00'), help_text='Base delivery fee for 1st jar Outside Dhaka / Nationwide (৳).', max_digits=10),
        ),
        migrations.AddField(
            model_name='promotionsetting',
            name='outside_dhaka_extra_per_jar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Extra delivery fee for each additional jar after the 1st Outside Dhaka (৳).', max_digits=10),
        ),
        migrations.AlterField(
            model_name='promotionsetting',
            name='announcement_bar_text',
            field=models.CharField(blank=True, default='🎁 2 Jars Flat ৳50 OFF • 🚚 Inside Dhaka ৳80 & Outside Dhaka ৳130!', help_text='Header announcement text.', max_length=300),
        ),
        migrations.AlterField(
            model_name='promotionsetting',
            name='delivery_notice_text',
            field=models.CharField(blank=True, default='', help_text='Optional custom delivery notice note (leave blank to auto-generate dynamically from rates).', max_length=255),
        ),
        migrations.AlterField(
            model_name='promotionsetting',
            name='standard_delivery_fee',
            field=models.DecimalField(decimal_places=2, default=Decimal('130.00'), help_text='Fallback / nationwide standard delivery fee.', max_digits=10),
        ),
        migrations.RunPython(migrate_existing_promo_delivery, migrations.RunPython.noop),
    ]
