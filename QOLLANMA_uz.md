# SafeVault v0.3 — qisqa qo'llanma

## Nima bor
- **Server** (kompyuterda ishlaydi): hisob, kodlar bilan tasdiqlash, yangi qurilmadan kirish, tiklash kodi, shifrlangan ombor.
- **Telefon ilovasi kodi** (Android): kirish/ro'yxatdan o'tish, tiklash kodi, nimalar zaxiralanishini tanlash, holat, saqlangan fayllarni tiklash, barmoq izi.
- **Telegram bot + AI qidiruv va joylashuv (v0.3):** `QOLLANMA_BOT_uz.md` ga qarang.
- Kompyuter agenti (Windows) keyingi versiyada.

## 1-qadam. Serverni ishga tushirish
1. python.org dan Python 3.11+ o'rnating ("Add python.exe to PATH" ni belgilang).
2. `ISHGA_TUSHIR.bat` ni ikki marta bosing. Oynada kompyuteringiz IPv4 manzili ko'rinadi (masalan 192.168.1.15).
3. Brauzerda `http://localhost:8080/v1/health` ochilsa, server ishlayapti.

## 2-qadam. APK yig'ish (bir marta)
1. Flutter va Android Studio o'rnating (docs.flutter.dev/get-started/install/windows), so'ng `flutter doctor --android-licenses` bajaring.
2. `BUILD_APK.bat` ni ikki marta bosing. Birinchi marta 5-15 daqiqa ketadi.
3. Tayyor fayl: `dist\SafeVault-v0.1.apk`. Xato chiqsa, oynadagi matnni menga yuboring.

## 3-qadam. Telefonga o'rnatish
1. APK ni telefonga o'tkazing va oching ("Noma'lum manbalardan o'rnatish" ruxsatini bering).
2. Telefon va kompyuter **bir Wi-Fi** tarmog'ida bo'lsin. Windows xavfsizlik oynasi chiqsa, "Private networks" ga ruxsat bering.
3. Ilovada server manzilini kiriting: `192.168.1.15:8080` (o'zingiznikini yozing), telefon raqami va emailni kiriting, "Kodlarni yuborish" ni bosing.
4. **Kodlar SMS/emailga ketmaydi**: ularni server oynasidan (yoki `data\outbox.log` dan) ko'ring.
5. **Tiklash kodini qog'ozga yozing.** U faqat bir marta ko'rsatiladi.
6. Nimalar zaxiralanishini tanlang va "Hozir zaxiralash" ni bosing.

## Avtomatik zaxira (v0.2)
Bosh sahifada **"Avtomatik zaxira (fonda)"** ni yoqing: ilova ochiq bo'lmasa ham, internet bor paytda yangi rasm, video va kontaktlar o'zi shifrlanib yuklanadi (har ~30 daqiqada tekshiradi). Birinchi marta ko'p rasm bo'lsa, bir necha marta ishlab hammasini yuklab bo'ladi.
- Rasmlar uchun ruxsatni **"Hammasiga ruxsat"** qilib bering.
- Xiaomi, Samsung, Huawei, Oppo va Vivo telefonlarida **Sozlamalar → Ilovalar → SafeVault → Batareya → Cheklovsiz** ni tanlang. Aks holda telefon zaxirani to'xtatib qo'yadi.
- Natija bosh sahifada ("Oxirgi tekshiruv ...") ko'rinadi.

## Joylashuv (v0.3)
Bosh sahifada **«Joylashuvni yuborish»** ni yoqing (ruxsat: «Doim ruxsat berish»). **«Telefon joylashuvi (xarita)»** tugmasi oxirgi yuborilgan joyni xaritada ko'rsatadi. Batafsil: `QOLLANMA_BOT_uz.md`.

## Server doim ishlashi uchun
Kompyuter o'chiq bo'lsa, server ham ishlamaydi. Doimiy ishlashi uchun `QOLLANMA_VPS_uz.md` (deploy papkasida) bo'yicha serverni VPS ga ko'chiring.

## Muhim eslatmalar
- Hozircha oddiy `http`: faqat uy tarmog'ida sinash uchun. Internetdan foydalanish uchun HTTPS kerak.
- Hujjatlar hozircha qo'lda tanlanadi; 200 MB dan katta fayllar o'tkazib yuboriladi.
- Parol ham, tiklash kodi ham yo'qolsa, fayllarni hech kim ochib bera olmaydi.
- `C:\SafeVaultData` papkasini boshqa diskka nusxalab turing: barcha shifrlangan fayllar shu yerda.
