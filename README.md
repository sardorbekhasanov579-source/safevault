# SafeVault v0.4 (qisman)

Telefon ma'lumotlarini shifrlab zaxiralash va tiklash tizimi.

## Tuzilma
- `server/safevault_server/` — server (faqat Python standart kutubxonasi; SQLite + diskdagi bloblar)
- `client/safevault_client/` — telefon tomoni mantiqining Python andozasi (shifrlash, kirish, zaxira); Dart/Flutter ilovasi shuni takrorlaydi
- `app/` — Flutter (Android) ilova kodi: `lib/`, Python bilan moslik testi `test/`, `tools/patch_android.py`
- `BUILD_APK.bat` — Windows'da APK yig'ish (Flutter kerak)
- `agent/safevault_agent/` — Telegram bot + AI qidiruv (Gemini 3.5 Flash Lite, kalit bo'lmasa oddiy qidiruv) + joylashuvni ko'rsatish
- `Dockerfile.allinone`, `render.yaml`, `deploy/run_all.py`, `QOLLANMA_BULUT_uz.md` — server + bot bitta konteynerda (VPS yoki Render)
- `BOT_ISHGA_TUSHIR.bat`, `QOLLANMA_BOT_uz.md` — botni ishga tushirish va qo'llanma
- `tests/` — 66 ta test: `python -m pytest tests` (kerak: pytest, cryptography)
- `ISHGA_TUSHIR.bat`, `Dockerfile`, `docker-compose.yml` — ishga tushirish
- `QOLLANMA_uz.md` — foydalanuvchi qo'llanmasi

## Xavfsizlik modeli
Server parol, tiklash kodi va asosiy kalitni (MK) hech qachon ko'rmaydi. MK ni parol va tiklash kodi
alohida o'raydi. Fayl, fayl nomi/turi/sanasi va joylashuv telefonda shifrlanadi. Server faqat hajm,
yuklangan vaqt va takrorlanishni aniqlovchi HMAC belgisini ko'radi.

## Hozirgi holat
Tayyor: hisob + OTP, yangi qurilma (SMS + tiklash kodi), parolni tiklash, bloklash (5 xato -> 15 daq),
shifrlangan ombor, holat, joylashuv. Sinalgan.
v0.1 ilova telefonda sinalgan (ro'yxat, zaxira). v0.2: avtomatik fon zaxirasi (WorkManager) kodi yozilgan, hali telefonda SINALMAGAN. `deploy/` — VPS ga doimiy joylash (Docker + HTTPS + Telegram kodlar).
v0.4: botda kontaktlar, /hammasi (ZIP), boshqa Telegram hisobidan kirish; ilovada qidiruv, toifa filtri, kontaktlar ro'yxati, hammasini yuklab olish (Flutter qismi SINALMAGAN). v0.3: joylashuv (ilova xaritasi + fon yuborish) va Telegram bot kodi yozilgan; bot Python'da sinalgan, Flutter joylashuv qismi va Gemini javobi hali haqiqiy qurilma/kalit bilan SINALMAGAN.
Qolgan: hujjat papkasini kuzatish, hujjat ichidan (OCR) qidiruv, kompyuter agenti (Windows), haqiqiy SMS/email,
bo'lakli (uzilsa davom etadigan) yuklash, HTTPS, Argon2id (hozir scrypt), qurilmalar ro'yxati va chiqarish.
