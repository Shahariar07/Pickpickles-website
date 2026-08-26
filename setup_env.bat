@echo off
REM ==============================================================================
REM Pickpickles Virtual Environment Setup Script (Windows CMD)
REM ==============================================================================

echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in PATH. Please install Python 3.10+ from python.org.
    pause
    exit /b 1
)

echo [2/5] Creating virtual environment (.venv)...
if not exist ".venv" (
    python -m venv .venv
    echo Virtual environment created successfully at .venv\
) else (
    echo Virtual environment .venv already exists.
)

echo [3/5] Activating virtual environment and upgrading pip...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo [4/5] Installing project dependencies from requirements.txt...
pip install -r requirements.txt

echo [5/5] Applying database migrations...
python manage.py migrate

if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env
        echo Created .env from .env.example
    )
)

echo ==============================================================================
echo Setup Complete!
echo.
echo To start developing:
echo   1. Activate environment:  .venv\Scripts\activate
echo   2. Seed demo data (optional): python seed_data.py
echo   3. Run server:            python manage.py runserver
echo ==============================================================================
pause
