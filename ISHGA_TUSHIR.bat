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

set SAFEVAULT_DATA=C:\SafeVaultData
set SAFEVAULT_HOST=0.0.0.0
set SAFEVAULT_PORT=8080

echo ================================================
echo   SafeVault server v0.1
echo   Kompyuteringizning tarmoq manzili (IPv4) quyida:
ipconfig | findstr /c:"IPv4"
echo   Telefon ilovasiga shuni kiriting: http://IPv4-manzil:%SAFEVAULT_PORT%
echo.
echo   Tasdiqlash kodlari (SMS/email o'rniga) shu oynada va
echo   C:\SafeVaultData\outbox.log faylida ko'rinadi.
echo   To'xtatish: Ctrl+C
echo ================================================
echo.

cd server
python -m safevault_server
pause
