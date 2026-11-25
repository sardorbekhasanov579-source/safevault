# SafeVault v0.4 — Telegram bot va AI qidiruv, kontaktlar, ommaviy yuklash, joylashuv

## Bu nima qiladi
Telegram'da botingizga oddiy gap bilan yozasiz, masalan: **«O'tgan oy saqlagan diplomimni topib ber»**.
Bot zaxirangizdan mos fayllarni topadi, tugmalar bilan ko'rsatadi, tanlaganingizni yuboradi.
Telefon o'chiq bo'lsa ham ishlaydi, chunki fayllar serverdagi zaxiradan olinadi.

Buyruqlar: `/yordam`, `/holat` (oxirgi zaxira), `/oxirgi` (oxirgi fayllar), `/joylashuv` (telefonning oxirgi joyi),
`/pin KOD` (PIN o'rnatilgan bo'lsa), `/ulash KOD` (botni ulash).

## Oldindan kerak bo'ladigan narsalar
1. **Server ishlab turishi kerak** (`ISHGA_TUSHIR.bat` yoki VPS) va telefon ilovasida hisob ochilgan, zaxira olingan bo'lishi kerak.
2. **Telegram bot tokeni:** Telegram'da @BotFather → `/newbot` → nom bering → token oling.
3. **Gemini API kaliti (ixtiyoriy):** aistudio.google.com → "Get API key". Kalit bo'lmasa, bot oddiy (qoidali) qidiruvdan foydalanadi. Bepul tarif shartlarini o'zingiz tekshirib ko'ring.
4. **Python 3.11+** (python.org, "Add python.exe to PATH" belgilansin). Kerakli paket `BOT_ISHGA_TUSHIR.bat` ichida o'zi o'rnatiladi (`cryptography`).

## Ishga tushirish
1. `BOT_ISHGA_TUSHIR.bat` ni ikki marta bosing.
2. Birinchi marta savollar beriladi:
   - server manzili (`http://127.0.0.1:8080` yoki VPS uchun `https://nom.duckdns.org`),
   - telefon raqamingiz va zaxira parolingiz,
   - yangi qurilma sifatida **SMS kodi** va **tiklash kodi** (bot agenti ham yangi qurilma hisoblanadi),
   - bot tokeni, Gemini kaliti, ixtiyoriy PIN.
3. Oxirida `/ulash 123456` kabi buyruq chiqadi. Uni **o'z botingizga** Telegram'da yuboring. Shundan keyin bot faqat sizniki bo'ladi, boshqa odamlarga javob bermaydi.
4. Keyingi ishga tushirishlarda savollar so'ralmaydi. Sozlamalar `C:\Users\SIZNING_NOM\.safevault_agent\state.json` faylida (parolingiz u yerda saqlanmaydi, lekin kalitlar bor).

## Pastdagi tugmalar va menyu
Bot ulangach, yozish maydoni ostida doim turadigan tugmalar chiqadi: **📂 Oxirgi fayllar, 📊 Holat, 📍 Joylashuv, ❓ Yordam**. Yozish maydoni yonidagi **«/» menyusi** ham barcha buyruqlarni ko'rsatadi. Tugmalar chiqmasa, botga `/yordam` yuboring.

