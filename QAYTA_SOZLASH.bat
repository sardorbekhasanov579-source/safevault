@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [XATO] Python topilmadi. python.org saytidan Python 3.11 yoki yangiroq o'rnating.
  pause
  exit /b 1
)

echo ================================================
echo   SafeVault bot: qayta sozlash
echo   Telefon, parol, bot tokeni va PIN qaytadan so'raladi.
echo   Oxirida chiqqan /ulash kodini botga yuboring.
echo ================================================
echo.

cd agent
set PYTHONPATH=%CD%;%CD%\..\client
python -m safevault_agent --setup
pause
