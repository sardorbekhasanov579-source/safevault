import datetime as dt
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from safevault_agent import claude as claude_mod
from safevault_agent import gemini as gemini_mod
from safevault_agent.bot import Bot
from safevault_agent.search import parse_query, search
from safevault_agent.state import State, hash_pin
from safevault_agent.tg import Telegram
from safevault_client import crypto as C

PHONE, EMAIL, PW = "+998901234567", "sardor@gmail.com", "Kuchli-Parol-1"
TODAY = dt.date(2026, 11, 24)  # seshanba


# ---------------- qidiruv ----------------
def test_parse_last_month_diploma():
    q = parse_query("O'tgan oy saqlagan diplomimni topib ber", TODAY)
    assert q["keywords"] == ["diplomimni"]
    assert (q["start"], q["end"]) == (dt.date(2026, 10, 1), dt.date(2026, 10, 31))


def test_parse_variants():
    assert parse_query("o‘tgan oy diplom", dt.date(2026, 1, 15))["start"] == dt.date(2025, 12, 1)  # yanvarda -> dekabr, ʻ belgisi
    q = parse_query("kecha olingan rasmlar", TODAY)
    assert q["start"] == q["end"] == dt.date(2026, 11, 23) and q["category"] == "photo" and q["keywords"] == ["olingan"]
    q = parse_query("o'tgan hafta pasport", TODAY)
    assert (q["start"], q["end"]) == (dt.date(2026, 11, 16), dt.date(2026, 11, 22)) and q["keywords"] == ["pasport"]
    q = parse_query("oktabr oyidagi shartnoma", TODAY)
    assert q["start"] == dt.date(2026, 10, 1) and q["keywords"] == ["shartnoma"]
    q = parse_query("mart 2025 diplom", TODAY)
    assert (q["start"], q["end"]) == (dt.date(2025, 3, 1), dt.date(2025, 3, 31))
    q = parse_query("kontaktlar", TODAY)
    assert q["category"] == "contact" and q["keywords"] == []
    assert parse_query("oxirgi diplom", TODAY)["latest"] is True


def ts(y, m, d, h=12):
    return dt.datetime(y, m, d, h).timestamp()


INDEX = [
    {"id": "a", "name": "diplom.pdf", "category": "document", "size": 1, "uploaded_at": ts(2026, 10, 12)},
    {"id": "b", "name": "diplom_nusxa.jpg", "category": "photo", "size": 1, "uploaded_at": ts(2026, 11, 2)},
    {"id": "c", "name": "pasport.pdf", "category": "document", "size": 1, "uploaded_at": ts(2026, 10, 30)},
    {"id": "d", "name": "IMG_001.jpg", "category": "photo", "size": 1, "uploaded_at": ts(2026, 10, 31, 23)},
    {"id": "e", "name": "Diplom ilovasi.docx", "category": "document", "size": 1, "uploaded_at": ts(2026, 9, 1)},
]


def ids(res):
    return [f["id"] for f in res[0]]


def test_search_last_month_diploma_finds_only_october_diploma():
    assert ids(search(INDEX, parse_query("o'tgan oy saqlagan diplomimni topib ber", TODAY))) == ["a"]


def test_search_no_dates_ranks_by_recency():
    assert ids(search(INDEX, parse_query("diplom", TODAY))) == ["b", "a", "e"]


def test_search_date_boundaries_and_category():
    assert ids(search(INDEX, parse_query("o'tgan oy rasmlar", TODAY))) == ["d"]  # 31-oktabr 23:00 kiradi
    assert ids(search(INDEX, {"keywords": [], "category": None, "start": dt.date(2026, 11, 1), "end": dt.date(2026, 11, 30), "latest": False})) == ["b"]


def test_search_latest_and_relaxed_category():
    assert ids(search(INDEX, parse_query("oxirgi diplom", TODAY))) == ["b"]
    res, relaxed = search(INDEX, parse_query("pasport rasmim", TODAY))  # rasm toifasida yo'q -> nomi bo'yicha
    assert [f["id"] for f in res] == ["c"] and relaxed
    assert search(INDEX, parse_query("mavjud emas fayl", TODAY))[0] == []


