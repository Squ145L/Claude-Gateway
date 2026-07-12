@echo off
cd /d "%~dp0"
echo ==============================
echo   Claude Gateway - Clean
echo ==============================
echo.

echo [1/3] Killing uvicorn processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    echo   Killing PID %%a on port 8080
    taskkill /F /PID %%a >nul 2>&1
)
echo   Done.

echo.
echo [2/3] Clearing Python cache...
for /d /r . %%d in (__pycache__) do @if exist "%%d" (
    echo   Removing %%d
    rmdir /s /q "%%d" 2>nul
)
del /s /q *.pyc 2>nul
echo   Done.

echo.
echo [3/3] Ready to restart.
echo   Run: run.bat
echo ==============================
