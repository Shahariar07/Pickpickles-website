#!/usr/bin/env bash
# ==============================================================================
# Pickpickles Virtual Environment Setup Script (Linux / macOS / Git Bash)
# ==============================================================================

set -e

echo "[1/5] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 could not be found. Please install Python 3.10+."
    exit 1
fi

echo "[2/5] Creating virtual environment (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Virtual environment created at .venv/"
else
    echo "Virtual environment .venv already exists."
fi

echo "[3/5] Activating virtual environment and upgrading pip..."
source .venv/bin/activate || source .venv/Scripts/activate
python -m pip install --upgrade pip

echo "[4/5] Installing dependencies..."
pip install -r requirements.txt

echo "[5/5] Applying migrations..."
python manage.py migrate

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

echo "=============================================================================="
echo " Setup Complete!"
echo ""
echo " To run the project:"
echo "   1. Activate environment:  source .venv/bin/activate (or source .venv/Scripts/activate)"
echo "   2. Seed demo data:        python seed_data.py"
echo "   3. Run server:            python manage.py runserver"
echo "=============================================================================="
