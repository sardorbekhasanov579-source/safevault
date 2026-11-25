@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [XATO] Python topilmadi. python.org saytidan Python 3.11 yoki yangiroq o'rnating
  echo        va o'rnatishda "Add python.exe to PATH" katagini belgilang.
  pause
  exit /b 1
)

python -c "import cryptography" >nul 2>nul
if errorlevel 1 (
  echo Kerakli paket o'rnatilmoqda: cryptography
  python -m pip install cryptography
  if errorlevel 1 (
    echo [XATO] Paketni o'rnatib bo'lmadi. Internetni tekshiring.
    pause
    exit /b 1
  )
)

echo ================================================
echo   SafeVault Telegram bot v0.3
echo   Birinchi marta savollar beriladi. To'xtatish: Ctrl+C
echo ================================================
echo.

cd agent
set PYTHONPATH=%CD%;%CD%\..\client
python -m safevault_agent
pause
