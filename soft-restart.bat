@echo off
cd /d "%~dp0"
echo ==============================
echo   Claude Gateway - Soft Restart
echo   Graceful: no force-kill, lets uvicorn shutdown cleanly
echo ==============================
echo.

echo [1/4] Gracefully shutting down (WM_CLOSE, no /F)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    echo   Asking PID %%a to close...
    taskkill /PID %%a >nul 2>&1
)
echo   Signal sent. Waiting for clean shutdown...

echo.
echo [2/4] Waiting up to 5s for port 8080 to release...
set /a wait_count=0
:wait_graceful
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":8080.*LISTENING" >nul 2>&1
if errorlevel 1 goto port_free_graceful
set /a wait_count+=1
if %wait_count% lss 5 goto wait_graceful

echo   Port still busy — forcing with /F...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    echo   Force-killing PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo.
echo [3/4] Waiting for port release...
:wait_force
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":8080.*LISTENING" >nul 2>&1
if not errorlevel 1 goto wait_force

:port_free_graceful
echo   Port free.
echo.
echo [4/4] Starting server...
python -m uvicorn main:app --host 0.0.0.0 --port 8080
pause
