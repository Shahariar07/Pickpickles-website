# 🥒 Pickpickles — Artisan Pickle E-Commerce & Operations Platform

A full-featured Django e-commerce platform and operational dashboard for **Pickpickles**, handcrafted pickles in Dhaka, Bangladesh.

---

## 🚀 Virtual Environment Setup Guide

### 1. Prerequisites
- **Python 3.10+** (Python 3.10, 3.11, 3.12, 3.13 supported)
- **pip** and **git**

---

### 2. Automated One-Step Setup (Recommended)

#### On Windows (Command Prompt / Double Click):
Double-click `setup_env.bat` or run:
```cmd
setup_env.bat
```

#### On Windows (PowerShell):
```powershell
.\setup_env.ps1
```

#### On macOS / Linux / Git Bash:
```bash
chmod +x setup_env.sh
./setup_env.sh
```

---

### 3. Manual Virtual Environment Setup

#### Step 1: Create a Virtual Environment
```bash
# Windows / macOS / Linux
python -m venv .venv
```

#### Step 2: Activate the Virtual Environment
- **Windows (Command Prompt):**
  ```cmd
  .venv\Scripts\activate
  ```
- **Windows (PowerShell):**
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
- **macOS / Linux / Git Bash:**
  ```bash
  source .venv/bin/activate
  ```

*(Once activated, your terminal prompt will show `(.venv)`).*

#### Step 3: Upgrade pip and Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### Step 4: Configure Environment Variables (Optional)
Copy the example environment configuration:
```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

#### Step 5: Run Database Migrations
```bash
python manage.py migrate
```

#### Step 6: Seed Sample / Initial Data (Optional)
Populates categories, gourmet pickle products, mock orders, and superuser:
```bash
python seed_data.py
```

---

### 4. Running the Development Server

Activate your environment and run:
```bash
python manage.py runserver
```
Or simply double-click `run_server.bat` on Windows.

Visit the application:
- **Storefront**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Operations Dashboard**: [http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)
- **Django Admin**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

#### Default Superuser & Staff Credentials (from `seed_data.py`):
- **Username**: `admin`
- **Password**: `pickles123`

---

## 📦 Project Structure

```
Pickpickles website/
├── .venv/                   # Virtual environment (ignored by Git)
├── .gitignore              # Git ignore rules for venv, caches, media
├── .env.example            # Environment variables template
├── requirements.txt        # Pinned Python package dependencies
├── setup_env.bat           # 1-click Windows CMD setup script
├── setup_env.ps1           # 1-click PowerShell setup script
├── setup_env.sh            # 1-click Linux/macOS setup script
├── run_server.bat          # 1-click server launcher
├── manage.py               # Django CLI management utility
├── seed_data.py            # Sample data seeding script
├── pickpickles_project/    # Project root config & settings
├── store/                  # Storefront app (catalog, cart, orders)
├── dashboard/              # Operations & kitchen order management
├── static/                 # CSS, JavaScript, and branding assets
├── media/                  # Product and uploaded media
└── templates/              # HTML templates (storefront + dashboard)
```

---

## 🛠️ Deactivating the Virtual Environment
When you are done working on the project, run:
```bash
deactivate
```
