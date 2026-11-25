# SafeVault: bepul bulut (Render + Backblaze B2 + GitHub)

Natija: kompyuteringiz o'chiq bo'lsa ham **server** va **Telegram bot** ishlaydi. Pul to'lanmaydi.

## Qanday ishlaydi
- **Render (bepul)** — dasturni ishga tushiradi. Diski doimiy emas, shuning uchun fayllar u yerda saqlanmaydi.
- **Backblaze B2 (10 GB bepul)** — shifrlangan fayllar, baza nusxasi va bot holati shu yerda turadi. Serverdagi hamma narsa allaqachon shifrlangan: B2 ham faqat shifrlangan baytlarni ko'radi.
- **GitHub** — kodni Render'ga yetkazadi.
- **Telegram webhook** — bot uxlab qolgan xizmatni Telegramning o'zi uyg'otadi.
- Neon ishlatilmadi: bepul 1 GB rasm va videolarga yetmaydi, B2 esa 10 GB beradi.

## Cheklovlar (halol)
- Render bepul xizmati **15 daqiqa** so'rov bo'lmasa uxlaydi, qayta uyg'onishi ~1 daqiqa oladi. 5-qadamdagi "ping" buni deyarli yo'qotadi.
- Bepul tariflar va shartlar o'zgarishi mumkin; kerak bo'lsa keyin pullik rejaga o'tish mumkin (kod o'zgarmaydi).
- Render bepul rejasida oyiga 750 soat bor: bitta xizmat uchun butun oyga yetadi.
- Bu yo'l haqiqiy Render va B2 bilan hali sinalmagan: testlar sun'iy ombor bilan o'tgan. Biror joyda xato chiqsa, Render **Logs** oynasidagi matnni menga yuboring.

## 0. Hisoblar (3 ta)
GitHub, Render (github orqali kirish mumkin), Backblaze B2 (backblaze.com > B2 Cloud Storage). Karta so'ralsa, to'xtang va menga yozing.

## 1. Backblaze B2
1. **Buckets > Create a Bucket**: nom yozing (masalan `safevault-sardor-123`), **Private** qoldiring, Create.
2. Bucket sahifasida **Endpoint** ko'rinadi, masalan `s3.eu-central-003.backblazeb2.com`. Oldiga `https://` qo'yib yozib oling.
3. **Application Keys > Add a New Application Key**: faqat shu bucketga ruxsat bering, **Read and Write**. Chiqqan **keyID** va **applicationKey** ni darhol yozib oling (ikkinchi marta ko'rsatilmaydi).

## 2. Eski ma'lumotlarni ko'chirish (kompyuterda)
Eski server (oyna) **yopiq** bo'lsin. Loyiha papkasida PowerShell:
```
$env:SAFEVAULT_S3_ENDPOINT="https://s3.eu-central-003.backblazeb2.com"
$env:SAFEVAULT_S3_BUCKET="bucket-nomi"
$env:SAFEVAULT_S3_KEY_ID="keyID"
$env:SAFEVAULT_S3_SECRET="applicationKey"
python deploy\migrate_to_cloud.py C:\SafeVaultData
```
Oxirida `SAFEVAULT_PEPPER_B64 = ...` chiqadi: uni yozib oling (maxfiy). Usiz eski parol va sessiyalar ishlamaydi.
Yangi boshlamoqchi bo'lsangiz (eski fayllar kerak bo'lmasa), bu qadamni o'tkazib yuboring va pepperni o'zingiz yarating:
```
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

## 3. Bot holatini tayyorlash
Bot kompyuterda allaqachon sozlangan (egasi, PIN, Gemini kaliti shu faylda). Uni base64 ga aylantiring:
```
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\.safevault_agent\state.json")) | Set-Clipboard
```
Nusxa buferda turadi (keyingi qadamda `SAFEVAULT_AGENT_STATE_B64` ga qo'yasiz). Bu faylda shifrlash kaliti va bot tokeni bor: hech kimga bermang.
Kompyuterdagi botni (**BOT_ISHGA_TUSHIR.bat**, AVTO_BOSHLASH) **o'chiring**: bitta bot ikki joyda ishlay olmaydi.

## 4. GitHub va Render
1. github.com da yangi **Private** repo oching (masalan `safevault`) va loyiha papkasini yuklang (**app/** papkasi shart emas). `.gitignore` bazani va kalitlarni yuklatmaydi.
2. render.com > **New > Blueprint** > reponi tanlang. `render.yaml` o'qiladi, reja **Free**.
3. So'ralgan qiymatlarni kiriting (namuna: `deploy/muhit.namuna.txt`):
   - `SAFEVAULT_PEPPER_B64`, `SAFEVAULT_S3_ENDPOINT`, `SAFEVAULT_S3_BUCKET`, `SAFEVAULT_S3_KEY_ID`, `SAFEVAULT_S3_SECRET`
   - `SAFEVAULT_TG_TOKEN`, `SAFEVAULT_TG_CHAT` (tasdiqlash kodlari Telegramga keladi)
   - `SAFEVAULT_ALLOWED_PHONES` = `+998973010022`
   - `SAFEVAULT_AGENT_STATE_B64` = 3-qadamdagi nusxa
4. Deploy tugagach manzil chiqadi: `https://safevault-xxxx.onrender.com`. Logda `Telegram webhook o'rnatildi` yozuvi bo'lishi kerak.

## 5. Uxlab qolmasligi uchun
uptimerobot.com (bepul) > **Add New Monitor** > HTTP(s), URL: `https://safevault-xxxx.onrender.com/v1/health`, interval 5 daqiqa.

## 6. Tekshirish
1. Telegram'da botga `/holat` yuboring: javob kelishi kerak (birinchi marta ~1 daqiqa kutish mumkin).
2. Telefon ilovasida **server manzili** ni yangi `https://...onrender.com` ga o'zgartiring va o'sha raqam/parol bilan kiring. Ko'chirilgan bo'lsa, fayllar ro'yxati turibdi.
3. Kompyuterni o'chirib, botga `/oxirgi` yuboring.

## Muammolar
- **Bot javob bermayapti**: Render **Logs** da `webhook o'rnatilmadi` bormi? Bot tokeni to'g'rimi? Kompyuterdagi bot hali ishlab turmaganmi?
- **`SAFEVAULT_PEPPER_B64 kerak`** xatosi: 4.3 dagi qiymat kiritilmagan.
- **Eski parol ishlamayapti**: pepper boshqa. 2-qadamdagi qiymatni qayta tekshiring.
- **Boshidan boshlash**: B2 bucketini bo'shating va yangi pepper bilan ro'yxatdan qaytadan o'ting.
- Bot holatini majburan almashtirish (masalan, token o'zgarganda): `SAFEVAULT_AGENT_STATE_FORCE=1` qo'shing, bir marta ishga tushgach olib tashlang.
