# ==============================================================================
# Pickpickles Virtual Environment Setup Script (PowerShell)
# ==============================================================================

Write-Host "[1/5] Checking Python installation..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python is not found in PATH. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

Write-Host "[2/5] Creating virtual environment (.venv)..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "Virtual environment created at .venv\" -ForegroundColor Green
} else {
    Write-Host "Virtual environment .venv already exists." -ForegroundColor Yellow
}

Write-Host "[3/5] Activating virtual environment and upgrading pip..." -ForegroundColor Cyan
& ".\.venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip

Write-Host "[4/5] Installing project dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "[5/5] Applying database migrations..." -ForegroundColor Cyan
python manage.py migrate

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env file from .env.example" -ForegroundColor Green
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host " Setup Complete!" -ForegroundColor Green
Write-Host ""
Write-Host " To start developing in PowerShell:" -ForegroundColor White
Write-Host "   1. Activate environment:  .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "   2. Seed demo data (opt):  python seed_data.py" -ForegroundColor Yellow
Write-Host "   3. Run server:            python manage.py runserver" -ForegroundColor Yellow
Write-Host "==============================================================================" -ForegroundColor Green
