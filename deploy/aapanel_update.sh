#!/bin/bash
# ==========================================================
# aaPanel 1-Click Update Script for Pickpickles
# ==========================================================
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_BIN="/www/server/pyporject_evn/pickpickles_env/bin"

# Fallback if spelling is pyproject_evn
if [ ! -f "$VENV_BIN/python" ]; then
    if [ -f "/www/server/pyproject_evn/pickpickles_env/bin/python" ]; then
        VENV_BIN="/www/server/pyproject_evn/pickpickles_env/bin"
    fi
fi

echo ">>> [1/5] Navigating to project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"

echo ">>> [2/5] Pulling latest updates from Git..."
git pull origin main || git pull

echo ">>> [3/5] Installing/Updating requirements..."
"$VENV_BIN/pip" install -r requirements.txt

echo ">>> [4/5] Running database migrations..."
"$VENV_BIN/python" manage.py migrate

echo ">>> [5/5] Collecting static files..."
"$VENV_BIN/python" manage.py collectstatic --noinput

# Fix permissions for media and database in aaPanel (www user)
chown -R www:www "$PROJECT_DIR" 2>/dev/null || true
chmod -R 775 "$PROJECT_DIR/media" 2>/dev/null || true
chmod 664 "$PROJECT_DIR/db.sqlite3" 2>/dev/null || true

echo "=========================================================="
echo " Pickpickles updated successfully in aaPanel!"
echo " Now in aaPanel -> Python Project Manager -> Click 'Restart' on pickpickles project."
echo "=========================================================="
