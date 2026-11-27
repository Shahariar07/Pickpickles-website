from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0038_promotionsetting_free_delivery_apply_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='promotionsetting',
            name='inside_dhaka_delivery_fee',
            field=models.DecimalField(decimal_places=2, default=Decimal('80.00'), help_text='Base delivery fee Inside Dhaka City (৳).', max_digits=10),
        ),
        migrations.AlterField(
            model_name='promotionsetting',
            name='inside_dhaka_extra_per_jar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Extra delivery fee per additional jar Inside Dhaka starting from extra_jar_start_from (৳).', max_digits=10),
        ),
        migrations.AlterField(
            model_name='promotionsetting',
            name='outside_dhaka_delivery_fee',
            field=models.DecimalField(decimal_places=2, default=Decimal('130.00'), help_text='Base delivery fee Outside Dhaka / Nationwide (৳).', max_digits=10),
        ),
        migrations.AlterField(
            model_name='promotionsetting',
            name='outside_dhaka_extra_per_jar',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Extra delivery fee per additional jar Outside Dhaka starting from extra_jar_start_from (৳).', max_digits=10),
        ),
        migrations.AddField(
            model_name='promotionsetting',
            name='extra_jar_start_from',
            field=models.PositiveIntegerField(
                default=5,
                help_text='Jar number from which extra per-jar delivery charge starts (e.g. 5 means 1–4 jars have 0 extra charge; 5th jar adds 1x extra).',
            ),
        ),
    ]
