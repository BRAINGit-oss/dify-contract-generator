@echo off
setlocal
cd /d "%~dp0"
if /I "%~1"=="check" goto check
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please run: python -m venv .venv
  exit /b 1
)
set "AUTO_CLOUDFLARED=true"
set "TUNNEL_TARGET_URL=http://127.0.0.1:19000"
set "PUBLIC_BASE_URL="
echo [INFO] Starting local service at http://127.0.0.1:19000
echo [INFO] Cloudflared quick tunnel will be started automatically by app.py
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 19000
exit /b %errorlevel%

:check
if exist ".venv\Scripts\python.exe" (
  echo OK
  exit /b 0
)
echo MISSING_VENV
exit /b 1