# ---------------- Claude so'rovi (mahalliy soxta server) ----------------
class _FakeAnthropic(BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeAnthropic.seen = {"path": self.path, "key": self.headers.get("x-api-key"), "body": body}
        out = {"content": [{"type": "tool_use", "name": "search_files", "input": {
            "keywords": ["Diplom"], "category": "document", "saved_from": "2026-10-01", "saved_to": "2026-10-31"}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_claude_extract_parses_tool_use():
    srv = HTTPServer(("127.0.0.1", 0), _FakeAnthropic)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        q = claude_mod.extract("sk-test", "o'tgan oy diplomimni topib ber", TODAY, base_url=f"http://127.0.0.1:{srv.server_address[1]}")
    finally:
        srv.shutdown()
        srv.server_close()
    assert q == {"keywords": ["diplom"], "category": "document", "start": dt.date(2026, 10, 1), "end": dt.date(2026, 10, 31), "latest": False}
    seen = _FakeAnthropic.seen
    assert seen["path"] == "/v1/messages" and seen["key"] == "sk-test"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "search_files"}
    assert seen["body"]["messages"][0]["content"] == "o'tgan oy diplomimni topib ber"  # faqat foydalanuvchi matni
    assert "2026-11-24" in seen["body"]["system"]


# ---------------- Telegram klienti (mahalliy soxta server) ----------------
class _FakeTelegram(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        _FakeTelegram.calls.append((self.path, self.headers.get("Content-Type"), raw))
        data = json.dumps({"ok": True, "result": []}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_telegram_client_requests():
    _FakeTelegram.calls.clear()
    srv = HTTPServer(("127.0.0.1", 0), _FakeTelegram)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        tg = Telegram("123:ABC", f"http://127.0.0.1:{srv.server_address[1]}")
        tg.send_message(5, "salom", [[("1", "get:abc")]])
        tg.send_location(5, 41.3, 69.2)
        payload = bytes(range(256)) * 10
        tg.send_document(5, 'dip"lom.pdf', payload, "izoh")
    finally:
        srv.shutdown()
        srv.server_close()
    (p1, _, b1), (p2, _, b2), (p3, ct3, b3) = _FakeTelegram.calls
    assert p1 == "/bot123:ABC/sendMessage" and json.loads(b1)["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "get:abc"
    assert p2 == "/bot123:ABC/sendLocation" and json.loads(b2)["latitude"] == 41.3
    assert p3 == "/bot123:ABC/sendDocument" and ct3.startswith("multipart/form-data; boundary=")
    assert payload in b3 and b'filename="dip_lom.pdf"' in b3 and b'name="chat_id"\r\n\r\n5' in b3


def test_telegram_error_does_not_leak_token():
    tg = Telegram("123:SECRET", "http://127.0.0.1:1")
    with pytest.raises(Exception) as e:
        tg.send_message(1, "x")
    assert "SECRET" not in str(e.value)


# ---------------- Bot: haqiqiy server + soxta Telegram ----------------
class FakeTG:
    def __init__(self):
        self.messages, self.docs, self.locations, self.answers = [], [], [], []
        self.keyboards, self.commands = [], None

    deleted = None

    def delete_message(self, chat, mid):
        if self.deleted is None:
            self.deleted = []
        self.deleted.append((chat, mid))

    def send_message(self, chat, text, buttons=None, keyboard=None):
        self.messages.append((chat, text, buttons))
        if keyboard:
            self.keyboards.append(keyboard)

    def set_commands(self, commands):
        self.commands = commands

    def answer_callback(self, cid, text=None):
        self.answers.append((cid, text))

    def send_document(self, chat, name, data, caption=None):
        self.docs.append((chat, name, data))

    def send_location(self, chat, lat, lon):
        self.locations.append((chat, lat, lon))


def msg(chat, text):
    return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}


def press(chat, data):
    return {"update_id": 2, "callback_query": {"id": "cb1", "data": data, "message": {"chat": {"id": chat}}}}


@pytest.fixture()
def bot_env(env, tmp_path):
    phone = env.client("phone-1")
    phone.request_otp("register", PHONE, EMAIL)
    phone.register(PHONE, EMAIL, env.last_code("otp-phone", PHONE), env.last_code("otp-email", EMAIL), PW)
    diploma = b"DIPLOM-MAZMUNI" * 500
    phone.backup(diploma, {"name": "diplom.pdf", "category": "document"})
    phone.backup(os.urandom(300), {"name": "IMG_1.jpg", "category": "photo"})
    state = State(str(tmp_path / "agent" / "state.json"))
    state.set(owner_chat=None, pair_code="ABCD2345")
    agent_vault = env.client("agent-1")  # alohida qurilma: bir xil hisob
    agent_vault.request_otp("new_device", PHONE)
    code_sms = env.last_code("otp-phone", PHONE)
    # yangi qurilma kirishi uchun tiklash kodi kerak — yangi hisob yaratamiz o'rniga phone sessiyasidan foydalanamiz
    agent_vault.token, agent_vault.mk = phone.token, phone.mk
    tg = FakeTG()
    return Bot(state, tg, agent_vault), tg, phone, diploma, state


def test_bot_pairing_and_ignores_strangers(bot_env):
    bot, tg, _, _, state = bot_env
    bot.handle_update(msg(99, "diplom"))
    assert "ulanmagan" in tg.messages[-1][1] and not tg.docs
    bot.handle_update(msg(99, "/ulash XXXXXXXX"))
    assert "noto'g'ri" in tg.messages[-1][1] and state.get("owner_chat") is None
    bot.handle_update(msg(99, "/ulash abcd2345"))  # kod katta-kichik harfga sezgir emas
    assert state.get("owner_chat") == 99 and state.get("pair_code") is None
    n = len(tg.messages)
    bot.handle_update(msg(7, "diplom"))  # boshqa chat
    assert len(tg.messages) == n and not tg.docs


def test_bot_search_and_download(bot_env):
    bot, tg, _, diploma, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    bot.handle_update(msg(5, "diplomimni topib ber"))
    chat, text, buttons = tg.messages[-1]
    assert "diplom.pdf" in text and "IMG_1" not in text
    cb = buttons[0][0][1]
    assert cb.startswith("get:")
    bot.handle_update(press(5, cb))
    assert tg.docs == [(5, "diplom.pdf", diploma)]  # shifri ochilgan asl fayl
    bot.handle_update(msg(5, "yo'q-bunaqa-narsa"))
    assert "topilmadi" in tg.messages[-1][1].lower()


def test_bot_not_found_by_date_explains_and_falls_back(bot_env):
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    # fayllar bugun saqlangan, "o'tgan hafta" esa boshqa kunlar: bot sababini aytib, sanasiz natijani ko'rsatishi kerak
    bot.handle_update(msg(5, "o'tgan hafta saqlagan hujjatlarim"))
    chat, text, buttons = tg.messages[-1]
    assert "shu sanalarda hech narsa saqlanmagan" in text and "diplom.pdf" in text and buttons


def test_bot_not_found_summarizes_vault(bot_env):
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    bot.handle_update(msg(5, "videolarim"))  # video yo'q va sana yo'q
    text = tg.messages[-1][1]
    assert "Topilmadi" in text and "1 ta rasm" in text and "1 ta hujjat" in text and "0 ta video" in text


def test_bot_persistent_keyboard_and_button_presses(bot_env):
    bot, tg, _, _, state = bot_env
    bot.handle_update(msg(5, "/ulash ABCD2345"))
    assert tg.keyboards and tg.keyboards[-1][0][0] == "📂 Oxirgi fayllar"
    bot.handle_update(msg(5, "📊 Holat"))  # tugma = /holat
    assert "Saqlangan fayllar: 2" in tg.messages[-1][1]
    bot.handle_update(msg(5, "📂 Oxirgi fayllar"))
    assert "diplom.pdf" in tg.messages[-1][1] and "IMG_1.jpg" in tg.messages[-1][1]
    n = len(tg.keyboards)
    bot.handle_update(msg(5, "❓ Yordam"))
    assert len(tg.keyboards) == n + 1 and "Masalan yozing" in tg.messages[-1][1]


def test_bot_pin_prompt_explains_format(bot_env):
    bot, tg, _, _, state = bot_env
    from safevault_agent.state import hash_pin
    state.set(owner_chat=5, pair_code=None, pin=hash_pin("1234"))
    bot.handle_update(msg(5, "2026"))
    assert "/pin" in tg.messages[-1][1] and "bo'sh joy" in tg.messages[-1][1]
    bot.handle_update(msg(5, "/pin 1234"))
    assert "PIN to'g'ri" in tg.messages[-1][1] and tg.keyboards


def mmsg(chat, text, mid):
    return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text, "message_id": mid}}


def _guest_env(bot_env, pin="4321"):
    from safevault_agent.state import hash_pin
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None, phone=PHONE, pin=hash_pin(pin))
    bot._verify = lambda phone, password: password == PW
    return bot, tg, state


def _login_as(bot, chat, phone, password, pin):
    bot.handle_update(mmsg(chat, "/kirish", 1))
    bot.handle_update(mmsg(chat, phone, 2))
    bot.handle_update(mmsg(chat, password, 3))
    bot.handle_update(mmsg(chat, pin, 4))


def test_guest_login_from_other_telegram_account(bot_env):
    bot, tg, state = _guest_env(bot_env)
    bot.handle_update(msg(77, "diplom"))  # kirmagan hisob: jim
    assert not tg.messages
    bot.handle_update(msg(77, "/start"))  # faqat kirish yo'lini ko'rsatadi, ma'lumot bermaydi
    assert "/kirish" in tg.messages[-1][1] and "diplom" not in tg.messages[-1][1]
    tg.messages.clear()
    _login_as(bot, 77, PHONE, PW, "4321")
    assert "Kirdingiz" in tg.messages[-1][1] and tg.keyboards
    assert (77, 3) in tg.deleted and (77, 4) in tg.deleted and (77, 2) in tg.deleted  # telefon, parol va PIN xabarlari o'chirilgan
    bot.handle_update(msg(77, "diplomimni topib ber"))
    assert "diplom.pdf" in tg.messages[-1][1]
    bot.handle_update(press(77, tg.messages[-1][2][0][0][1]))
    assert tg.docs and tg.docs[-1][0] == 77


def test_guest_login_rejects_wrong_credentials_and_locks(bot_env):
    bot, tg, state = _guest_env(bot_env)
    _login_as(bot, 77, PHONE, "xato-parol", "4321")
    assert "noto'g'ri" in tg.messages[-1][1] and not bot._guests()
    _login_as(bot, 77, "+998900000000", PW, "4321")  # boshqa telefon
    assert not bot._guests()
    _login_as(bot, 77, PHONE, PW, "0000")  # PIN xato
    assert not bot._guests()
    for _ in range(3):
        _login_as(bot, 77, PHONE, "yana-xato", "4321")
    bot.handle_update(mmsg(77, "/kirish", 9))
    assert "Juda ko'p xato" in tg.messages[-1][1]
    _login_as(bot, 77, PHONE, PW, "4321")
    assert not bot._guests()  # bloklangan paytda to'g'ri ma'lumot ham o'tmaydi


def test_default_password_check_against_real_server(env, bot_env):
    bot, tg, _, _, state = bot_env
    state.set(server=env.url, device_id="phone-1")  # ro'yxatdan o'tgan qurilma identifikatori bilan
    assert bot._verify_with_server(PHONE, PW) is True
    assert bot._verify_with_server(PHONE, "boshqa-parol") is False


def test_guest_login_requires_pin_set_and_expires(bot_env):
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None, phone=PHONE, pin=None)
    bot.handle_update(mmsg(77, "/kirish", 1))
    assert "PIN o'rnatishi kerak" in tg.messages[-1][1]
    bot, tg, state = _guest_env(bot_env)
    t = [1_000_000.0]
    bot.now = lambda: t[0]
    _login_as(bot, 77, PHONE, PW, "4321")
    assert bot._role(77) == "guest"
    t[0] += 12 * 3600 + 1
    assert bot._role(77) is None  # muddati tugadi


def test_guest_logout_owner_commands_and_revoke_all(bot_env):
    bot, tg, state = _guest_env(bot_env)
    bot._unlocked[5] = bot.now() + 1000
    _login_as(bot, 77, PHONE, PW, "4321")
    bot.handle_update(msg(77, "/yopish"))
    assert "faqat bot egasi" in tg.messages[-1][1] and bot._role(77) == "guest"
    bot.handle_update(msg(5, "/seanslar"))
    assert "1 ta" in tg.messages[-1][1]
    bot.handle_update(msg(5, "/yopish"))
    assert bot._role(77) is None
    _login_as(bot, 77, PHONE, PW, "4321")
    bot.handle_update(msg(77, "/chiqish"))
    assert bot._role(77) is None and "Chiqdingiz" in tg.messages[-1][1]


def test_owner_sets_pin_in_chat(bot_env):
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None, pin=None)
    bot.handle_update(mmsg(5, "/pinqoy 99", 1))
    assert "kamida 4" in tg.messages[-1][1] and not state.get("pin")
    bot.handle_update(mmsg(5, "/pinqoy 7777", 2))
    assert state.get("pin") and (5, 2) in tg.deleted and "PIN o'rnatildi" in tg.messages[-1][1]


