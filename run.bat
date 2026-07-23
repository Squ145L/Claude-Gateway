@echo off
cd /d "%~dp0"
set PATH=%PATH%;%APPDATA%\npm
echo ==============================
echo   Claude Gateway
echo ==============================
echo.
echo Listening on http://0.0.0.0:8080
echo Press Ctrl+C to stop
echo.

:loop
echo [%date% %time%] Checking port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    echo   Killing old process PID %%a
    taskkill /f /pid %%a 2>nul
)
:wait_port
netstat -ano | findstr ":8080.*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo   Port 8080 in use, waiting...
    timeout /t 2 /nobreak >nul
    goto wait_port
)
echo [%date% %time%] Port free. Starting...
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --log-level info
set EXITCODE=%ERRORLEVEL%
echo [%date% %time%] Server stopped (exit code: %EXITCODE%)
if %EXITCODE% neq 0 (
    echo.
    echo Server crashed. Press any key to restart...
    pause >nul
)
timeout /t 2 /nobreak >nul
goto loop
