# 🛡️ Universal Production Security & Deployment Master Guide
*(Django + PostgreSQL + aaPanel / Nginx / Linux VPS)*

এই গাইডটি অনুসরণ করে আপনি আপনার **Django ই-কমার্স বা ওয়েব অ্যাপ্লিকেশনকে** সর্বোচ্চ লেভেলের প্রোডাকশন সিকিউরিটি (OWASP Top 10 Standard - **Score 10/10**) এবং সর্বোচ্চ স্পিড প্রদান করতে পারবেন।

> ⚠️ **গুরুত্বপূর্ণ সতর্কতা:** আপনি যদি **aaPanel** ব্যবহার করেন, তবে ফায়ারওয়াল বা সিকিউরিটি রুল দেওয়ার সময় aaPanel-এর পোর্ট ব্লক করবেন না। নিচে নিরাপদ ও পরীক্ষিত নিয়মগুলো দেওয়া হলো।

---

## 📑 সূচিপত্র
1. [Phase 1: Django Settings-এ প্রোডাকশন সিকিউরিটি](#-phase-1-django-settings-এ-প্রোডাকশন-সিকিউরিটি)
2. [Phase 2: .env ফাইল ও সিক্রেট কি (Secret Key) অটোমেশন](#-phase-2-env-ফাইল-ও-সিক্রেট-কি-secret-key-অটোমেশন)
3. [Phase 3: Nginx সার্ভার ব্লক ও সিকিউরিটি কনফিগারেশন](#-phase-3-nginx-সার্ভার-ব্লক-ও-সিকিউরিটি-কনফিগারেশন)
4. [Phase 4: VPS ফায়ারওয়াল ও ওএস (Linux / aaPanel) নিরাপদ সিকিউরিটি](#-phase-4-vps-ফায়ারওয়াল-ও-ওএস-linux--aapanel-নিরাপদ-সিকিউরিটি)
5. [Phase 5: PostgreSQL ডাটাবেজ সুরক্ষা ও অটো-ব্যাকআপ (Cron Job)](#-phase-5-postgresql-ডাটাবেজ-সুরক্ষা-ও-অটো-ব্যাকআপ-cron-job)
6. [Phase 6: সিকিউরিটি টেস্ট ও ভেরিফিকেশন কমান্ড](#-phase-6-সিকিউরিটি-টেস্ট-ও-ভেরিফিকেশন-কমান্ড)
7. [Phase 7: Cloudflare CDN, WAF ও DDoS সুরক্ষা সেটআপ](#-phase-7-cloudflare-cdn-waf-ও-ddos-সুরক্ষা-সেটআপ)
8. [Phase 8: ট্রাবলশুটিং (সাইট বা aaPanel স্লো হলে করণীয়)](#-phase-8-ট্রাবলশুটিং-সাইট-বা-aapanel-স্লো-হলে-করণীয়)

---

## 🛡️ Phase 1: Django Settings-এ প্রোডাকশন সিকিউরিটি

আপনার প্রোজেক্টের `settings.py` ফাইলের একদম নিচে এই ব্লকটি যুক্ত করুন:

```python
# ============================================
# Production Security Hardening (SSL, Cookies, HSTS, Headers)
# ============================================
# Tell Django that reverse proxies (Nginx / aaPanel / Cloudflare) handle SSL termination
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Set DJANGO_SECURE_SSL_REDIRECT=True in .env only if Nginx/Cloudflare does NOT already redirect HTTP to HTTPS
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', 'False').lower() in ('true', '1', 't')

if not DEBUG:
    # 1. সেশন ও CSRF কুকি বাধ্যতামূলক এনক্রিপ্টেড HTTPS-এ পাঠানো
    SESSION_COOKIE_SECURE = os.environ.get('DJANGO_SESSION_COOKIE_SECURE', 'True').lower() in ('true', '1', 't')
    CSRF_COOKIE_SECURE = os.environ.get('DJANGO_CSRF_COOKIE_SECURE', 'True').lower() in ('true', '1', 't')

    # 2. সেশন হাইজ্যাকিং ও XSS থেকে কুকি চুরি রোধ (JavaScript এক্সেস ব্লক)
    SESSION_COOKIE_HTTPONLY = True

    # 3. ব্রাউজার CSRF অ্যাটাক প্রতিরোধ পলিসি
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'

    # 4. ক্লিকজ্যাকিং (iFrame) ও MIME-টাইপ স্নিফিং প্রতিরোধ
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

    # 5. HTTP Strict Transport Security (HSTS) - ১ বছর মেয়াদি সাবডোমেইন ও প্রিলোড সহ
    if SECURE_SSL_REDIRECT or os.environ.get('DJANGO_ENABLE_HSTS', 'False').lower() in ('true', '1', 't'):
        SECURE_HSTS_SECONDS = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True
```

> 💡 **নোট:** `DEBUG = False` করার সাথে সাথে অবশ্যই একবার `python manage.py collectstatic --noinput` কমান্ডটি চালাবেন, নতুবা CSS/JS ফাইল লোড হতে বিলম্ব হতে পারে।

---

## 🔑 Phase 2: .env ফাইল ও সিক্রেট কি (Secret Key) অটোমেশন

প্রোডাকশন সার্ভারে কখনোই ডিফল্ট বা ইনসিকিউর সিক্রেট কি ব্যবহার করবেন না।

### ১-ক্লিকে ইউনিক ৫০+ ক্যারেক্টারের Secret Key জেনারেট ও সেভ করার কমান্ড:
```bash
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))") && \
sed -i "s/^DJANGO_SECRET_KEY=.*/DJANGO_SECRET_KEY=$NEW_KEY/" .env && \
echo "✅ New 50+ char cryptographic Secret Key generated & updated!"
```

### প্রোডাকশন `.env` এর স্ট্যান্ডার্ড স্ট্রাকচার:
```ini
DJANGO_SECRET_KEY=k8dF92_aBcXyz...
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=pickpickles.xyz,www.pickpickles.xyz,127.0.0.1,localhost
DJANGO_TIME_ZONE=Asia/Dhaka

# PostgreSQL Database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=pickpickles_db
DB_USER=pickpickles_user
DB_PASSWORD=your_strong_password
DB_HOST=127.0.0.1
DB_PORT=5432
```

---

## 🌐 Phase 3: Nginx সার্ভার ব্লক ও সিকিউরিটি কনফিগারেশন

aaPanel বা VPS-এর Nginx কনফিগারেশন ফাইলে নিচের স্ট্যান্ডার্ড রুলগুলো ব্যবহার করুন (পাথ আপনার প্রজেক্ট অনুযায়ী মিলিয়ে নিন):

```nginx
server {
    listen 80;
    server_name pickpickles.xyz www.pickpickles.xyz;
    root /www/wwwroot/pickpickles;

    # ১. ফাইল আপলোড সাইজ ও Nginx ভার্সন হাইড (হ্যাকারদের থেকে তথ্য গোপন)
    client_max_body_size 50M;
    server_tokens off;

    # ২. Gzip হাই-স্পিড কম্প্রেশন (সাইট সুপার-ফাস্ট লোড হওয়ার জন্য)
    gzip on;
    gzip_disable "msie6";
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_buffers 16 8k;
    gzip_types text/plain text/css text/javascript text/xml application/json application/javascript application/x-javascript application/xml application/xml+rss application/xhtml+xml image/svg+xml;

    # ৩. Static Files সরাসরি Nginx সার্ভ করবে (১ বছর ব্রাউজার ক্যাশিং)
    location /static/ {
        alias /www/wwwroot/pickpickles/staticfiles/;
        expires 365d;
        add_header Cache-Control "public, max-age=31536000, immutable";
        access_log off;
    }

    # ৪. Media Files সরাসরি Nginx সার্ভ করবে (৩০ দিন ক্যাশিং)
    location /media/ {
        alias /www/wwwroot/pickpickles/media/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000";
        access_log off;
    }

    # ৫. অতি সংবেদনশীল ফাইল ব্লক (.env, .git, requirements.txt, ইত্যাদি)
    location ~* (\.user.ini|\.htaccess|\.htpasswd|\.env.*|\.git.*|README\.md|requirements\.txt)$ {
        return 404;
    }

    # ৬. SSL সার্টিফিকেটের চ্যালেঞ্জ পাথ
    location /.well-known/ {
        root /www/wwwroot/java_node_ssl;
    }

    # ৭. Django Python ব্যাকএন্ড রিভার্স প্রক্সি
    location / {
        proxy_pass http://127.0.0.1:8089; # aaPanel Python Project Manager Port
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 86400s;
        proxy_send_timeout 60s;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    access_log  /www/wwwlogs/pickpickles.xyz.log;
    error_log  /www/wwwlogs/pickpickles.xyz.error.log;
}
```

---

## 🔒 Phase 4: VPS ফায়ারওয়াল ও ওএস (Linux / aaPanel) নিরাপদ সিকিউরিটি

> ⚠️ **সাবধানতা:** aaPanel চললে সাধারণ UFW দিয়ে সব ব্লক করলে aaPanel প্যানেল ও প্রজেক্ট পোর্ট বন্ধ হয়ে যায়। তাই নিচের মতো **নিরাপদ পদ্ধতিতে** ফায়ারওয়াল সেট করুন:

### ১. aaPanel-এর পোর্ট জেনে নেওয়া:
টার্মিনালে চালান:
```bash
bt default
```
*(এটি আপনাকে aaPanel-এর লিঙ্ক এবং পোর্ট নম্বর যেমন: 8888 বা 7800 দেখিয়ে দেবে)*

### ২. সঠিক পোর্ট এলাও করে ফায়ারওয়াল অন করা:
```bash
# SSH, HTTP, HTTPS ওপেন
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# aaPanel প্যানেল পোর্ট (bt default এ পাওয়া পোর্ট দিন)
sudo ufw allow 7800/tcp
sudo ufw allow 8888/tcp

# aaPanel Python প্রজেক্ট পোর্ট (যেমন: 8089)
sudo ufw allow 8089/tcp

# এরপর ফায়ারওয়াল সক্রিয় করুন
sudo ufw enable
```

> 💡 **বিকল্প (বেস্ট প্র্যাকটিস):** aaPanel ড্যাশবোর্ডের **Security** মেনু ব্যবহার করে ফায়ারওয়াল ও পোর্ট ম্যানেজ করা সবচেয়ে সহজ এবং নিরাপদ।

---

## 🗄️ Phase 5: PostgreSQL ডাটাবেজ সুরক্ষা ও অটো-ব্যাকআপ (Cron Job)

সার্ভার ক্র্যাশ বা ডাটা হারানোর ঝুঁকি এড়াতে প্রতিদিন স্বয়ংক্রিয় ব্যাকআপের জন্য:

1. টার্মিনালে রান করুন:
   ```bash
   crontab -e
   ```
2. ফাইলের শেষে এই লাইনটি যোগ করে সেভ করুন (প্রতিদিন রাত ৩টায় ডাটাবেজের জিপ ব্যাকআপ জমা হবে):
   ```bash
   0 3 * * * pg_dump -U postgres pickpickles_db | gzip > /var/backups/db_backup_$(date +\%F).sql.gz
   ```

---

## ✅ Phase 6: সিকিউরিটি টেস্ট ও ভেরিফিকেশন কমান্ড

সবকিছু ঠিকমতো কাজ করছে কিনা পরীক্ষা করার জন্য:

```bash
# ১. Django ডেপ্লয়মেন্ট সিকিউরিটি অডিট চেক
python manage.py check --deploy

# ২. Nginx সিনট্যাক্স ঠিক আছে কিনা চেক
sudo nginx -t

# ৩. HTTPS রেসপন্স হেডার ও স্পিড চেক
curl -o /dev/null -s -w 'Connect: %{time_connect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n' https://pickpickles.xyz/
```

---

## ☁️ Phase 7: Cloudflare CDN, WAF ও DDoS সুরক্ষা সেটআপ

ক্লাউডফ্লেয়ার যুক্ত করলে আপনার VPS সার্ভারের আসল IP গোপন থাকবে এবং স্পিড অনেক গুণ বৃদ্ধি পাবে:

### ক্লাউডফ্লেয়ারের আবশ্যিক সেটিংস:
| মেনু / ট্যাব | সেটিংয়ের নাম | কী সিলেক্ট করবেন | কেন দরকার? |
|---|---|---|---|
| **SSL/TLS** | Encryption Mode | **Full** অথবা **Full (Strict)** | ডিয়াঙ্গোর রিডাইরেক্ট লুপ ও স্লো হওয়া রোধে (কখনই Flexible দিবেন না) |
| **SSL/TLS -> Edge Certificates** | Always Use HTTPS | **ON** | বাধ্যতামূলক এনক্রিপশন |
| **Speed -> Optimization** | Brotli Compression | **ON** | Gzip-এর চেয়ে ২০% দ্রুত কম্প্রেশন |
| **Security -> Bots** | Bot Fight Mode | **ON** | ক্ষতিকর স্প্যাম বট ও ফেইক রিকোয়েস্ট ব্লক |

---

## 🚨 Phase 8: ট্রাবলশুটিং (সাইট বা aaPanel স্লো হলে করণীয়)

যদি কখনো সিকিউরিটি দেওয়ার পর aaPanel বা সাইট খুলতে দেরি হয় বা হ্যাং হয়ে যায়:

### ১. ফায়ারওয়াল সমস্যা সমাধান:
```bash
# ফায়ারওয়াল সাময়িকভাবে রিসেট করে সব পোর্ট আনলক করতে
sudo ufw disable
sudo ufw reset -y
```

### ২. aaPanel ক্যাশ ও রিস্টার্ট:
```bash
bt 9      # প্যানেল ক্যাশ ক্লিয়ার
bt 1      # প্যানেল রিস্টার্ট
```

### ৩. স্ট্যাটিক ফাইল রিফ্রেশ:
```bash
source /www/server/pyporject_evn/pickpickles_env/bin/activate
python manage.py collectstatic --noinput
sudo systemctl restart nginx
```
