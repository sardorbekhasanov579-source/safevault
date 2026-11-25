# SafeVault: kompyuterdan mustaqil (bulutda) ishlash

Maqsad: kompyuteringiz o'chiq bo'lsa ham **server** (zaxira ombori) va **Telegram bot** ishlab tursin.
Buning uchun ikkalasi bitta konteynerda (`Dockerfile.allinone`) bulutga joylanadi. Telefon ilovasi va Telegram bot shu yerga ulanadi.

## Qaysi yo'lni tanlash kerak (halol taqqoslash)
Dastur fayllarni **diskda** va ma'lumotlar bazasini **SQLite** faylida saqlaydi, bot esa doim ishlab turishi kerak.

| Yo'l | Doimiy disk | Uxlab qolish | Narx | Holat |
|---|---|---|---|---|
| **A. VPS** (Hetzner, Contabo, DigitalOcean...) | bor | yo'q | oyiga ~4–6 $ | **Tavsiya.** Hammasi tayyor, kod o'zgarmaydi |
| **B. Render (pullik) + GitHub** | pullik rejada diskni ulash mumkin | pullik rejalar uxlamaydi | render.com/pricing da ko'ring | Tayyor (`render.yaml`) |
| **C. Render bepul + Neon** | **yo'q**: bepul xizmatning fayllari har qayta ishga tushganda o'chadi | 15 daqiqa trafik bo'lmasa uxlaydi, qayta ochilishi ~1 daqiqa | bepul | **Hozirgi kod bilan mos emas** (pastga qarang) |

### Nega C (Render bepul + Neon) hozir ishlamaydi
- Render bepul xizmati diskni saqlamaydi: yuklangan fayllar va SQLite har qayta ishga tushishda yo'qoladi. Telegram bot esa serverga tashqaridan so'rov kelmasa 15 daqiqada uxlaydi va xabarlarga javob bermaydi.
- Neon bepul rejasida har loyiha uchun **1 GB** joy bor. Bu faqat kichik ma'lumotlar bazasiga yetadi, rasm va videolarga emas.
- Shuning uchun bepul ishlashi uchun kodni o'zgartirish kerak: bazani Neon (Postgres)ga, fayllarni alohida fayl omboriga (S3 turidagi), botni "webhook" rejimiga o'tkazish. Bu katta ish; kerak bo'lsa keyingi bosqichda qilish mumkin. Shuncha ishdan keyin ham bepul tariflar o'zgarishi mumkin.

## Umumiy tayyorgarlik (A va B uchun)
1. **Yangi bulutda yangi hisob:** eng sodda yo'l. Serverni bulutga qo'ygach, telefon ilovasida yangi serverga ro'yxatdan o'ting; ilova rasmlarni qayta yuklaydi (rasmlar telefonda bor). Eski kompyuter ma'lumotlarini ko'chirish ham mumkin (VPS qo'llanmasining 6-bandi).
2. `ALLOWED_PHONES` ga faqat o'z raqamingizni yozing.
3. Tasdiqlash kodlari Telegramga kelishi uchun `TG_TOKEN` va `TG_CHAT` kerak (VPS qo'llanmasining 4-bandi).

## Botni (agentni) bulutga olib o'tish
Bot kompyuterda **bir marta** sozlanadi, keyin uning holati bulutga beriladi.
1. Serverni bulutga joylang va ilovada ro'yxatdan o'ting (yuqoridagi tayyorgarlik).
2. Kompyuterda `BOT_ISHGA_TUSHIR.bat` ni oching. Server manzili: **bulutdagi manzil** (`https://...`). Telefon, parol, kodlar, bot tokeni, Gemini kaliti, PIN ni kiriting.
3. Chiqqan `/ulash KOD` ni **hozircha yubormang**. Oynani yoping (Ctrl+C).
4. PowerShell'da state faylini base64 ga aylantirib nusxalang:
   ```
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\.safevault_agent\state.json")) | Set-Clipboard
   ```
5. Nusxani bulutdagi `AGENT_STATE_B64` (VPS: `.env` fayli, Render: Environment) ga qo'ying va qayta ishga tushiring.
6. Telegram'da botga `/ulash KOD` yuboring. Endi bot bulutda ishlaydi.
7. **Kompyuterdagi botni qayta ishga tushirmang:** bitta tokenni ikki joyda ishlatib bo'lmaydi (Telegram xato beradi).

> **Xavfsizlik:** `state.json` ichida shifrlash kaliti va bot tokeni bor. Uni bulutga bersangiz, bulut hisobingizga (VPS yoki Render) kirgan odam zaxirangizni ochishi mumkin. Hisobni kuchli parol va ikki bosqichli tasdiq bilan himoyalang. Bot sessiyasi har 6 soatda o'zi yangilanadi, shuning uchun 30 kun ishlatmasangiz ham tugamaydi.

## A. VPS
`deploy/QOLLANMA_VPS_uz.md` ni bajaring. Bot uchun faqat `.env` ga `AGENT_STATE_B64=...` qo'shish yetarli.

## B. Render + GitHub
1. GitHub'da **private** (yopiq) repozitoriy oching. Loyiha papkasida:
   ```
   git init
   git add .
   git commit -m "SafeVault"
   git branch -M main
   git remote add origin https://github.com/SIZNING_NOM/safevault.git
   git push -u origin main
   ```
   `.gitignore` sirlarni (`data/`, `*.key`, `state.json`, `.env`) yuklamaydi. Ularni GitHub'ga **hech qachon** yuklamang.
2. render.com ga kiring, **New → Blueprint** ni tanlab, shu repozitoriyni ulang. `render.yaml` o'zi o'qiladi: Docker, 5 GB doimiy disk, `/v1/health` tekshiruvi.
3. So'ralgan maxfiy o'zgaruvchilarni kiriting: `SAFEVAULT_TG_TOKEN`, `SAFEVAULT_TG_CHAT`, `SAFEVAULT_ALLOWED_PHONES`, `SAFEVAULT_AGENT_STATE_B64` (bot keyin ham qo'shiladi).
4. Chiqqan manzilni (`https://safevault-xxxx.onrender.com`) telefon ilovasiga server sifatida kiriting.
5. Disk pullik rejada beriladi; `render.yaml` dagi reja nomi va narxni render.com/pricing da tekshiring.

## Gemini obunangiz haqida
Gemini ilovasidagi obuna (masalan Google AI Pro) botning **API kaliti** emas. Bot `aistudio.google.com` dan olinadigan **API kaliti** bilan ishlaydi. Obuna AI Studio'da yuqori limit beradi, API ni to'g'ridan-to'g'ri ishlatish esa alohida hisoblanadi, lekin to'lov sozlansa obunadagi oylik kreditlar API uchun ishlatilishi mumkin. Bot juda kam so'rov yuboradi (faqat qidiruv matni), shuning uchun odatda bepul limit ham yetadi. AI Studio'da o'z limitingizni tekshiring.
