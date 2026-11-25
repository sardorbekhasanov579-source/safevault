# SafeVault: doimiy server (VPS) qo'llanmasi

Maqsad: server kompyuteringiz o'chiq bo'lsa ham 24/7 ishlasin, ilova esa istalgan joydan ulansin.
Taxminan 40-60 daqiqa. Hammasini bir marta qilasiz.

## 0. Nimalar kerak
- Oyiga ~4-6 dollarlik **VPS** (Ubuntu 24.04, 1 GB RAM, 20+ GB disk). Masalan Hetzner, DigitalOcean, Contabo yoki O'zbekistondagi hosting kompaniyalari. Hisobni ochish va to'lov sizning qo'lingizda.
- Bepul **domen**: duckdns.org (HTTPS uchun kerak).
- **Telegram** (kodlar SMS o'rniga shu yerga keladi).
- Windows'da `ssh` va `scp` bor (PowerShell'da ishlaydi).

> Eslatma: bu sozlama **faqat sizning shaxsiy** foydalanishingiz uchun. Ko'p foydalanuvchili ommaviy xizmatda
> haqiqiy SMS provayderi kerak va O'zbekiston shaxsiy ma'lumotlar qonunini (ma'lumotlarni mamlakat ichida saqlash) alohida ko'rib chiqish kerak.

## 1. VPS ni oling
1. Ubuntu 24.04 tanlang. Yaratgach sizga **IP manzil** (masalan 203.0.113.10) va `root` paroli (yoki SSH kaliti) beriladi.
2. PowerShell'da ulanib ko'ring: `ssh root@203.0.113.10`

## 2. Domen
1. duckdns.org ga kirib (Google bilan), yangi nom oling, masalan `sardor-vault` -> `sardor-vault.duckdns.org`.
2. "current ip" maydoniga VPS IP manzilini yozing va "update ip" bosing.

## 3. VPS ga Docker o'rnating (VPS ichida)
```
curl -fsSL https://get.docker.com | sh
```

## 4. Telegram bot yarating
1. Telegram'da **@BotFather** ga `/newbot` yozing, nom bering. U sizga **token** beradi (`123456:ABC...`). Uni hech kimga bermang.
2. Yangi botga kirib `/start` yozing.
3. Brauzerda oching: `https://api.telegram.org/bot<TOKEN>/getUpdates` (o'zingizning tokeningiz bilan). Natijadagi `"chat":{"id":123456789` dagi raqam **chat ID** bo'ladi.

## 5. Fayllarni VPS ga yuklang
Kompyuteringizda (PowerShell), ZIP ochilgan papkada:
```
scp SafeVault-server-vps.zip root@203.0.113.10:/root/
```
VPS ichida:
```
apt-get install -y unzip
cd /root && unzip SafeVault-server-vps.zip && cd safevault/deploy
cp .env.example .env
nano .env
```
`.env` ichida `DOMAIN`, `TG_TOKEN`, `TG_CHAT`, `ALLOWED_PHONES` ni to'ldiring (Ctrl+O, Enter, Ctrl+X bilan saqlang).

## 6. Mavjud ma'lumotlaringizni ko'chiring (hisobingiz va zaxiralar saqlanib qoladi)
1. Kompyuterdagi serverni to'xtating (`ISHGA_TUSHIR.bat` oynasini yoping).
2. PowerShell'da:
```
scp -r C:\SafeVaultData root@203.0.113.10:/root/safevault/deploy/data
```
Bu papkada `server_secret.key` ham bor, uni **albatta** ko'chiring, usiz eski hisob ishlamaydi.

## 7. Ishga tushiring (VPS ichida)
```
cd /root/safevault/deploy
docker compose -f docker-compose.vps.yml up -d --build
```
Tekshirish: brauzerda `https://sardor-vault.duckdns.org/v1/health` ochilsa, `{"ok": true...}` chiqadi.
(Birinchi marta HTTPS sertifikati olinishi 1-2 daqiqa olishi mumkin.)

## 8. Ilovada
Server manzili: `https://sardor-vault.duckdns.org` (portsiz). Eski hisobingiz bilan kiring. Yangi telefon bo'lsa, SMS kodi Telegram botga keladi.
Endi Tailscale va kompyuter kerak emas.

## Zaxira va xavfsizlik
- `deploy/data` papkasi (shifrlangan fayllar + baza + `server_secret.key`) ni vaqti-vaqti bilan kompyuteringizga ko'chirib turing:
  `scp -r root@203.0.113.10:/root/safevault/deploy/data C:\SafeVaultData_nusxa`
- VPS ga parol bilan emas, SSH kaliti bilan kirishni sozlash tavsiya etiladi; `ufw allow 22,80,443/tcp && ufw enable`.
- Yangilash: yangi ZIP ni yuklab, `docker compose -f docker-compose.vps.yml up -d --build` ni qayta bajaring.
- Loglarni ko'rish: `docker compose -f docker-compose.vps.yml logs -f safevault`
