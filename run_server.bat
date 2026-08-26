@echo off
REM ==============================================================================
REM Quick Server Start Script
REM ==============================================================================

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo Starting Pickpickles Django Server...
python manage.py runserver 127.0.0.1:8000
pause
