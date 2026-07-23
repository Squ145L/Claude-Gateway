@echo off
cd /d "%~dp0"
echo ==============================
echo   Claude Gateway - 更新
echo ==============================
echo.
python services/update.py
