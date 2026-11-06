import os, sys, json
BASE_DIR = 'H:/My Drive/Pickpickles website'
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()
from store.models import Product

print('Local products:')
for p in Product.objects.all():
    print(f'  pk={p.pk}, slug={p.slug}, name={p.name}')

print('\nDump products:')
with open('datadump_clean.json', encoding='utf-8') as f:
    dump = json.load(f)
for item in dump:
    if item['model'] == 'store.product':
        print(f"  pk={item.get('pk')}, slug={item['fields'].get('slug')}, name={item['fields'].get('name')}")