def test_telegram_client_payloads():
    import safevault_agent.tg as tgmod
    t = tgmod.Telegram("TOKEN")
    sent = []
    t._json = lambda method, payload, timeout=40: sent.append((method, payload))  # noqa: E731
    t.send_message(1, "x", keyboard=[["a", "b"]])
    t.set_commands([("oxirgi", "Oxirgi")])
    assert sent[0][1]["reply_markup"] == {"keyboard": [[{"text": "a"}, {"text": "b"}]], "resize_keyboard": True, "is_persistent": True}
    assert sent[1] == ("setMyCommands", {"commands": [{"command": "oxirgi", "description": "Oxirgi"}]})


def test_bot_status_last_and_help(bot_env):
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    bot.handle_update(msg(5, "/holat"))
    assert "Saqlangan fayllar: 2" in tg.messages[-1][1]
    bot.handle_update(msg(5, "/oxirgi"))
    assert "IMG_1.jpg" in tg.messages[-1][1] and "diplom.pdf" in tg.messages[-1][1]
    bot.handle_update(msg(5, "/yordam"))
    assert "/joylashuv" in tg.messages[-1][1]


def test_bot_location(bot_env):
    bot, tg, phone, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    bot.handle_update(msg(5, "/joylashuv"))
    assert "hali joylashuv yubormagan" in tg.messages[-1][1] and not tg.locations
    phone.send_location(41.2995, 69.2401, 25.0, "Toshkent, Amir Temur ko'chasi", battery=7)
    bot.handle_update(msg(5, "/joylashuv"))
    assert tg.locations == [(5, 41.2995, 69.2401)]
    text = tg.messages[-1][1]
    assert "Toshkent" in text and "Batareya: 7%" in text and "OXIRGI" in text


