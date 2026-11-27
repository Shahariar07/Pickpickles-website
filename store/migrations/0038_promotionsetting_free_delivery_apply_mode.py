from django.db import migrations, models


def activate_exact_four_jar_free_delivery(apps, schema_editor):
    PromotionSetting = apps.get_model('store', 'PromotionSetting')
    PromotionSetting.objects.all().update(
        free_delivery_enabled=True,
        free_delivery_min_jars=4,
        free_delivery_apply_mode='EXACT',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0037_promotionsetting_zone_delivery_fees'),
    ]

    operations = [
        migrations.AlterField(
            model_name='promotionsetting',
            name='free_delivery_min_jars',
            field=models.PositiveIntegerField(default=4, help_text='Jar count needed for free delivery.'),
        ),
        migrations.AddField(
            model_name='promotionsetting',
            name='free_delivery_apply_mode',
            field=models.CharField(
                choices=[
                    ('EXACT', 'Exactly Minimum Jars (e.g. exactly 2 jars)'),
                    ('AT_LEAST', 'Minimum Jars or More (e.g. 2 or more jars)'),
                ],
                default='EXACT',
                help_text='Apply free delivery on exact jar count (e.g. exact 4 jars) or minimum threshold (e.g. 4+ jars).',
                max_length=20,
            ),
        ),
        migrations.RunPython(activate_exact_four_jar_free_delivery, migrations.RunPython.noop),
    ]
