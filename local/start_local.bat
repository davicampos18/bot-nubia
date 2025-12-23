@echo off
cd /d "%~dp0"
echo Iniciando NUBIA Local...

:: 1. Inicia a API Python usando a venv
start "NUBIA Brain" cmd /k ".venv\Scripts\python.exe main.py"

echo Aguardando a API Python iniciar...

:wait_loop
powershell -command ^
  "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8000/docs' -UseBasicParsing -TimeoutSec 1) > $null; exit 0 } catch { exit 1 }"

if %ERRORLEVEL% NEQ 0 (
    timeout /t 1 >nul
    goto wait_loop
)

echo API Python ativa! Iniciando bot WhatsApp...

:: 2. Inicia o Bot WhatsApp
start "WhatsApp Bot" cmd /k "node bot.js"

echo Tudo pronto!
pause