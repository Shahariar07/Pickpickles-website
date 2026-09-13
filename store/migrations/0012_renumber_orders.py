from django.db import migrations

def renumber_orders(apps, schema_editor):
    Order = apps.get_model('store', 'Order')
    orders = list(Order.objects.all().order_by('created_at', 'id'))
    
    # Assign temporary unique order numbers first to avoid unique constraint collision
    for idx, order in enumerate(orders, start=1):
        order.order_number = f"TEMP-{order.id}-{idx}"
        order.save(update_fields=['order_number'])
        
    # Assign sequential order numbers starting from PKP-00001
    for idx, order in enumerate(orders, start=1):
        order.order_number = f"PKP-{idx:05d}"
        order.save(update_fields=['order_number'])

class Migration(migrations.Migration):

    dependencies = [
        ('store', '0011_alter_order_delivery_city_alter_order_delivery_fee_and_more'),
    ]

    operations = [
        migrations.RunPython(renumber_orders, migrations.RunPython.noop),
    ]
