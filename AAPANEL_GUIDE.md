# aaPanel Deployment & Terminal Guide for Pickpickles

## 📌 Virtual Environment Details
- **Venv Path:** `/www/server/pyporject_evn/pickpickles_env/bin`
- **Python Executable:** `/www/server/pyporject_evn/pickpickles_env/bin/python`
- **Pip Executable:** `/www/server/pyporject_evn/pickpickles_env/bin/pip`

---

## ⚡ 1. Virtual Environment Activate করার কমান্ড
সার্ভার টার্মিনালে ঢুকে virtual environment activate করতে নিচের কমান্ডটি রান করুন:

```bash
source /www/server/pyporject_evn/pickpickles_env/bin/activate
```

*(এরপর টার্মিনাল প্রম্পটে `(pickpickles_env)` দেখতে পাবেন)*

---

## 🔄 2. সহজে কোড আপডেট ও মাইগ্রেশন চালানোর কমান্ড
প্রজেক্ট ফোল্ডারে গিয়ে এক ক্লিকে আপডেট চালাতে:

```bash
chmod +x deploy/aapanel_update.sh
./deploy/aapanel_update.sh
```

অথবা ম্যানুয়ালি রান করতে চাইলে:

```bash
# ১. প্রজেক্ট ডিরেক্টরিতে যান
cd /www/wwwroot/your_project_folder

# ২. Venv Activate করুন
source /www/server/pyporject_evn/pickpickles_env/bin/activate

# ৩. লেটেস্ট কোড পুল করুন
git pull

# ৪. ডিপেনডেন্সি ও মাইগ্রেশন রান করুন
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput

# ৫. পারমিশন ঠিক রাখুন
chown -R www:www .
chmod -R 775 media
chmod 664 db.sqlite3
```

---

## 🚀 3. aaPanel-এ প্রজেক্ট রিস্টার্ট
- aaPanel ড্যাশবোর্ডে যান।
- **Python Project Manager** এ ঢুকুন।
- **pickpickles** প্রজেক্টের ডানপাশে **Restart** বাটনে ক্লিক করুন।