def test_bot_pin_gate(bot_env):
    now = [1000.0]
    bot, tg, _, diploma, state = bot_env
    bot.now = lambda: now[0]
    state.set(owner_chat=5, pair_code=None, pin=hash_pin("4321"))
    bot.handle_update(msg(5, "diplom"))
    assert "PIN" in tg.messages[-1][1] and not any("diplom.pdf" in m[1] for m in tg.messages)
    bot.handle_update(press(5, "get:" + "0" * 32))
    assert "PIN" in tg.answers[-1][1] and not tg.docs
    bot.handle_update(msg(5, "/pin 0000"))
    assert "noto'g'ri" in tg.messages[-1][1]
    bot.handle_update(msg(5, "/pin 4321"))
    assert "to'g'ri" in tg.messages[-1][1]
    bot.handle_update(msg(5, "diplom"))
    assert "diplom.pdf" in tg.messages[-1][1]
    now[0] += 31 * 60  # 30 daqiqadan keyin qayta so'raydi
    bot.handle_update(msg(5, "diplom"))
    assert "PIN" in tg.messages[-1][1]


def test_bot_pin_lockout(bot_env):
    now = [1000.0]
    bot, tg, _, _, state = bot_env
    bot.now = lambda: now[0]
    state.set(owner_chat=5, pair_code=None, pin=hash_pin("4321"))
    for _ in range(5):
        bot.handle_update(msg(5, "/pin 1111"))
    bot.handle_update(msg(5, "/pin 4321"))  # to'g'ri PIN ham bloklangan
    assert "Juda ko'p" in tg.messages[-1][1]
    now[0] += 16 * 60
    bot.handle_update(msg(5, "/pin 4321"))
    assert "to'g'ri" in tg.messages[-1][1]


