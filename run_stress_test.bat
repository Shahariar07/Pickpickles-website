@echo off
title Pickpickles - 1000 Concurrent Users Stress Test
color 0A
cls

echo =====================================================================
echo          PICKPICKLES WEBSITE - 1000 USERS STRESS TESTING TOOL
echo =====================================================================
echo.

set /p TARGET_URL="Enter Website URL (Press Enter for https://pickpickles.xyz/): "
if "%TARGET_URL%"=="" set TARGET_URL=https://pickpickles.xyz/

set /p USERS_COUNT="Enter Concurrent Users Count (Press Enter for 1000): "
if "%USERS_COUNT%"=="" set USERS_COUNT=1000

echo.
echo [INFO] Target URL: %TARGET_URL%
echo [INFO] Simulating: %USERS_COUNT% concurrent requests...
echo.

python stress_test.py %TARGET_URL% %USERS_COUNT%

echo.
echo =====================================================================
echo Stress Test Finished!
echo =====================================================================
pause
