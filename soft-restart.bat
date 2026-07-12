@echo off
cd /d "%~dp0"
echo ==============================
echo   Claude Gateway - Soft Restart
echo   Graceful: no force-kill, lets uvicorn shutdown cleanly
echo ==============================
echo.

echo [1/3] Gracefully shutting down (WM_CLOSE, no /F)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    echo   Asking PID %%a to close...
    taskkill /PID %%a >nul 2>&1
)
echo   Signal sent.

echo.
echo [2/3] Waiting for port 8080 to release...
:wait
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":8080.*LISTENING" >nul 2>&1
if not errorlevel 1 goto wait
echo   Port free.

echo.
echo [3/3] Starting server...
python -m uvicorn main:app --host 0.0.0.0 --port 8080
pause
