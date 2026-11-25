import os

import pytest

from safevault_client.client import ApiFailure

PHONE = "+998901234567"
EMAIL = "sardor@gmail.com"
PW = "Kuchli-Parol-1"


def register(env, device="phone-1", phone=PHONE, email=EMAIL, pw=PW):
    c = env.client(device)
    c.request_otp("register", phone, email)
    code = c.register(phone, email, env.last_code("otp-phone", phone), env.last_code("otp-email", email), pw)
    return c, code


def test_register_backup_status_restore(env):
    c, code = register(env)
    assert len(code.replace("-", "")) == 32
    assert c.status() == {"file_count": 0, "total_bytes": 0, "last_backup_at": None}

    doc = b"DIPLOM: Hasanov Sardor, 2026" * 100
    r = c.backup(doc, {"name": "diplom.pdf", "category": "document", "mtime": 1700000000})
    assert r["duplicate"] is False
    assert c.backup(doc, {"name": "diplom-nusxa.pdf"}) == {"duplicate": True}  # takror yuklanmaydi
    photo = os.urandom(2_500_000)
    c.backup(photo, {"name": "IMG_1.jpg", "category": "photo"})

    st = c.status()
    assert st["file_count"] == 2 and st["last_backup_at"] > 0
    files = {f["name"]: f for f in c.list_files()}
    assert set(files) == {"diplom.pdf", "IMG_1.jpg"}
    assert c.restore(files["diplom.pdf"]["id"]) == doc
    assert c.restore(files["IMG_1.jpg"]["id"]) == photo


def test_server_stores_no_plaintext(env):
    c, _ = register(env)
    c.backup(b"MAXFIY-MATN-12345" * 50, {"name": "maxfiy-nom.pdf"})
    found = []
    for root, _, names in os.walk(env.data_dir):
        for n in names:
            with open(os.path.join(root, n), "rb") as f:
                raw = f.read()
            for needle in (b"MAXFIY-MATN", b"maxfiy-nom", PW.encode()):
                if needle in raw:
                    found.append((n, needle))
    assert not [x for x in found if x[0] != "outbox.log"], found


def test_login_same_device_and_wrong_password(env):
    c, _ = register(env)
    c.backup(b"abc", {"name": "a.txt"})
    c2 = env.client("phone-1")
    c2.login(PHONE, PW)
    assert c2.list_files()[0]["name"] == "a.txt"
    with pytest.raises(ApiFailure) as e:
        env.client("phone-1").login(PHONE, "boshqa-parol")
    assert e.value.code == "invalid_credentials"


def test_lockout_after_failures(env):
    register(env)
    bad = env.client("phone-1")
    for _ in range(5):
        with pytest.raises(ApiFailure):
            bad.login(PHONE, "xato")
    with pytest.raises(ApiFailure) as e:
        env.client("phone-1").login(PHONE, PW)  # to'g'ri parol ham bloklangan
    assert e.value.status == 423 and e.value.body["retry_after"] > 0


