# Pickpickles VPS Deployment Guide (Ubuntu / Debian)

This guide walks you through setting up and running Pickpickles on a VPS using **Nginx + Gunicorn + Systemd**.

---

## 📁 Prepared Deployment Files

| File | Purpose |
|---|---|
| [deploy/gunicorn.service](file:///h:/My%20Drive/Pickpickles%20website/deploy/gunicorn.service) | Systemd background service for Gunicorn |
| [deploy/nginx_pickpickles.conf](file:///h:/My%20Drive/Pickpickles%20website/deploy/nginx_pickpickles.conf) | Nginx configuration (Reverse Proxy, Static/Media files) |
| [deploy/setup_vps.sh](file:///h:/My%20Drive/Pickpickles%20website/deploy/setup_vps.sh) | 1-Click automated server installation script |
| [deploy/update.sh](file:///h:/My%20Drive/Pickpickles%20website/deploy/update.sh) | 1-Command update script for pulling new code |
| [.env.production.example](file:///h:/My%20Drive/Pickpickles%20website/.env.production.example) | Production environment variable template |

---

## 🚀 Quick Setup Steps on VPS

### Step 1: Clone Repository on VPS
```bash
sudo git clone <YOUR_GIT_REPO_URL> /var/www/pickpickles
cd /var/www/pickpickles
```

### Step 2: Upload Live Data from Shared Hosting
Upload your backup files into `/var/www/pickpickles/`:
- `db.sqlite3`
- `media/` folder (extract all product images here)

### Step 3: Configure `.env`
```bash
cp .env.production.example .env
nano .env
```
Set `DJANGO_DEBUG=False`, your domain names, and secret key.

### Step 4: Run Automated Setup Script
```bash
chmod +x deploy/setup_vps.sh
./deploy/setup_vps.sh
```

### Step 5: Enable Free SSL (HTTPS) with Certbot
```bash
sudo certbot --nginx -d pickpickles.xyz -d www.pickpickles.xyz
```

---

## 🔄 How to Update Code in the Future
Whenever you push changes to Git:
```bash
cd /var/www/pickpickles
chmod +x deploy/update.sh
./deploy/update.sh
```
