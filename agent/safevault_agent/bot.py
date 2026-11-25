"""Telegram bot: zaxiradagi fayllarni topib yuboradi, telefonning oxirgi joylashuvini ko'rsatadi."""
from __future__ import annotations

import datetime as dt
import hmac
import sys
import time
import urllib.error

from safevault_client import crypto as C
from safevault_client.client import ApiFailure, VaultClient

from . import bulk
from . import claude as claude_mod
from . import contacts as contacts_mod
from . import gemini as gemini_mod
from .geo import reverse_geocode
from .search import describe_query, parse_query, search, summarize
from .state import State, check_pin, hash_pin
from .tg import MAX_UPLOAD, TelegramError

ICONS = {"photo": "🖼", "video": "🎬", "contact": "👤", "document": "📄"}
UNLOCK_SECONDS = 30 * 60
KEEPALIVE_SECONDS = 6 * 3600
GUEST_TTL = 12 * 3600  # boshqa Telegram hisobidan kirish shuncha vaqt amal qiladi
LOGIN_TTL = 5 * 60     # kirish jarayoni (telefon, parol, PIN) shuncha vaqt ichida tugatilishi kerak
MENU = [["📂 Oxirgi fayllar", "📊 Holat"], ["👤 Kontaktlar", "📍 Joylashuv"], ["📦 Hammasini yuklash", "❓ Yordam"]]
BUTTON_COMMANDS = {"📂 oxirgi fayllar": "/oxirgi", "📊 holat": "/holat", "📍 joylashuv": "/joylashuv", "❓ yordam": "/yordam",
                   "👤 kontaktlar": "/kontaktlar", "📦 hammasini yuklash": "/hammasi"}
COMMANDS = [("oxirgi", "Oxirgi saqlangan fayllar"), ("holat", "Zaxira holati"),
            ("kontaktlar", "Kontaktlar ro'yxati (yoki /kontaktlar ism)"), ("hammasi", "Fayllarni ZIP qilib bir yo'la yuklash"),
            ("joylashuv", "Telefonning oxirgi joylashuvi"), ("yordam", "Yordam va misollar"),
            ("pin", "PIN kiritish (masalan: /pin 1234)"), ("kirish", "Boshqa Telegram hisobidan kirish"),
            ("chiqish", "Shu hisobdan chiqish")]
HELP = ("Men zaxiradagi fayllaringizni topib beraman.\n\n"
        "Masalan yozing:\n• o'tgan oy saqlagan diplomimni topib ber\n• kecha olingan rasmlar\n• kontaktlar\n\n"
        "Buyruqlar (pastdagi tugmalar yoki / menyusi ham ishlaydi):\n/oxirgi — oxirgi saqlangan fayllar\n/holat — zaxira holati\n"
        "/kontaktlar — kontaktlar ro'yxati; /kontaktlar ali — ism yoki raqam bo'yicha qidirish\n"
        "/hammasi — fayllarni ZIP qilib bir yo'la yuklab olish (toifa bo'yicha yoki hammasi)\n"
        "/joylashuv — telefonning oxirgi joylashuvi\n/pin KOD — PIN kiritish (agar o'rnatilgan bo'lsa)\n\n"
        "Boshqa Telegram hisobidan: /kirish (telefon raqam, parol va PIN so'raladi). Chiqish: /chiqish.\n"
        "Faqat egasi uchun: /pinqoy KOD (PIN o'rnatish), /seanslar (boshqa hisoblar), /yopish (hammasini chiqarib yuborish).\n\n"
        "Izoh: qidiruv fayl nomi, turi va saqlangan sanasi bo'yicha ishlaydi (fayl ichidagi matn bo'yicha emas).")


def fmt_size(b: int) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if b >= div:
            return f"{b / div:.1f} {unit}"
    return f"{b} B"