## Kontaktlar
Tugma **👤 Kontaktlar** yoki `/kontaktlar`: oxirgi saqlangan kontaktlar ro'yxati ism va raqam bilan chiqadi, pastdan to'liq `.vcf` fayl ham yuboriladi (telefonga import qilsa bo'ladi).
- Qidirish: `/kontaktlar ali` yoki oddiy gap: «Alisherning raqami». Ism yoki raqamning bir qismi bo'yicha topadi.
- «Kontaktlar zaxirada yo'q» desa: telefondagi ilovada Zaxira sozlamalarida **Kontaktlar** ni belgilang, kontakt ruxsatini bering va «Hozir zaxiralash» ni bosing.

## Hammasini bir yo'la yuklab olish
Tugma **📦 Hammasini yuklash** yoki `/hammasi`: bot toifalar bo'yicha sonini va hajmini ko'rsatadi (Rasmlar, Videolar, Hujjatlar, Kontaktlar, Hammasi). Tanlasangiz, fayllar ZIP qilib yuboriladi.
- Telegram bir faylga 50 MB ruxsat beradi, shuning uchun fayllar ~45 MB li ZIP qismlarga bo'linadi. Bir bosishda 10 tagacha ZIP keladi, qolganini «➡️ Keyingi» tugmasi yuboradi.
- 45 MB dan katta bitta fayl ZIP ga kirmaydi; bot buni aytadi, uni `/oxirgi` yoki qidiruv orqali alohida oling.
- Ko'p GB bo'lsa, telefon ilovasidagi «Hammasini yuklab olish» tugmasi qulayroq (telefonga to'g'ridan-to'g'ri tiklaydi).

## Kompyuterdan mustaqil ishlash
Bot va serverni bulutga qo'yish: `QOLLANMA_BULUT_uz.md`.

## Boshqa Telegram hisobidan kirish
Do'stingiz yoki ikkinchi akkauntingizdagi Telegram'dan ham botdan foydalanish mumkin:
1. **Egasi bir marta PIN o'rnatishi kerak** (sozlashda o'rnatmagan bo'lsa, o'z chatida `/pinqoy 1234` yozing). PIN bo'lmasa, boshqa hisobdan kirish yopiq.
2. Boshqa Telegram'dan botga `/kirish` yuboring. Bot ketma-ket so'raydi: **telefon raqam → zaxira paroli → bot PIN'i**. Parol va PIN yozilgan xabarlar bot tomonidan darhol o'chiriladi.
3. Kirgach hisob **12 soat** amal qiladi, undan keyin qayta `/kirish` kerak. Chiqish: `/chiqish`.
4. Egasi uchun: `/seanslar` (nechta boshqa hisob kirgan) va `/yopish` (hammasini darhol chiqarish).
5. Himoya: ketma-ket 5 ta xato bo'lsa, kirish 15 daqiqaga bloklanadi. Kirmagan hisoblarga bot umuman javob bermaydi (faqat `/kirish` dan tashqari).

**Xavf haqida halol:** Telegram bot chatlari boshdan-oxir shifrlanmagan. Parolingiz Telegram serverlaridan o'tadi va o'chirilgunga qadar ko'rinib turishi mumkin. Parolni faqat o'zingiz ishongan hisobda kiriting va kiritganingizdan keyin xabar o'chganini tekshiring. Telefon + parol + PIN'ni bilgan odam butun zaxirangizni ko'ra oladi. Shubha bo'lsa, `/yopish` bosing va parolni ilovada o'zgartiring.

## Joylashuv
1. Telefon ilovasida bosh sahifada **«Joylashuvni yuborish»** ni yoqing. Ruxsat ikki bosqichda so'raladi: avval «ilova ochiqligida», keyin **«Doim ruxsat berish»**.
2. Ilova har ~30 daqiqada shifrlangan joyni yuboradi. Ilovadagi **«Telefon joylashuvi (xarita)»** yoki botdagi `/joylashuv` xarita, taxminiy manzil va yangilanish vaqtini ko'rsatadi.
3. Batareya sozlamasida SafeVault uchun **«Cheklovsiz»** ni tanlang, aks holda telefon fonda to'xtatib qo'yishi mumkin.

## Muhim cheklovlar (halol)
- **Qidiruv faqat fayl nomi, turi va saqlangan sanasi bo'yicha.** Hujjat ichidagi matn (masalan diplom ichida «diplom» so'zi) hali o'qilmaydi. Fayl nomi «IMG_2041.jpg» bo'lsa, uni nom bilan topib bo'lmaydi.
- **Telegram 50 MB gacha** fayl yuboradi; kattasi bo'lsa, bot shuni aytadi.
- **Maxfiylik:** bot agenti asosiy kalitni (MK) o'zida saqlaydi, shuning uchun u ishlaydigan kompyuter/VPS ga ishonchli bo'lishi shart. `state.json` ni hech kimga bermang. Server esa baribir hech narsani ko'ra olmaydi.
- **Gemini'ga faqat sizning so'rov matningiz va bugungi sana boradi.** Fayl nomlari, fayllar va joylashuv bormaydi. Gemini xato bersa yoki kalit bo'lmasa, bot oddiy qidiruvga o'tadi.
- Joylashuv faqat **telefon oxirgi yuborgan** nuqta; telefon o'chiq yoki internetsiz bo'lsa, yangilanmaydi. Manzil taxminiy (OpenStreetMap), so'rov paytida Nominatim'dan olinadi.
- Gemini javobi va fon joylashuvi hali haqiqiy telefon/kalit bilan sinalmagan. Xato chiqsa, matnini yuboring.

## VPS'da doimiy ishlatish
Kompyuter o'chsa, bot ham to'xtaydi. Doimiy ishlashi uchun agentni ham VPS'ga qo'yish mumkin (keyingi qadam); hozircha serverni VPS'da, botni esa o'z kompyuteringizda ishlatish mumkin.
