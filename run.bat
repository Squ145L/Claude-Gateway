@echo off
cd /d "%~dp0"
echo ==============================
echo   Claude Gateway
echo ==============================
echo.
echo Starting server on http://0.0.0.0:8080
echo Press Ctrl+C to stop
echo.

:loop
echo [%date% %time%] Killing old processes on port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    echo   Killing PID %%a
    taskkill /f /pid %%a 2>nul
)
timeout /t 1 /nobreak >nul
echo [%date% %time%] Starting...
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --log-level info
echo [%date% %time%] Server stopped (exit code: %ERRORLEVEL%). Restarting in 2s...
timeout /t 2 /nobreak >nul
goto loop