def test_new_device_needs_sms_and_recovery_code(env):
    c, code = register(env)
    c.backup(b"hujjat", {"name": "h.txt"})
    new = env.client("phone-2")
    with pytest.raises(ApiFailure) as e:
        new.login(PHONE, PW)  # faqat parol yetmaydi
    assert e.value.code == "new_device_required"

    new.request_otp("new_device", PHONE)
    sms = env.last_code("otp-phone", PHONE)
    with pytest.raises(ApiFailure) as e:
        new.login(PHONE, PW, phone_code=sms, recovery_code="AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
    assert e.value.code == "bad_code"

    new.request_otp("new_device", PHONE)
    new.login(PHONE, PW, phone_code=env.last_code("otp-phone", PHONE), recovery_code=code)
    assert new.list_files()[0]["name"] == "h.txt"
    assert env.notices(EMAIL), "egasiga email xabari ketishi kerak"
    env.client("phone-2").login(PHONE, PW)  # endi qurilma tanilgan


def test_forgot_password_recovery_keeps_data(env):
    c, code = register(env)
    data = os.urandom(10_000)
    c.backup(data, {"name": "foto.jpg"})

    lost = env.client("phone-9")
    lost.request_otp("recover", PHONE)
    lost.recover(PHONE, env.last_code("otp-phone", PHONE), env.last_code("otp-email", EMAIL), code, "Yangi-Parol-2")
    assert lost.restore(lost.list_files()[0]["id"]) == data

    with pytest.raises(ApiFailure):
        env.client("phone-1").login(PHONE, PW)  # eski parol endi ishlamaydi
    with pytest.raises(ApiFailure):
        c.status()  # eski sessiya yopilgan
    env.client("phone-9").login(PHONE, "Yangi-Parol-2")


def test_recover_with_wrong_recovery_code_fails(env):
    register(env)
    x = env.client("phone-9")
    x.request_otp("recover", PHONE)
    from safevault_client import crypto as C
    with pytest.raises(ApiFailure) as e:
        x.recover(PHONE, env.last_code("otp-phone", PHONE), env.last_code("otp-email", EMAIL),
                  C.new_recovery_code(), "Yangi-Parol-2")
    assert e.value.code == "bad_code"


def test_otp_wrong_code_and_reuse(env):
    c = env.client()
    c.request_otp("register", PHONE, EMAIL)
    pc, ec = env.last_code("otp-phone", PHONE), env.last_code("otp-email", EMAIL)
    with pytest.raises(ApiFailure) as e:
        c.register(PHONE, EMAIL, "000000" if pc != "000000" else "111111", ec, PW)
    assert e.value.code == "bad_code"
    c.register(PHONE, EMAIL, pc, ec, PW)  # to'g'ri kodlar hali ishlaydi
    with pytest.raises(ApiFailure):  # xuddi shu raqam qayta ro'yxatdan o'tolmaydi
        env.client("x").request_otp("register", PHONE, EMAIL)


def test_otp_rate_limit(env):
    c = env.client()
    for _ in range(3):
        c.request_otp("register", PHONE, EMAIL)
    with pytest.raises(ApiFailure) as e:
        c.request_otp("register", PHONE, EMAIL)
    assert e.value.status == 429


def test_users_are_isolated(env):
    a, _ = register(env)
    b, _ = register(env, device="b-phone", phone="+998901112233", email="b@gmail.com", pw="Boshqa-Parol-9")
    a.backup(b"A ning siri", {"name": "a.txt"})
    fid = a.list_files()[0]["id"]
    assert b.list_files() == []
    with pytest.raises(ApiFailure) as e:
        b.restore(fid)
    assert e.value.status == 404


def test_endpoints_require_auth(env):
    c = env.client()
    for call in (c.status, c.list_files, lambda: c.restore("0" * 32), c.get_location):
        with pytest.raises(ApiFailure) as e:
            call()
        assert e.value.status == 401


def test_params_do_not_reveal_whether_phone_exists(env):
    register(env)
    c = env.client()
    real = c._call("GET", "/v1/auth/params?phone=%2B998901234567")
    fake = c._call("GET", "/v1/auth/params?phone=%2B998909999999")
    assert set(real) == set(fake)
    assert fake == c._call("GET", "/v1/auth/params?phone=%2B998909999999")  # barqaror
    import base64
    for k in ("pw_salt", "rec_salt"):  # Dart ham o'qiy olishi uchun: qat'iy (kanonik) base64, 16 bayt
        for v in (real[k], fake[k]):
            raw = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4))
            assert len(raw) == 16 and base64.urlsafe_b64encode(raw).decode().rstrip("=") == v


def test_location_roundtrip_is_encrypted(env):
    c, _ = register(env)
    with pytest.raises(ApiFailure) as e:
        c.get_location()
    assert e.value.status == 404
    c.send_location(41.2995, 69.2401, 25.0, "Toshkent, Amir Temur ko'chasi", battery=7)
    loc = c.get_location()
    assert loc["lat"] == 41.2995 and loc["addr"].startswith("Toshkent") and loc["bat"] == 7
    raw = c._call("GET", "/v1/location")["payload"]
    assert "41.29" not in raw and "Toshkent" not in raw


def test_upload_truncated_and_bad_input(env):
    c, _ = register(env)
    with pytest.raises(ApiFailure) as e:
        c._call("PUT", "/v1/files/" + "a" * 64, data=b"x", headers={})  # X-Meta yo'q
    assert e.value.status == 400
    with pytest.raises(ApiFailure) as e:
        c._call("POST", "/v1/files/missing", {"tags": ["../../etc/passwd"]})
    assert e.value.status == 400
    with pytest.raises(ApiFailure) as e:
        c._call("GET", "/v1/files/../../etc/passwd")
    assert e.value.status in (401, 404)


def test_registration_allowlist(tmp_path, monkeypatch):
    import threading
    from safevault_server.app import create_server
    from safevault_client.client import VaultClient
    monkeypatch.setenv("SAFEVAULT_ALLOWED_PHONES", "+998901234567")
    srv = create_server(str(tmp_path), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = VaultClient(f"http://127.0.0.1:{srv.server_address[1]}", "d")
        c.request_otp("register", "+998901234567", "a@gmail.com")  # ruxsat etilgan
        with pytest.raises(ApiFailure) as e:
            c.request_otp("register", "+998909999999", "b@gmail.com")
        assert e.value.code == "registration_closed"
    finally:
        srv.shutdown()
        srv.server_close()


def test_telegram_delivery_hook(tmp_path, monkeypatch):
    import time
    import urllib.request
    from safevault_server.store import Store
    sent = []

    class Dummy:
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=0):
        sent.append((req.full_url, req.data))
        return Dummy()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("SAFEVAULT_TG_TOKEN", "123:ABC")
    monkeypatch.setenv("SAFEVAULT_TG_CHAT", "555")
    Store(str(tmp_path)).deliver("otp-phone", "+998901234567", "kod: 123456")
    for _ in range(50):
        if sent:
            break
        time.sleep(0.05)
    assert sent and sent[0][0] == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert b"chat_id=555" in sent[0][1] and b"123456" in sent[0][1]