def test_bot_expired_session_message(bot_env):
    bot, tg, phone, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    bot.vault.token = "yaroqsiz"
    bot.handle_update(msg(5, "/holat"))
    assert "qayta sozlang" in tg.messages[-1][1]


def test_state_file_roundtrip(tmp_path):
    s = State(str(tmp_path / "s" / "state.json"))
    s.set(server="http://x", token="t", mk="m", device_id="d", tg_token="tt")
    assert State(str(tmp_path / "s" / "state.json")).ready
    if os.name == "posix":
        assert oct(os.stat(s.path).st_mode & 0o777) == "0o600"


# ---------------- Gemini so'rovi (mahalliy soxta server) ----------------
class _FakeGemini(BaseHTTPRequestHandler):
    seen = {}
    reply = None
    reject_new_format = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeGemini.seen = {"path": self.path, "key": self.headers.get("x-goog-api-key"), "body": body}
        if _FakeGemini.reject_new_format and "responseFormat" in body["generationConfig"]:
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        out = {"candidates": [{"content": {"parts": [{"text": json.dumps(_FakeGemini.reply)}]}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _with_fake_gemini(reply, fn):
    _FakeGemini.reply = reply
    srv = HTTPServer(("127.0.0.1", 0), _FakeGemini)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        return fn(f"http://127.0.0.1:{srv.server_address[1]}")
    finally:
        srv.shutdown()
        srv.server_close()


def test_gemini_extract_request_and_parse():
    reply = {"keywords": ["Diplom"], "category": "document", "saved_from": "2026-10-01", "saved_to": "2026-10-31", "latest_only": False}
    q = _with_fake_gemini(reply, lambda base: gemini_mod.extract("g-key", "o'tgan oy diplomimni topib ber", TODAY, base_url=base))
    assert q == {"keywords": ["diplom"], "category": "document", "start": dt.date(2026, 10, 1), "end": dt.date(2026, 10, 31), "latest": False}
    seen = _FakeGemini.seen
    assert seen["path"] == "/v1beta/models/gemini-3.5-flash-lite:generateContent" and seen["key"] == "g-key"
    fmt = seen["body"]["generationConfig"]["responseFormat"]["text"]
    assert fmt["mimeType"] == "application/json" and fmt["schema"]["type"] == "object"
    prompt = seen["body"]["contents"][0]["parts"][0]["text"]
    assert "o'tgan oy diplomimni topib ber" in prompt and "2026-11-24" in prompt


def test_gemini_falls_back_to_legacy_schema_fields_on_400():
    reply = {"keywords": ["diplom"], "category": "any", "saved_from": "", "saved_to": "", "latest_only": False}
    _FakeGemini.reject_new_format = True
    try:
        q = _with_fake_gemini(reply, lambda base: gemini_mod.extract("k", "diplom", TODAY, base_url=base))
    finally:
        _FakeGemini.reject_new_format = False
    assert q["keywords"] == ["diplom"]
    cfg = _FakeGemini.seen["body"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["responseSchema"]["type"] == "object"


def test_gemini_any_category_and_empty_dates():
    reply = {"keywords": [], "category": "any", "saved_from": "", "saved_to": "", "latest_only": True}
    q = _with_fake_gemini(reply, lambda base: gemini_mod.extract("k", "oxirgi fayl", TODAY, base_url=base))
    assert q == {"keywords": [], "category": None, "start": None, "end": None, "latest": True}


def test_bot_uses_gemini_and_falls_back_to_rules(bot_env):
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None, gemini_key="k")
    bot.handle_update(msg(5, "diplomimni topib ber"))  # kalit bor, lekin server yo'q -> oddiy qoidalarga o'tadi
    assert "diplom.pdf" in tg.messages[-1][1]


def test_bot_location_address_lookup_when_phone_sent_none(bot_env):
    bot, tg, phone, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    bot.geocode = lambda lat, lon: f"Soxta manzil {lat:.2f},{lon:.2f}"
    phone.send_location(41.2995, 69.2401, 12.0)  # manzilsiz, faqat koordinata (ilova shunday yuboradi)
    bot.handle_update(msg(5, "/joylashuv"))
    assert tg.locations == [(5, 41.2995, 69.2401)]
    assert "Taxminiy manzil: Soxta manzil 41.30,69.24" in tg.messages[-1][1]
    bot.geocode = lambda lat, lon: None  # manzil topilmasa ham koordinata va vaqt chiqadi
    bot.handle_update(msg(5, "/joylashuv"))
    assert "Yangilangan:" in tg.messages[-1][1] and "Taxminiy manzil" not in tg.messages[-1][1]


class _FakeNominatim(BaseHTTPRequestHandler):
    seen = {}

    def do_GET(self):
        _FakeNominatim.seen = {"path": self.path, "ua": self.headers.get("User-Agent")}
        data = json.dumps({"display_name": "Amir Temur ko'chasi, Toshkent"}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_reverse_geocode_request():
    from safevault_agent.geo import reverse_geocode
    srv = HTTPServer(("127.0.0.1", 0), _FakeNominatim)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert reverse_geocode(41.2995, 69.2401, base) == "Amir Temur ko'chasi, Toshkent"
        assert reverse_geocode(1.0, 1.0, "http://127.0.0.1:1") is None  # xatoda None, istisno emas
    finally:
        srv.shutdown()
        srv.server_close()
    assert "lat=41.299500" in _FakeNominatim.seen["path"] and "SafeVault" in _FakeNominatim.seen["ua"]


# ---------------- Kontaktlar va ommaviy yuklash ----------------
VCF = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Alisher Karimov\r\nTEL;TYPE=CELL:+998 90 111-22-33\r\nEND:VCARD\r\n"
       "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Rustamova;Dilnoza;;;\r\nTEL:+998935556677\r\nEND:VCARD\r\n"
       "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Bobur\r\nEND:VCARD\r\n")


def test_parse_and_search_vcf():
    from safevault_agent import contacts as ct
    people = ct.parse_vcf(VCF)
    assert [p["name"] for p in people] == ["Alisher Karimov", "Bobur", "Dilnoza Rustamova"]
    assert [p["name"] for p in ct.search_contacts(people, "alisherning")] == ["Alisher Karimov"]  # qo'shimchali so'z
    assert [p["name"] for p in ct.search_contacts(people, "935556677")] == ["Dilnoza Rustamova"]
    assert ct.search_contacts(people, "yo'q") == []
    assert ct.format_contacts(people)[0].startswith("👤 Alisher Karimov — +998 90 111-22-33")


def test_bot_contacts_list_and_search(bot_env):
    bot, tg, phone, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    bot.handle_update(msg(5, "/kontaktlar"))
    assert "yo'q" in tg.messages[-1][1]  # hali kontakt zaxiralanmagan
    phone.backup(VCF.encode(), {"name": "kontaktlar.vcf", "category": "contact", "count": 3})
    bot.handle_update(msg(5, "👤 Kontaktlar"))
    texts = " ".join(m[1] for m in tg.messages[-4:])
    assert "Alisher Karimov" in texts and "Dilnoza Rustamova" in texts and "Kontaktlar: 3 ta" in texts
    assert tg.docs[-1][1] == "kontaktlar.vcf" and tg.docs[-1][2] == VCF.encode()
    bot.handle_update(msg(5, "/kontaktlar dilnoza"))
    assert "Dilnoza" in tg.messages[-1][1] and "Alisher" not in tg.messages[-1][1]
    bot.handle_update(msg(5, "alisherning raqami"))  # oddiy gap: "raqam" -> kontakt qidiruvi
    assert "+998 90 111-22-33" in tg.messages[-1][1]
    bot.handle_update(msg(5, "/kontaktlar nomalum"))
    assert "topilmadi" in tg.messages[-1][1]


def test_plan_zips_splits_by_limit_and_skips_huge():
    from safevault_agent import bulk
    files = [{"id": str(i), "name": f"f{i}", "size": s, "uploaded_at": 100 - i} for i, s in enumerate([40, 30, 30, 200, 10])]
    parts, big = bulk.plan_zips(files, limit=60)
    assert [[f["id"] for f in p] for p in parts] == [["0"], ["1", "2"], ["4"]] and [f["id"] for f in big] == ["3"]


def test_bot_bulk_menu_and_zip_download(bot_env):
    import io
    import zipfile
    bot, tg, phone, diploma, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    phone.backup(b"ikkinchi", {"name": "diplom.pdf", "category": "document"})  # bir xil nom: ZIP ichida ajratilishi kerak
    bot.handle_update(msg(5, "📦 Hammasini yuklash"))
    chat, text, buttons = tg.messages[-1]
    assert "Hujjatlar: 2 ta" in text and "Rasmlar: 1 ta" in text
    cbs = [b[1] for row in buttons for b in row]
    assert "zip:document:0" in cbs and "zip:all:0" in cbs
    bot.handle_update(press(5, "zip:document:0"))
    chat, name, data = tg.docs[-1]
    assert name == "safevault-document-1-of-1.zip"
    z = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(z.namelist()) == ["diplom (2).pdf", "diplom.pdf"] and sorted(z.read(n) for n in z.namelist()) == sorted([diploma, b"ikkinchi"])
    assert "Hammasi yuborildi" in tg.messages[-1][1]


def test_bot_bulk_paging(bot_env, monkeypatch):
    from safevault_agent import bulk
    bot, tg, phone, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)
    monkeypatch.setattr(bulk, "PART_LIMIT", 1)  # hamma fayl chegaradan katta bo'lib qoladi
    bot.handle_update(press(5, "zip:all:0"))
    assert "45 MB dan katta" in tg.messages[-1][1] and not tg.docs
    monkeypatch.setattr(bulk, "PART_LIMIT", 300)  # diplom.pdf (~7000 bayt) sig'maydi; ikki kichik fayl har biri alohida ZIP bo'ladi
    phone.backup(b"x" * 200, {"name": "kichik1.txt", "category": "document"})
    phone.backup(b"y" * 200, {"name": "kichik2.txt", "category": "document"})
    monkeypatch.setattr(bulk, "PARTS_PER_STEP", 1)
    tg.messages.clear()
    bot.handle_update(press(5, "zip:document:0"))
    assert len(tg.docs) == 1
    nxt = tg.messages[-1][2][0][0][1]
    assert nxt.startswith("zip:document:")
    bot.handle_update(press(5, nxt))
    assert len(tg.docs) == 2
    bot.handle_update(press(5, "zip:hack:0"))  # noto'g'ri toifa: e'tiborsiz
    assert len(tg.docs) == 2


# ---------------- Bulutda ishlash (konteyner) ----------------
def test_cloud_load_state_from_env(tmp_path, monkeypatch):
    import base64
    from safevault_agent import cloud
    home = tmp_path / "agent"
    monkeypatch.setenv("SAFEVAULT_AGENT_HOME", str(home))
    monkeypatch.delenv("SAFEVAULT_AGENT_STATE_B64", raising=False)
    monkeypatch.delenv("SAFEVAULT_AGENT_SERVER", raising=False)
    assert not cloud.load_state().ready  # sozlanmagan
    data = {"server": "https://eski.example", "token": "t", "mk": "bQ", "device_id": "d", "tg_token": "x", "owner_chat": 5}
    monkeypatch.setenv("SAFEVAULT_AGENT_STATE_B64", base64.b64encode(json.dumps(data).encode()).decode())
    monkeypatch.setenv("SAFEVAULT_AGENT_SERVER", "http://127.0.0.1:9999")
    st = cloud.load_state()
    assert st.ready and st.get("server") == "http://127.0.0.1:9999" and (home / "state.json").exists()
    # diskdagi holat (masalan keyingi o'zgarishlar) muhit o'zgaruvchisidan ustun turadi
    st.set(owner_chat=77)
    monkeypatch.setenv("SAFEVAULT_AGENT_STATE_B64", base64.b64encode(json.dumps({**data, "owner_chat": 1}).encode()).decode())
    assert cloud.load_state().get("owner_chat") == 77
    monkeypatch.setenv("SAFEVAULT_AGENT_STATE_B64", "bu-base64-emas!!")
    monkeypatch.setenv("SAFEVAULT_AGENT_HOME", str(tmp_path / "boshqa"))
    with pytest.raises(SystemExit):
        cloud.load_state()


def test_bot_run_keeps_session_alive(bot_env):
    bot, tg, _, _, state = bot_env
    calls = []
    real = bot.vault.status
    bot.vault.status = lambda: (calls.append(1), real())[1]

    def boom(offset, timeout):
        raise KeyboardInterrupt

    tg.get_updates = boom
    tg.set_commands = lambda c: None
    with pytest.raises(KeyboardInterrupt):
        bot.run()
    assert calls == [1]


def test_run_all_serves_health_without_agent(tmp_path):
    import socket
    import subprocess
    import sys
    import time
    import urllib.request
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = {**os.environ, "PORT": str(port), "SAFEVAULT_DATA": str(tmp_path / "d"), "SAFEVAULT_HOST": "127.0.0.1",
           "SAFEVAULT_AGENT_HOME": str(tmp_path / "a"), "PYTHONPATH": ""}
    env.pop("SAFEVAULT_AGENT_STATE_B64", None)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen([sys.executable, os.path.join(root, "deploy", "run_all.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = False
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=1) as r:
                    ok = r.status == 200
                    break
            except OSError:
                time.sleep(0.2)
        assert ok
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_bot_reports_unreachable_server(bot_env):
    import urllib.error
    bot, tg, _, _, state = bot_env
    state.set(owner_chat=5, pair_code=None)

    def down(*a, **k):
        raise urllib.error.URLError("connection refused")

    bot.vault.list_files = down
    bot.handle_update(msg(5, "diplomimni topib ber"))
    assert "ulanib bo'lmadi" in tg.messages[-1][1]
