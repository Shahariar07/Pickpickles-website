#!/bin/bash
# ==========================================================
# One-Command Update Script for Pickpickles on VPS
# ==========================================================

set -e

PROJECT_DIR="/var/www/pickpickles"

echo ">>> Pulling latest code..."
cd $PROJECT_DIR
git pull origin main

echo ">>> Activating virtual environment & updating packages..."
source venv/bin/activate
pip install -r requirements.txt

echo ">>> Running migrations & collecting static files..."
python manage.py migrate
python manage.py collectstatic --noinput

echo ">>> Restarting services..."
sudo systemctl restart gunicorn_pickpickles
sudo systemctl restart nginx

# Fix permissions
sudo chown -R www-data:www-data $PROJECT_DIR
sudo chmod -R 775 $PROJECT_DIR/media
sudo chmod 664 $PROJECT_DIR/db.sqlite3 || true

echo ">>> Project updated and restarted successfully!"
