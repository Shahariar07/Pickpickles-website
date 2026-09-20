# 🛡️ Universal Production Security & Deployment Master Guide
*(Django + PostgreSQL + aaPanel / Nginx / Linux VPS)*

এই গাইডটি অনুসরণ করে আপনি যেকোনো **Django ই-কমার্স বা ওয়েব অ্যাপ্লিকেশনকে** সর্বোচ্চ লেভেলের প্রোডাকশন সিকিউরিটি (OWASP Top 10 Standard - **Score 10/10**) প্রদান করতে পারবেন।

---

## 📑 সূচিপত্র
1. [Phase 1: Django Settings-এ প্রোডাকশন সিকিউরিটি](#-phase-1-django-settings-এ-প্রোডাকশন-সিকিউরিটি)
2. [Phase 2: .env ফাইল ও সিক্রেট কি (Secret Key) অটোমেশন](#-phase-2-env-ফাইল-ও-সিক্রেট-কি-secret-key-অটোমেশন)
3. [Phase 3: Nginx সার্ভার ব্লক ও সিকিউরিটি কনফিগারেশন](#-phase-3-nginx-সার্ভার-ব্লক-ও-সিকিউরিটি-কনফিগারেশন)
4. [Phase 4: VPS ফায়ারওয়াল ও ওএস (Linux) সিকিউরিটি](#-phase-4-vps-ফায়ারওয়াল-ও-ওএস-linux-সিকিউরিটি)
5. [Phase 5: PostgreSQL ডাটাবেজ সুরক্ষা ও অটো-ব্যাকআপ (Cron Job)](#-phase-5-postgresql-ডাটাবেজ-সুরক্ষা-ও-অটো-ব্যাকআপ-cron-job)
6. [Phase 6: সিকিউরিটি টেস্ট ও ভেরিফিকেশন কমান্ড](#-phase-6-সিকিউরিটি-টেস্ট-ও-ভেরিফিকেশন-কমান্ড)

---

## 🛡️ Phase 1: Django Settings-এ প্রোডাকশন সিকিউরিটি

আপনার প্রোজেক্টের `settings.py` ফাইলের একদম নিচে এই ব্লকটি যুক্ত করুন:

```python
# ============================================
# Production Security Hardening (SSL, Cookies, HSTS, Headers)
# ============================================
if not DEBUG:
    # 1. Nginx Reverse Proxy SSL প্রটোকল শনাক্তকরণ
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # 2. নন-HTTPS ট্রাফিককে স্বয়ংক্রিয়ভাবে HTTPS-এ রিডাইরেক্ট
    SECURE_SSL_REDIRECT = True

    # 3. সেশন ও CSRF কুকি বাধ্যতামূলক এনক্রিপ্টেড HTTPS-এ পাঠানো
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # 4. সেশন হাইজ্যাকিং ও XSS থেকে কুকি চুরি রোধ (JavaScript এক্সেস ব্লক)
    SESSION_COOKIE_HTTPONLY = True

    # 5. ব্রাউজার CSRF অ্যাটাক প্রতিরোধ পলিসি
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'

    # 6. ক্লিকজ্যাকিং (iFrame) ও MIME-টাইপ স্নিফিং প্রতিরোধ
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

    # 7. HTTP Strict Transport Security (HSTS) - ১ বছর মেয়াদি সাবডোমেইন ও প্রিলোড সহ
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
```

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
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,127.0.0.1,localhost
DJANGO_TIME_ZONE=Asia/Dhaka

# PostgreSQL Database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_strong_password
DB_HOST=127.0.0.1
DB_PORT=5432
```

---

## 🌐 Phase 3: Nginx সার্ভার ব্লক ও সিকিউরিটি কনফিগারেশন

aaPanel বা VPS-এর Nginx কনফিগারেশন ফাইলে নিচের স্ট্যান্ডার্ড রুলগুলো ব্যবহার করুন:

```nginx
server {
    listen 80;
    server_name www.yourdomain.com yourdomain.com;
    root /www/wwwroot/your_project_folder;

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
        alias /www/wwwroot/your_project_folder/staticfiles/;
        expires 365d;
        add_header Cache-Control "public, max-age=31536000, immutable";
        access_log off;
    }

    # ৪. Media Files সরাসরি Nginx সার্ভ করবে (৩০ দিন ক্যাশিং)
    location /media/ {
        alias /www/wwwroot/your_project_folder/media/;
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
        proxy_pass http://127.0.0.1:8089; # আপনার প্রোজেক্টের পোর্ট
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

    access_log  /www/wwwlogs/yourdomain.log;
    error_log  /www/wwwlogs/yourdomain.error.log;
}
```

---

## 🔒 Phase 4: VPS ফায়ারওয়াল ও ওএস (Linux) সিকিউরিটি

সার্ভারের টার্মিনালে এই কমান্ডগুলো চালিয়ে সার্ভারকে ব্রুট-ফোর্স অ্যাটাক থেকে নিরাপদ রাখুন:

```bash
# ১. UFW ফায়ারওয়াল অন করা (শুধুমাত্র SSH, HTTP, HTTPS ওপেন থাকবে)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# ২. Fail2ban ইনস্টল (বারবার ভুল পাসওয়ার্ড দিলে হ্যাকারের IP অটো ব্লক হবে)
sudo apt update && sudo apt install fail2ban -y
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

---

## 🗄️ Phase 5: PostgreSQL ডাটাবেজ সুরক্ষা ও অটো-ব্যাকআপ (Cron Job)

সার্ভার ক্র্যাশ বা ডাটা হারানোর ঝুঁকি এড়াতে প্রতিদিন স্বয়ংক্রিয় ব্যাকআপের জন্য:

1. টার্মিনালে রান করুন:
   ```bash
   crontab -e
   ```
2. ফাইলের শেষে এই লাইনটি যোগ করে সেভ করুন (প্রতিদিন রাত ৩টায় ডাটাবেজের জিপ ব্যাকআপ জমা হবে):
   ```bash
   0 3 * * * pg_dump -U postgres your_db_name | gzip > /var/backups/db_backup_$(date +\%F).sql.gz
   ```

---

## ✅ Phase 6: সিকিউরিটি টেস্ট ও ভেরিফিকেশন কমান্ড

সবকিছু ঠিকমতো কাজ করছে কিনা পরীক্ষা করার জন্য:

```bash
# ১. Django ডেপ্লয়মেন্ট সিকিউরিটি অডিট চেক
python manage.py check --deploy

# ২. ডিয়াঙ্গোতে সিক্রেট কি সঠিকভাবে লোড হচ্ছে কিনা যাচাই
python manage.py shell -c "from django.conf import settings; print('Loaded Secret Key length:', len(settings.SECRET_KEY))"

# ৩. Nginx সিনট্যাক্স ঠিক আছে কিনা চেক
sudo nginx -t

# ৪. HTTPS রেসপন্স হেডার চেক (HSTS, X-Frame-Options সক্রিয় আছে কিনা)
curl -I https://yourdomain.com
```

---

## ☁️ Phase 7: Cloudflare CDN, WAF ও DDoS সুরক্ষা সেটআপ

ক্লাউডফ্লেয়ার যুক্ত করলে আপনার VPS সার্ভারের আসল IP গোপন থাকবে এবং ২x স্পিড বৃদ্ধি পাবে:

### ১. ডোমেইন নেমসার্ভার পরিবর্তন:
- [Cloudflare](https://dash.cloudflare.com/) এ সাইনআপ করে আপনার ডোমেইন যুক্ত করুন।
- ডোমেইন প্রোভাইডার থেকে নেমসার্ভার ক্লাউডফ্লেয়ারের নেমসার্ভারে পয়েন্ট করুন।

### ২. ক্লাউডফ্লেয়ারের আবশ্যিক ৫টি সেটিংস:
| মেনু / ট্যাব | সেটিংয়ের নাম | কী সিলেক্ট করবেন | কেন দরকার? |
|---|---|---|---|
| **SSL/TLS** | Encryption Mode | **Full (Strict)** | ডিয়াঙ্গোর রিডাইরেক্ট লুপ ইরর প্রতিরোধে |
| **SSL/TLS -> Edge Certificates** | Always Use HTTPS | **ON** | বাধ্যতামূলক এনক্রিপশন |
| **Speed -> Optimization** | Brotli Compression | **ON** | Gzip-এর চেয়ে ২০% দ্রুত কম্প্রেশন |
| **Speed -> Optimization** | Auto Minify | **JS, CSS, HTML (Tick all)** | কোড সাইজ ছোট করে সুপার ফাস্ট লোডিং |
| **Security -> Bots** | Bot Fight Mode | **ON** | ক্ষতিকর স্প্যাম বট ও ফেইক রিকোয়েস্ট ব্লক |

### ৩. Nginx-এ ক্লাউডফ্লেয়ারের আসল কাস্টমার IP রিড করার কনফিগারেশন:
কাস্টমারের আসল IP ট্রেস করতে Nginx-এর `http { ... }` ব্লকে বা সার্ভার ফাইলে এটি যুক্ত করুন:
```nginx
# Restore Real Visitor IP from Cloudflare
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
real_ip_header CF-Connecting-IP;
```

---

> 💡 **টিপ:** ভবিষ্যতে নতুন কোনো ডিয়াঙ্গো প্রোজেক্ট লাইভ করার সময় এই গাইডের প্রতিটি ধাপ পর্যায়ক্রমে অনুসরণ করলে আপনার ওয়েবসাইট শুরু থেকেই সম্পূর্ণ সুরক্ষিত ও হ্যাক-প্রুফ থাকবে।
