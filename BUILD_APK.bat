@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where flutter >nul 2>nul
if errorlevel 1 (
  echo [XATO] Flutter topilmadi. docs.flutter.dev/get-started/install/windows saytidagi
  echo        ko'rsatma bo'yicha Flutter va Android Studio o'rnating, keyin
  echo        "flutter doctor --android-licenses" buyrug'ini bajaring.
  pause & exit /b 1
)
where python >nul 2>nul
if errorlevel 1 ( echo [XATO] Python topilmadi. & pause & exit /b 1 )

set PROJ=C:\safevault_build\safevault_app
if not exist "%PROJ%\pubspec.yaml" (
  echo [1/5] Flutter loyihasi yaratilmoqda: C:\safevault_build, OneDrive tashqarisida...
  call flutter create --org uz.safevault --project-name safevault_app --platforms=android "%PROJ%"
  if errorlevel 1 ( echo [XATO] flutter create bajarilmadi & pause & exit /b 1 )
)

echo [2/5] Kodlar nusxalanmoqda...
if exist "%PROJ%\lib" rmdir /s /q "%PROJ%\lib"
if exist "%PROJ%\test" rmdir /s /q "%PROJ%\test"
xcopy /e /i /y "%~dp0app\lib" "%PROJ%\lib" >nul
xcopy /e /i /y "%~dp0app\test" "%PROJ%\test" >nul
copy /y "%~dp0app\pubspec.yaml" "%PROJ%\pubspec.yaml" >nul
python "%~dp0app\tools\patch_android.py" "%PROJ%"

cd /d "%PROJ%"
echo [3/5] Paketlar yuklanmoqda...
call flutter pub get
if errorlevel 1 ( echo [XATO] flutter pub get bajarilmadi. Yuqoridagi xabarni menga yuboring. & pause & exit /b 1 )

echo [4/5] Shifrlash testlari (Python bilan moslik)...
call flutter test
if errorlevel 1 ( echo [XATO] Testlar o'tmadi. Yuqoridagi xabarni menga yuboring. & pause & exit /b 1 )

echo [5/5] APK yig'ilmoqda (birinchi marta 5-15 daqiqa olishi mumkin)...
call flutter build apk --release
if errorlevel 1 ( echo [XATO] APK yig'ilmadi. Yuqoridagi xabarni menga yuboring. & pause & exit /b 1 )

if not exist "%~dp0dist" mkdir "%~dp0dist"
copy /y "%PROJ%\build\app\outputs\flutter-apk\app-release.apk" "%~dp0dist\SafeVault-v0.1.apk" >nul
echo.
echo TAYYOR: %~dp0dist\SafeVault-v0.1.apk
pause
