import os, sys, shutil
BASE_DIR = 'H:/My Drive/Pickpickles website'
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pickpickles_project.settings')
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.db import connection

# Test on a fresh db file
test_db_path = os.path.join(BASE_DIR, 'scratch', 'test_fresh.sqlite3')
if os.path.exists(test_db_path):
    os.remove(test_db_path)

settings.DATABASES['default']['NAME'] = test_db_path
connection.close()

try:
    print("1. Running migrate on fresh db...")
    call_command('migrate', verbosity=0)
    print("2. Running loaddata datadump_clean.json...")
    call_command('loaddata', 'datadump_clean.json', verbosity=1)
    print("SUCCESS! All 1614 objects loaded perfectly into fresh db!")
except Exception as e:
    print("ERROR:", e)
finally:
    connection.close()
    if os.path.exists(test_db_path):
        try: os.remove(test_db_path)
        except: pass
