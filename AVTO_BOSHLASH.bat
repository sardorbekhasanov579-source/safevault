@echo off
chcp 65001 >nul
cd /d "%~dp0"
schtasks /create /tn "SafeVault server" /tr "\"%~dp0ISHGA_TUSHIR.bat\"" /sc onlogon /f
if errorlevel 1 (
  echo [XATO] Vazifa yaratilmadi. Bu faylni o'ng tugma bilan bosib Administrator sifatida ishga tushiring.
) else (
  echo.
  echo TAYYOR: server endi Windows'ga kirganingizda o'zi ishga tushadi.
  echo O'chirish uchun: schtasks /delete /tn "SafeVault server" /f
)
pause
