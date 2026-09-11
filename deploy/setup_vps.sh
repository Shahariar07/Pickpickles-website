#!/bin/bash
# ==========================================================
# Automated Setup Script for Pickpickles on Ubuntu/Debian VPS
# ==========================================================

set -e

PROJECT_DIR="/var/www/pickpickles"
USER_RUN="www-data"

echo "========================================="
echo " Starting Pickpickles VPS Setup..."
echo "========================================="

# 1. Update OS and install system dependencies
echo ">>> [1/7] Updating system packages & installing dependencies..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv python3-dev nginx certbot python3-certbot-nginx libpq-dev libjpeg-dev zlib1g-dev

# 2. Create project directory if not exists
echo ">>> [2/7] Setting up project directory..."
sudo mkdir -p $PROJECT_DIR
sudo mkdir -p /var/log/gunicorn
sudo chown -R $USER:$USER $PROJECT_DIR
sudo chown -R $USER_RUN:$USER_RUN /var/log/gunicorn

# 3. Virtual Environment setup
echo ">>> [3/7] Setting up Python virtual environment..."
cd $PROJECT_DIR
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Check for .env file
if [ ! -f ".env" ]; then
    echo ">>> Creating .env from template (Please update secret key and domain later)..."
    cp .env.production.example .env
fi

# 5. Database migration & Static files
echo ">>> [4/7] Running database migrations & collecting static files..."
python manage.py migrate
python manage.py collectstatic --noinput

# 6. Setup Gunicorn Systemd Service
echo ">>> [5/7] Configuring Gunicorn systemd service..."
sudo cp deploy/gunicorn.service /etc/systemd/system/gunicorn_pickpickles.service
sudo systemctl daemon-reload
sudo systemctl enable gunicorn_pickpickles
sudo systemctl restart gunicorn_pickpickles

# 7. Setup Nginx Configuration
echo ">>> [6/7] Configuring Nginx web server..."
sudo cp deploy/nginx_pickpickles.conf /etc/nginx/sites-available/pickpickles
sudo ln -sf /etc/nginx/sites-available/pickpickles /etc/nginx/sites-enabled/
# Remove default nginx site if exists
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# 8. Fix file permissions for SQLite and media uploads
echo ">>> [7/7] Setting directory permissions for www-data..."
sudo chown -R $USER_RUN:$USER_RUN $PROJECT_DIR
sudo chmod -R 775 $PROJECT_DIR/media
sudo chmod 664 $PROJECT_DIR/db.sqlite3 || true

echo "========================================="
echo " Deployment Completed Successfully!"
echo " Next step: Run SSL setup using:"
echo "   sudo certbot --nginx -d pickpickles.xyz -d www.pickpickles.xyz"
echo "========================================="
