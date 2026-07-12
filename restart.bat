@echo off
cd /d "%~dp0"
echo ==============================
echo   Claude Gateway - Restart
echo ==============================
echo.

echo [1/4] Stopping server...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo   Done.

echo.
echo [2/4] Clearing cache...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
del /s /q *.pyc 2>nul
echo   Done.

echo.
echo [3/4] Waiting...
timeout /t 2 /nobreak >nul

echo.
echo [4/4] Starting server...
python -m uvicorn main:app --host 0.0.0.0 --port 8080
pause