def fmt_ts(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


class Bot:
    def __init__(self, state: State, tg, vault, now=time.time, geocode=reverse_geocode, verify_password=None):
        self.state, self.tg, self.vault, self.now, self.geocode = state, tg, vault, now, geocode
        self._verify = verify_password or self._verify_with_server
        self._unlocked: dict[int, float] = {}   # chat -> PIN ochiq turadigan vaqt
        self._pages: dict = {}  # chat -> (natijalar, sarlavha), 'Yana' tugmasi uchun
        self._login: dict[int, dict] = {}       # boshqa hisobdan kirish jarayonlari
        self._login_fails = 0
        self._login_locked_until = 0.0
        self._index_cache: tuple[float, list[dict]] | None = None
        self._pin_fails = 0
        self._pin_locked_until = 0.0
        self._pair_fails = 0
        self._last_keep = 0.0

    # ---------- yordamchilar ----------
    def _index(self, fresh: bool = False) -> list[dict]:
        if not fresh and self._index_cache and self.now() - self._index_cache[0] < 60:
            return self._index_cache[1]
        idx = [{"id": f["id"], "name": f.get("name", "?"), "category": f.get("category", "document"),
                "size": f["size"], "uploaded_at": f["uploaded_at"]} for f in self.vault.list_files()]
        self._index_cache = (self.now(), idx)
        return idx

    def _extract(self, text: str) -> dict:
        """AI so'rovni tahlil qiladi; kalit yo'q yoki xato bo'lsa, oddiy qoidalarga o'tadi."""
        try:
            if self.state.get("gemini_key"):
                return gemini_mod.extract(self.state.get("gemini_key"), text, dt.date.today(),
                                          self.state.get("gemini_model") or gemini_mod.DEFAULT_MODEL)
            if self.state.get("anthropic_key"):
                return claude_mod.extract(self.state.get("anthropic_key"), text, dt.date.today(),
                                          self.state.get("model") or "claude-haiku-5-5")
        except Exception as e:  # noqa: BLE001  (kalit xabarga chiqmaydi)
            print(f"[agent] AI tahlili ishlamadi ({type(e).__name__}), oddiy qidiruvga o'tildi", file=sys.stderr)
        return parse_query(text)

    # ---------- kirish nuqtasi ----------
    def handle_update(self, upd: dict):
        chat = None
        try:
            if "message" in upd:
                chat = upd["message"]["chat"]["id"]
                self._on_message(upd["message"])
            elif "callback_query" in upd:
                cq = upd["callback_query"]
                chat = cq["message"]["chat"]["id"]
                self._on_callback(cq)
        except ApiFailure as e:
            msg = ("Zaxira serveriga kirish muddati tugagan. Kompyuterda agentni qayta sozlang (setup)."
                   if e.status == 401 else f"Server xatosi: {e.code or e.status}")
            self._safe_send(chat, msg)
        except urllib.error.URLError:
            print("[agent] zaxira serveriga ulanib bo'lmadi (server ishlayaptimi?)", file=sys.stderr)
            self._safe_send(chat, "Zaxira serveriga ulanib bo'lmadi. Server (ISHGA_TUSHIR.bat yoki bulutdagi server) ishlab turganini tekshiring, so'ng qayta urinib ko'ring.")
        except Exception as e:  # noqa: BLE001
            print(f"[agent] xato: {type(e).__name__}: {e}", file=sys.stderr)
            self._safe_send(chat, "Kutilmagan xato yuz berdi. Keyinroq urinib ko'ring.")

    def _safe_send(self, chat, text):
        if chat is None:
            return
        try:
            self.tg.send_message(chat, text)
        except TelegramError:
            pass

    # ---------- xabarlar ----------
    def _on_message(self, msg: dict):
        chat, text = msg["chat"]["id"], (msg.get("text") or "").strip()
        owner = self.state.get("owner_chat")
        if owner is None:
            return self._pairing(chat, text)
        role = self._role(chat)
        if role is None:
            return self._stranger(chat, text, msg)
        if not self._gate(chat, text):
            return
        text = BUTTON_COMMANDS.get(text.lower(), text)  # pastdagi tugma bosilsa, mos buyruqqa aylanadi
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else None
        if cmd in ("/start", "/yordam", "/help"):
            self.tg.send_message(chat, HELP, keyboard=MENU)
        elif cmd == "/holat":
            self._status(chat)
        elif cmd == "/oxirgi":
            self._send_results(chat, sorted(self._index(True), key=lambda f: -f["uploaded_at"]), "Oxirgi saqlanganlar:")
        elif cmd == "/joylashuv":
            self._location(chat)
        elif cmd in ("/kontaktlar", "/kontakt"):
            self._contacts(chat, text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else "")
        elif cmd == "/hammasi":
            self._bulk_menu(chat)
        elif cmd == "/pin":
            self.tg.send_message(chat, "PIN qabul qilindi." if self.state.get("pin") else "PIN o'rnatilmagan.")
        elif cmd == "/chiqish":
            self._logout(chat, role)
        elif cmd in ("/pinqoy", "/seanslar", "/yopish"):
            if role != "owner":
                self.tg.send_message(chat, "Bu buyruq faqat bot egasi uchun.")
            elif cmd == "/pinqoy":
                self._set_pin(chat, text, msg)
            elif cmd == "/seanslar":
                g = self._guests()
                self.tg.send_message(chat, f"Boshqa Telegram hisoblaridan kirganlar: {len(g)} ta. Hammasini chiqarish: /yopish" if g
                                     else "Boshqa hisoblardan hech kim kirmagan.")
            else:
                self.state.set(guests={})
                self._unlocked = {c: t for c, t in self._unlocked.items() if c == owner}
                self.tg.send_message(chat, "Boshqa hisoblar chiqarib yuborildi.")
        elif cmd:
            self.tg.send_message(chat, "Noma'lum buyruq. /yordam ni bosing.")
        elif text:
            self._find(chat, text)

    def _pairing(self, chat, text: str):
        code = self.state.get("pair_code")
        parts = text.split()
        if parts and parts[0].split("@")[0].lower() == "/ulash" and len(parts) > 1 and code and self._pair_fails < 10:
            if hmac.compare_digest(parts[1].strip().upper(), code):
                self.state.set(owner_chat=chat, pair_code=None)
                self.tg.send_message(chat, "Ulandi! Endi faqat siz foydalana olasiz. Pastdagi tugmalardan foydalaning yoki /yordam ni bosing.", keyboard=MENU)
            else:
                self._pair_fails += 1
                self.tg.send_message(chat, "Kod noto'g'ri.")
        else:
            self.tg.send_message(chat, "Bu bot hali ulanmagan. Kompyuter oynasida ko'rsatilgan kodni yuboring: /ulash KOD")

    def _gate(self, chat, text: str) -> bool:
        """PIN o'rnatilgan bo'lsa, har 30 daqiqada bir marta so'raydi."""
        pin = self.state.get("pin")
        if not pin or self.now() < self._unlocked.get(chat, 0.0):
            return True
        parts = text.split(maxsplit=1)
        if parts and parts[0].split("@")[0].lower() == "/pin" and len(parts) > 1:
            if self.now() < self._pin_locked_until:
                self.tg.send_message(chat, "Juda ko'p xato urinish. Keyinroq urinib ko'ring.")
            elif check_pin(parts[1].strip(), pin):
                self._unlocked[chat], self._pin_fails = self.now() + UNLOCK_SECONDS, 0
                self.tg.send_message(chat, "PIN to'g'ri. 30 daqiqa ochiq.", keyboard=MENU)
            else:
                self._pin_fails += 1
                if self._pin_fails >= 5:
                    self._pin_locked_until, self._pin_fails = self.now() + 15 * 60, 0
                self.tg.send_message(chat, "PIN noto'g'ri.")
            return False
        self.tg.send_message(chat, "Avval PIN kiriting. PIN ni shunday yuboring: /pin va bo'sh joydan keyin PIN (masalan: /pin 1234)")
        return False

    # ---------- boshqa Telegram hisoblaridan kirish ----------
    def _guests(self) -> dict:
        """Muddati o'tmagan mehmon hisoblar: {chat_id(str): kirgan_vaqt}."""
        g = {c: t for c, t in (self.state.get("guests") or {}).items() if self.now() - t < GUEST_TTL}
        return g

    def _role(self, chat) -> str | None:
        if chat == self.state.get("owner_chat"):
            return "owner"
        return "guest" if str(chat) in self._guests() else None

    def _verify_with_server(self, phone: str, password: str) -> bool:
        """Parol to'g'riligini zaxira serveri orqali tekshiradi (agentning o'z qurilma identifikatori bilan)."""
        vc = VaultClient(self.state.get("server"), self.state.get("device_id"))
        try:
            vc.login(phone, password)
        except ApiFailure:
            return False
        return True

    def _delete(self, chat, msg: dict):
        """Parol/PIN yozilgan xabarni chatdan darhol o'chiradi (agar Telegram ruxsat bersa)."""
        mid = msg.get("message_id")
        if mid is None or not hasattr(self.tg, "delete_message"):
            return
        try:
            self.tg.delete_message(chat, mid)
        except TelegramError:
            pass

    def _login_fail(self, chat):
        self._login.pop(chat, None)
        self._login_fails += 1
        if self._login_fails >= 5:
            self._login_locked_until, self._login_fails = self.now() + 15 * 60, 0
        self.tg.send_message(chat, "Telefon, parol yoki PIN noto'g'ri. /kirish dan qaytadan boshlang.")

    def _stranger(self, chat, text: str, msg: dict):
        """Ulanmagan chat: faqat /start va /kirish ga javob beradi, qolganiga jim turadi."""
        st = self._login.get(chat)
        if st and self.now() - st["t"] > LOGIN_TTL:
            self._login.pop(chat, None)
            st = None
        first = text.split()[0].split("@")[0].lower() if text.split() else ""
        if first == "/start" and not st:
            return self.tg.send_message(chat, "Bu shaxsiy bot. Kirish uchun /kirish ni yuboring (telefon raqam, parol va PIN so'raladi).")
        if first == "/kirish":
            if not self.state.get("pin"):
                return self.tg.send_message(chat, "Bu botga boshqa hisobdan kirish uchun egasi avval PIN o'rnatishi kerak.")
            if self.now() < self._login_locked_until:
                return self.tg.send_message(chat, "Juda ko'p xato urinish. 15 daqiqadan keyin urinib ko'ring.")
            self._login[chat] = {"step": "phone", "t": self.now()}
            return self.tg.send_message(chat, "Zaxira hisobingiz telefon raqamini yuboring (masalan: +998901234567).")
        if not st:
            return
        if self.now() < self._login_locked_until:
            self._delete(chat, msg)
            return self.tg.send_message(chat, "Juda ko'p xato urinish. 15 daqiqadan keyin urinib ko'ring.")
        step = st["step"]
        if step == "phone":
            st.update(phone=text.strip(), step="password", t=self.now())
            self._delete(chat, msg)
            self.tg.send_message(chat, "Zaxira hisobi parolini yuboring. Xabar darhol o'chirib tashlanadi.")
        elif step == "password":
            self._delete(chat, msg)
            phone = st["phone"]
            if not hmac.compare_digest(phone, self.state.get("phone") or "") or not self._verify(phone, text):
                return self._login_fail(chat)
            st.update(step="pin", t=self.now())
            self.tg.send_message(chat, "Endi bot PIN kodini yuboring. Xabar darhol o'chirib tashlanadi.")
        elif step == "pin":
            self._delete(chat, msg)
            if not check_pin(text.strip(), self.state.get("pin") or ""):
                return self._login_fail(chat)
            self._login.pop(chat, None)
            g = self._guests()
            g[str(chat)] = self.now()
            self.state.set(guests=g)
            self._login_fails = 0
            self._unlocked[chat] = self.now() + UNLOCK_SECONDS
            self.tg.send_message(chat, f"Kirdingiz. Bu hisob {GUEST_TTL // 3600} soat amal qiladi; chiqish: /chiqish. "
                                       "Pastdagi tugmalardan foydalaning.", keyboard=MENU)

    def _logout(self, chat, role):
        if role == "owner":
            return self.tg.send_message(chat, "Siz bot egasisiz. Boshqa hisoblarni chiqarish uchun /yopish.")
        g = self._guests()
        g.pop(str(chat), None)
        self.state.set(guests=g)
        self._unlocked.pop(chat, None)
        self.tg.send_message(chat, "Chiqdingiz. Qayta kirish uchun /kirish.")

    def _set_pin(self, chat, text: str, msg: dict):
        parts = text.split(maxsplit=1)
        self._delete(chat, msg)
        if len(parts) < 2 or len(parts[1].strip()) < 4:
            return self.tg.send_message(chat, "PIN kamida 4 belgi bo'lsin. Yozing: /pinqoy 1234")
        self.state.set(pin=hash_pin(parts[1].strip()))
        self.tg.send_message(chat, "PIN o'rnatildi (yozgan xabaringiz o'chirildi). Endi boshqa hisoblardan /kirish orqali kirish mumkin.")

    # ---------- buyruqlar ----------
    def _status(self, chat):
        st = self.vault.status()
        last = fmt_ts(st["last_backup_at"]) if st.get("last_backup_at") else "hali yo'q"
        self.tg.send_message(chat, f"Saqlangan fayllar: {st['file_count']} ({fmt_size(st['total_bytes'])})\nOxirgi zaxira: {last}")

    def _location(self, chat):
        try:
            loc = self.vault.get_location()
        except ApiFailure as e:
            if e.status == 404:
                return self.tg.send_message(chat, "Telefon hali joylashuv yubormagan. Ilovada 'Joylashuvni yuborish' yoqilganini tekshiring.")
            raise
        self.tg.send_location(chat, loc["lat"], loc["lon"])
        lines = [f"Yangilangan: {fmt_ts(loc['updated_at'])}"]
        addr = loc.get("addr") or self.geocode(loc["lat"], loc["lon"])
        if addr:
            lines.insert(0, f"Taxminiy manzil: {addr}")
        if loc.get("acc") is not None:
            lines.append(f"Aniqlik: ~{int(loc['acc'])} m")
        if loc.get("bat") is not None:
            lines.append(f"Batareya: {loc['bat']}%")
        lines.append("Bu telefon OXIRGI yuborgan joy; telefon hozir shu yerda bo'lmasligi mumkin.")
        self.tg.send_message(chat, "\n".join(lines))

    def _find(self, chat, text: str):
        q = self._extract(text)
        if q.get("category") == "contact":  # "Alisherning raqami", "kontaktlar" ...
            return self._contacts(chat, " ".join(q.get("keywords") or []))
        index = self._index(True)
        results, relaxed = search(index, q, limit=1000)
        if results:
            head = "Topilgan fayllar:" + ("\n(Toifa bo'yicha topilmadi, nomi bo'yicha ko'rsatyapman)" if relaxed else "")
            return self._send_results(chat, results, head)
        asked = describe_query(q)
        if (q.get("start") or q.get("end")) and index:
            # sana bo'yicha topilmasa, sanasiz urinib ko'ramiz va buni ochiq aytamiz
            results, _ = search(index, dict(q, start=None, end=None), limit=1000)
            if results:
                return self._send_results(
                    chat, results, f"So'rovingiz bo'yicha ({asked}) shu sanalarda hech narsa saqlanmagan.\n"
                                   "Sanadan qat'i nazar topilganlar (eng yangilari birinchi):")
        tips = "\n\nMaslahat: sanani olib tashlab yozing yoki fayl nomidagi so'zni ayting. 📂 Oxirgi fayllar tugmasi hammasini ko'rsatadi."
        if index and q.get("category") == "document" and not any(f.get("category") == "document" for f in index):
            tips = "\n\nHujjatlar hali zaxiraga qo'shilmagan: ilovada Zaxira sozlamalarida «Hujjatlar» ni yoqing yoki «Hujjat tanlab zaxiralash» tugmasini bosing."
        self.tg.send_message(chat, f"Topilmadi (so'rov: {asked}).\n{summarize(index)}{tips}")

    def _contacts(self, chat, query: str = ""):
        files = [f for f in self._index(True) if f["category"] == "contact"]
        if not files:
            return self.tg.send_message(chat, "Kontaktlar zaxirada yo'q. Telefondagi ilovada Zaxira sozlamalarida «Kontaktlar» ni belgilab, "
                                              "«Hozir zaxiralash» ni bosing (kontakt ruxsatini bering).")
        latest = max(files, key=lambda f: f["uploaded_at"])
        raw = self.vault.restore(latest["id"])
        people = contacts_mod.parse_vcf(raw.decode("utf-8", "replace"))
        if query.strip():
            found = contacts_mod.search_contacts(people, query)
            if not found:
                return self.tg.send_message(chat, f"«{query.strip()}» bo'yicha kontakt topilmadi (jami {len(people)} ta kontakt).")
            for chunk in contacts_mod.format_contacts(found)[:3]:
                self.tg.send_message(chat, chunk)
            if len(found) > 20:
                self.tg.send_message(chat, f"Jami {len(found)} ta topildi; aniqroq yozing yoki /kontaktlar bilan to'liq ro'yxatni oling.")
            return
        if not people:
            return self.tg.send_message(chat, "Kontaktlar fayli bor, lekin ichidan kontakt o'qib bo'lmadi. Faylni yuboryapman:")
        chunks = contacts_mod.format_contacts(people)
        self.tg.send_message(chat, f"Kontaktlar: {len(people)} ta (saqlangan: {fmt_ts(latest['uploaded_at'])})")
        for chunk in chunks[:4]:
            self.tg.send_message(chat, chunk)
        if len(chunks) > 4:
            self.tg.send_message(chat, "Ro'yxat uzun, qolgani quyidagi .vcf faylda.")
        self.tg.send_document(chat, "kontaktlar.vcf", raw, caption="Barcha kontaktlar (.vcf): telefonga import qilsa bo'ladi")

    def _bulk_menu(self, chat):
        idx = self._index(True)
        if not idx:
            return self.tg.send_message(chat, "Hali fayl saqlanmagan.")
        lines, rows = ["Qaysi fayllarni ZIP qilib yuboray?"], []
        for cat, label in (("photo", "Rasmlar"), ("video", "Videolar"), ("document", "Hujjatlar"), ("contact", "Kontaktlar")):
            fs = [f for f in idx if f["category"] == cat]
            if fs:
                parts, big = bulk.plan_zips(fs)
                lines.append(f"{ICONS[cat]} {label}: {len(fs)} ta, {fmt_size(sum(f['size'] for f in fs))} → {len(parts)} ta ZIP"
                             + (f" (+{len(big)} ta juda katta)" if big else ""))
                rows.append([(f"{ICONS[cat]} {label}", f"zip:{cat}:0")])
        parts, big = bulk.plan_zips(idx)
        rows.append([("📦 Hammasi", "zip:all:0")])
        lines.append(f"\nHammasi: {len(idx)} ta fayl → {len(parts)} ta ZIP. Telegram bir faylga 50 MB ruxsat beradi, shuning uchun qismlarga bo'linadi; "
                     f"bir bosishda {bulk.PARTS_PER_STEP} tagacha ZIP yuboraman.")
        self.tg.send_message(chat, "\n".join(lines), rows)

    def _bulk_send(self, chat, cat: str, start: int):
        idx = self._index(True)
        files = idx if cat == "all" else [f for f in idx if f["category"] == cat]
        parts, big = bulk.plan_zips(files)
        if not parts:
            return self.tg.send_message(chat, "Bu toifada yuboriladigan fayl yo'q." + (
                f" ({len(big)} ta fayl 45 MB dan katta, ularni /oxirgi orqali alohida oling)" if big else ""))
        end = min(start + bulk.PARTS_PER_STEP, len(parts))
        self.tg.send_message(chat, f"ZIP {start + 1}–{end} / {len(parts)} tayyorlanmoqda…")
        for i in range(start, end):
            data = bulk.build_zip(self.vault, parts[i])
            self.tg.send_document(chat, f"safevault-{cat}-{i + 1}-of-{len(parts)}.zip", data,
                                  caption=f"{i + 1}/{len(parts)} · {len(parts[i])} ta fayl")
        if start == 0 and big:
            names = ", ".join(f["name"] for f in big[:10])
            self.tg.send_message(chat, f"{len(big)} ta fayl 45 MB dan katta, ZIP ga kirmadi (alohida tugma bilan oling): {names}")
        if end < len(parts):
            nxt = min(bulk.PARTS_PER_STEP, len(parts) - end)
            self.tg.send_message(chat, f"Yuborildi: {end}/{len(parts)}.", [[(f"➡️ Keyingi {nxt} ta ZIP", f"zip:{cat}:{end}")]])
        else:
            self.tg.send_message(chat, f"Hammasi yuborildi ({len(parts)} ta ZIP).")

    PAGE = 8

    def _send_results(self, chat, results: list[dict], head: str, start: int = 0):
        if not results:
            return self.tg.send_message(chat, "Hali fayl saqlanmagan.")
        self._pages[chat] = (results, head)
        total = len(results)
        page = results[start:start + self.PAGE]
        lines = [head]
        if total > self.PAGE:
            lines.append(f"(jami {total} ta, {start + 1}–{start + len(page)}-lari ko'rsatilmoqda)")
        for i, f in enumerate(page, start + 1):
            lines.append(f"{i}. {ICONS.get(f['category'], '📎')} {f['name']} — {fmt_size(f['size'])}, {fmt_ts(f['uploaded_at'])}")
        lines.append("\nYuklab olish uchun raqamni bosing:")
        nums = [(str(i), f"get:{f['id']}") for i, f in enumerate(page, start + 1)]
        buttons = [nums[k:k + 4] for k in range(0, len(nums), 4)]
        nav = []
        if start > 0:
            nav.append(("⬅️ Oldingi", f"more:{max(0, start - self.PAGE)}"))
        if start + self.PAGE < total:
            nav.append((f"➡️ Yana {min(self.PAGE, total - start - self.PAGE)} ta", f"more:{start + self.PAGE}"))
        if nav:
            buttons.append(nav)
        self.tg.send_message(chat, "\n".join(lines), buttons)

    # ---------- tugmalar ----------
    def _on_callback(self, cq: dict):
        chat = cq["message"]["chat"]["id"]
        if self._role(chat) is None:
            return
        pin = self.state.get("pin")
        if pin and self.now() >= self._unlocked.get(chat, 0.0):
            return self.tg.answer_callback(cq["id"], "Avval PIN kiriting: /pin KOD")
        data = cq.get("data") or ""
        if data.startswith("zip:"):
            _, cat, start = (data.split(":") + ["all", "0"])[:3]
            if cat not in ("all", "photo", "video", "document", "contact") or not start.isdigit():
                return self.tg.answer_callback(cq["id"])
            self.tg.answer_callback(cq["id"], "Tayyorlanmoqda…")
            return self._bulk_send(chat, cat, int(start))
        if data.startswith("more:"):
            saved = self._pages.get(chat)
            n = data[5:]
            if not saved or not n.isdigit():
                return self.tg.answer_callback(cq["id"], "Qidiruvni qaytadan yozing")
            self.tg.answer_callback(cq["id"])
            return self._send_results(chat, saved[0], saved[1], int(n))
        if not data.startswith("get:"):
            return self.tg.answer_callback(cq["id"])
        fid = data[4:]
        entry = next((f for f in self._index(True) if f["id"] == fid), None)
        if not entry:
            return self.tg.answer_callback(cq["id"], "Fayl topilmadi")
        if entry["size"] > MAX_UPLOAD + 1024 * 1024:
            return self.tg.answer_callback(cq["id"], "Fayl Telegram uchun juda katta (50 MB dan ortiq)")
        self.tg.answer_callback(cq["id"], "Yuklanmoqda…")
        data_bytes = self.vault.restore(fid)
        if len(data_bytes) > MAX_UPLOAD:
            return self.tg.send_message(chat, f"{entry['name']} Telegram orqali yuborish uchun juda katta.")
        self.tg.send_document(chat, entry["name"], data_bytes, caption=entry["name"])

    # ---------- doimiy ish ----------
    def keepalive_tick(self):
        """Serverga muntazam murojaat: sessiya muddati uzayib turadi."""
        if self.now() - self._last_keep > KEEPALIVE_SECONDS:
            self._last_keep = self.now()
            try:
                self.vault.status()
            except ApiFailure as e:
                print(f"[agent] server sessiyasi yangilanmadi: {e.code or e.status}", file=sys.stderr)

    def run(self):
        offset = None
        try:
            if hasattr(self.tg, "delete_webhook"):
                self.tg.delete_webhook()  # oldin webhook o'rnatilgan bo'lsa, getUpdates ishlashi uchun
        except Exception as e:  # noqa: BLE001
            print(f"[agent] webhookni o'chirib bo'lmadi: {type(e).__name__}", file=sys.stderr)
        try:
            if hasattr(self.tg, "set_commands"):
                self.tg.set_commands(COMMANDS)  # yozish maydoni yonidagi "/" menyusi
        except Exception as e:  # noqa: BLE001
            print(f"[agent] buyruqlar menyusini o'rnatib bo'lmadi: {type(e).__name__}", file=sys.stderr)
        print("[agent] Bot ishga tushdi. To'xtatish: Ctrl+C", flush=True)
        while True:
            try:
                self.keepalive_tick()
                for upd in self.tg.get_updates(offset, 30):
                    offset = upd["update_id"] + 1
                    self.handle_update(upd)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001
                print(f"[agent] tarmoq xatosi: {type(e).__name__}; 5 soniyadan keyin qayta uriniladi", file=sys.stderr)
                time.sleep(5)
