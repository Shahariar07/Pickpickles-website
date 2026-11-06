import os, sys, shutil

BASE_DIR = 'H:/My Drive/Pickpickles website'
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

backup_path = os.path.join(BASE_DIR, 'db.sqlite3.backup_before_live_dump')
if not os.path.exists(backup_path):
    shutil.copy2('db.sqlite3', backup_path)
    print("Safety backup verified at:", backup_path)

temp_db = os.path.join(BASE_DIR, 'db_live_fresh.sqlite3')
if os.path.exists(temp_db):
    try: os.remove(temp_db)
    except: pass

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.db import connection

settings.DATABASES['default']['NAME'] = temp_db
connection.close()

print("1. Migrating schema on live fresh db...")
call_command('migrate', verbosity=0)

print("2. Loading all 1,614 live business objects (Orders, Products, Stock, Expenses, Reviews)...")
call_command('loaddata', 'datadump_clean.json', verbosity=1)

connection.close()

print("3. Replacing db.sqlite3 with the live synchronized database...")
target_db = os.path.join(BASE_DIR, 'db.sqlite3')
if os.path.exists(target_db):
    try:
        os.remove(target_db)
    except Exception as e:
        print("Warning removing old db, trying copy over:", e)

shutil.move(temp_db, target_db)
print("Successfully replaced db.sqlite3!")

# Verify counts in new db.sqlite3
settings.DATABASES['default']['NAME'] = target_db
connection.close()

from store.models import Product, Order, OrderItem, Review
from dashboard.models import StockLog, Expense, ProductionBatch

print("\n--- Live Data Verification Summary ---")
print(f"Products: {Product.objects.count()}")
print(f"Orders: {Order.objects.count()}")
print(f"Order Items: {OrderItem.objects.count()}")
print(f"Customer Reviews: {Review.objects.count()}")
print(f"Stock Logs: {StockLog.objects.count()}")
print(f"Expenses: {Expense.objects.count()}")
print(f"Production Batches: {ProductionBatch.objects.count()}")
print("--------------------------------------")
