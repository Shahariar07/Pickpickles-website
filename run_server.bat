@echo off
REM ==============================================================================
REM Quick Server Start Script for Pickpickles
REM ==============================================================================

if exist ".venv\Scripts\python.exe" (
    echo Starting Pickpickles Django Server via .venv...
    ".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
) else if exist "venv\Scripts\python.exe" (
    echo Starting Pickpickles Django Server via venv...
    "venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
) else (
    echo Starting Pickpickles Django Server...
    python manage.py runserver 127.0.0.1:8000
)
pause
