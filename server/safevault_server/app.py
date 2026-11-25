"""SafeVault serveri v0.1 — faqat Python standart kutubxonasi bilan.

Server shifrlangan bloblarni saqlaydi va hisob/tiklash oqimini boshqaradi.
Parol, tiklash kodi va asosiy kalit serverga hech qachon kelmaydi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .store import Store

MAX_JSON = 1 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
OTP_TTL = 600
OTP_MAX_ATTEMPTS = 5
OTP_MAX_ACTIVE = 3
LOCK_AFTER = 5
LOCK_SECONDS = 15 * 60
SESSION_TTL = 30 * 24 * 3600
PHONE_RE = re.compile(r"^\+\d{9,15}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TAG_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")


class ApiError(Exception):
    def __init__(self, status: int, code: str, **extra):
        self.status, self.code, self.extra = status, code, extra


def _need(body: dict, *names: str):
    for n in names:
        if not isinstance(body.get(n), str) or not body[n]:
            raise ApiError(400, "bad_request", field=n)


class Service:
    def __init__(self, store: Store):
        self.s = store
        raw = os.environ.get("SAFEVAULT_ALLOWED_PHONES", "")
        self.allowed = {p.strip() for p in raw.split(",") if p.strip()}  # bo'sh = hamma ro'yxatdan o'ta oladi
        self.webhook = None  # bulut rejimi: funksiya(path, headers, body) -> bool (Telegram webhook)

    def _check_allowed(self, phone: str):
        if self.allowed and phone not in self.allowed:
            raise ApiError(403, "registration_closed")

    # ---------- OTP ----------
    def send_otp(self, purpose: str, kind: str, target: str):
        now = time.time()
        key = f"{kind}:{target}"
        with self.s.conn() as c:
            active = c.execute("SELECT COUNT(*) n FROM otps WHERE purpose=? AND target=? AND expires>?",
                               (purpose, key, now)).fetchone()["n"]
            if active >= OTP_MAX_ACTIVE:
                raise ApiError(429, "too_many_codes")
            code = f"{secrets.randbelow(10**6):06d}"
            c.execute("INSERT INTO otps(purpose,target,code_hash,expires) VALUES(?,?,?,?)",
                      (purpose, key, self.s.mac("otp", purpose, key, code), now + OTP_TTL))
        self.s.deliver(f"otp-{kind}", target, f"SafeVault tasdiqlash kodi: {code} (10 daqiqa amal qiladi)")

    def check_otp(self, purpose: str, kind: str, target: str, code: str, consume: bool = True) -> bool:
        """consume=False: faqat tekshiradi (noto'g'ri bo'lsa urinish hisoblanadi, to'g'ri bo'lsa kod sarflanmaydi)."""
        now = time.time()
        key = f"{kind}:{target}"
        with self.s.conn() as c:
            row = c.execute("SELECT * FROM otps WHERE purpose=? AND target=? AND used=0 AND expires>? "
                            "ORDER BY id DESC LIMIT 1", (purpose, key, now)).fetchone()
            if not row or row["attempts"] >= OTP_MAX_ATTEMPTS:
                return False
            ok = hmac.compare_digest(row["code_hash"], self.s.mac("otp", purpose, key, str(code)))
            if ok:
                if consume:
                    c.execute("UPDATE otps SET used=1 WHERE id=?", (row["id"],))
            else:
                c.execute("UPDATE otps SET attempts=attempts+1 WHERE id=?", (row["id"],))
            return ok

    # ---------- foydalanuvchi / sessiya ----------
    def user_by_phone(self, phone: str):
        with self.s.conn() as c:
            return c.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()

    def new_session(self, user_id: str, device_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.s.conn() as c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                      (hashlib.sha256(token.encode()).hexdigest(), user_id, device_id, time.time() + SESSION_TTL))
        self.s.flush()  # bulut rejimi: hisob/sessiya darrov omborga yoziladi (mahalliy rejimda hech narsa qilmaydi)
        return token

    def auth(self, header: str | None):
        if not header or not header.startswith("Bearer "):
            raise ApiError(401, "unauthorized")
        th = hashlib.sha256(header[7:].encode()).hexdigest()
        with self.s.conn() as c:
            row = c.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires>?",
                            (th, time.time())).fetchone()
            if row:  # ishlatilgan sessiya muddati uzayadi (fon zaxirasi uzoq vaqt ishlashi uchun)
                c.execute("UPDATE sessions SET expires=? WHERE token_hash=?", (time.time() + SESSION_TTL, th))
        if not row:
            raise ApiError(401, "unauthorized")
        return row["user_id"]

    def _secret_hash(self, user_id: str, label: str, secret: str) -> str:
        return self.s.mac("secret", user_id, label, secret)

    def _register_failure(self, user_id: str):
        with self.s.conn() as c:
            row = c.execute("SELECT fails FROM users WHERE id=?", (user_id,)).fetchone()
            fails = row["fails"] + 1
            locked = time.time() + LOCK_SECONDS if fails >= LOCK_AFTER else 0
            c.execute("UPDATE users SET fails=?, locked_until=? WHERE id=?",
                      (0 if locked else fails, locked, user_id))

    def _check_lock(self, user):
        left = user["locked_until"] - time.time()
        if left > 0:
            raise ApiError(423, "locked", retry_after=int(left) + 1)

    def _clear_failures(self, user_id: str):
        with self.s.conn() as c:
            c.execute("UPDATE users SET fails=0, locked_until=0 WHERE id=?", (user_id,))

    # ---------- auth endpointlari ----------
    def params(self, q: dict):
        phone = q.get("phone", "")
        if not PHONE_RE.match(phone):
            raise ApiError(400, "bad_request", field="phone")
        u = self.user_by_phone(phone)
        if u:
            return {"pw_salt": u["pw_salt"], "rec_salt": u["rec_salt"], "kdf": json.loads(u["kdf"])}
        return {"pw_salt": self.s.fake_salt(phone, "pw"), "rec_salt": self.s.fake_salt(phone, "rec"),
                "kdf": {"alg": "scrypt", "n": 2**15, "r": 8, "p": 1}}

    def otp_request(self, b: dict):
        _need(b, "purpose", "phone")
        phone = b["phone"]
        if not PHONE_RE.match(phone):
            raise ApiError(400, "bad_request", field="phone")
        purpose = b["purpose"]
        if purpose == "register":
            _need(b, "email")
            if not EMAIL_RE.match(b["email"]):
                raise ApiError(400, "bad_request", field="email")
            self._check_allowed(phone)
            if self.user_by_phone(phone):
                raise ApiError(409, "phone_taken")
            self.send_otp("register", "phone", phone)
            self.send_otp("register", "email", b["email"])
        elif purpose in ("new_device", "recover"):
            u = self.user_by_phone(phone)
            if u:  # mavjudligini oshkor qilmaymiz: javob har doim bir xil
                self.send_otp(purpose, "phone", phone)
                if purpose == "recover":
                    self.send_otp("recover", "email", u["email"])
        else:
            raise ApiError(400, "bad_request", field="purpose")
        return {"ok": True}

    def register(self, b: dict):
        _need(b, "phone", "email", "phone_code", "email_code", "pw_salt", "rec_salt",
              "auth", "rec_auth", "wrapped_pw", "wrapped_rec", "device_id")
        if not isinstance(b.get("kdf"), dict):
            raise ApiError(400, "bad_request", field="kdf")
        if not PHONE_RE.match(b["phone"]) or not EMAIL_RE.match(b["email"]):
            raise ApiError(400, "bad_request")
        self._check_allowed(b["phone"])
        if self.user_by_phone(b["phone"]):
            raise ApiError(409, "phone_taken")
        ok_p = self.check_otp("register", "phone", b["phone"], b["phone_code"], consume=False)
        ok_e = self.check_otp("register", "email", b["email"], b["email_code"], consume=False)
        if not (ok_p and ok_e):
            raise ApiError(403, "bad_code")
        self.check_otp("register", "phone", b["phone"], b["phone_code"])
        self.check_otp("register", "email", b["email"], b["email_code"])
        uid = uuid.uuid4().hex
        now = time.time()
        try:
            with self.s.conn() as c:
                c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?,0,0,?)",
                          (uid, b["phone"], b["email"], b["pw_salt"], b["rec_salt"], json.dumps(b["kdf"]),
                           self._secret_hash(uid, "pw", b["auth"]), self._secret_hash(uid, "rec", b["rec_auth"]),
                           b["wrapped_pw"], b["wrapped_rec"], now))
                c.execute("INSERT INTO devices VALUES(?,?,?)", (uid, b["device_id"], now))
        except Exception as e:  # UNIQUE
            raise ApiError(409, "phone_taken") from e
        return {"token": self.new_session(uid, b["device_id"]), "user_id": uid}

    def login(self, b: dict):
        _need(b, "phone", "auth", "device_id")
        u = self.user_by_phone(b["phone"])
        if not u:
            raise ApiError(401, "invalid_credentials")
        self._check_lock(u)
        if not hmac.compare_digest(u["auth_hash"], self._secret_hash(u["id"], "pw", b["auth"])):
            self._register_failure(u["id"])
            raise ApiError(401, "invalid_credentials")
        with self.s.conn() as c:
            known = c.execute("SELECT 1 FROM devices WHERE user_id=? AND device_id=?",
                              (u["id"], b["device_id"])).fetchone()
        if not known:
            if not b.get("phone_code") or not b.get("rec_auth"):
                raise ApiError(403, "new_device_required", need=["phone_code", "rec_auth"])
            rec_ok = hmac.compare_digest(u["rec_hash"], self._secret_hash(u["id"], "rec", str(b["rec_auth"])))
            otp_ok = rec_ok and self.check_otp("new_device", "phone", u["phone"], str(b["phone_code"]))
            if not (rec_ok and otp_ok):
                self._register_failure(u["id"])
                raise ApiError(403, "bad_code")
            with self.s.conn() as c:
                c.execute("INSERT OR IGNORE INTO devices VALUES(?,?,?)", (u["id"], b["device_id"], time.time()))
            self.s.deliver("notice-email", u["email"], "SafeVault: hisobingizga yangi qurilmadan kirildi.")
        self._clear_failures(u["id"])
        return {"token": self.new_session(u["id"], b["device_id"]), "user_id": u["id"],
                "wrapped_pw": u["wrapped_pw"], "pw_salt": u["pw_salt"], "kdf": json.loads(u["kdf"])}

    def recover_start(self, b: dict):
        _need(b, "phone", "phone_code", "email_code", "rec_auth")
        u = self.user_by_phone(b["phone"])
        if not u:
            raise ApiError(403, "bad_code")
        self._check_lock(u)
        rec_ok = hmac.compare_digest(u["rec_hash"], self._secret_hash(u["id"], "rec", b["rec_auth"]))
        p_ok = self.check_otp("recover", "phone", u["phone"], b["phone_code"], consume=False)
        e_ok = self.check_otp("recover", "email", u["email"], b["email_code"], consume=False)
        if not (rec_ok and p_ok and e_ok):
            self._register_failure(u["id"])
            raise ApiError(403, "bad_code")
        self.check_otp("recover", "phone", u["phone"], b["phone_code"])
        self.check_otp("recover", "email", u["email"], b["email_code"])
        token = secrets.token_urlsafe(32)
        with self.s.conn() as c:
            c.execute("INSERT INTO reset_tokens VALUES(?,?,?)",
                      (hashlib.sha256(token.encode()).hexdigest(), u["id"], time.time() + OTP_TTL))
        return {"reset_token": token, "wrapped_rec": u["wrapped_rec"], "rec_salt": u["rec_salt"]}

    def reset_password(self, b: dict):
        _need(b, "reset_token", "device_id", "pw_salt", "auth", "wrapped_pw")
        if not isinstance(b.get("kdf"), dict):
            raise ApiError(400, "bad_request", field="kdf")
        th = hashlib.sha256(b["reset_token"].encode()).hexdigest()
        with self.s.conn() as c:
            row = c.execute("SELECT user_id FROM reset_tokens WHERE token_hash=? AND expires>?",
                            (th, time.time())).fetchone()
            if not row:
                raise ApiError(403, "bad_token")
            uid = row["user_id"]
            c.execute("DELETE FROM reset_tokens WHERE token_hash=?", (th,))
            c.execute("UPDATE users SET pw_salt=?, kdf=?, auth_hash=?, wrapped_pw=?, fails=0, locked_until=0 "
                      "WHERE id=?", (b["pw_salt"], json.dumps(b["kdf"]),
                                     self._secret_hash(uid, "pw", b["auth"]), b["wrapped_pw"], uid))
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            c.execute("DELETE FROM devices WHERE user_id=?", (uid,))
            c.execute("INSERT INTO devices VALUES(?,?,?)", (uid, b["device_id"], time.time()))
            email = c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()["email"]
        self.s.deliver("notice-email", email, "SafeVault: parol tiklash kodi orqali o'zgartirildi, barcha qurilmalar chiqarildi.")
        return {"token": self.new_session(uid, b["device_id"]), "user_id": uid}

    # ---------- fayllar ----------
    def files_missing(self, uid: str, b: dict):
        tags = b.get("tags")
        if not isinstance(tags, list) or len(tags) > 5000 or not all(isinstance(t, str) and TAG_RE.match(t) for t in tags):
            raise ApiError(400, "bad_request", field="tags")
        with self.s.conn() as c:
            have = {r["content_tag"] for r in c.execute("SELECT content_tag FROM files WHERE user_id=?", (uid,))}
        return {"missing": [t for t in tags if t not in have]}

    def files_list(self, uid: str):
        with self.s.conn() as c:
            rows = c.execute("SELECT id,content_tag,meta,size,uploaded_at FROM files WHERE user_id=? "
                             "ORDER BY uploaded_at", (uid,)).fetchall()
        return {"files": [dict(r) for r in rows]}

    def status(self, uid: str):
        with self.s.conn() as c:
            r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(size),0) b, MAX(uploaded_at) last FROM files "
                          "WHERE user_id=?", (uid,)).fetchone()
        return {"file_count": r["n"], "total_bytes": r["b"], "last_backup_at": r["last"]}

    def location_put(self, uid: str, b: dict):
        _need(b, "payload")
        if len(b["payload"]) > 4096:
            raise ApiError(413, "too_large")
        with self.s.conn() as c:
            c.execute("INSERT INTO location VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                      "payload=excluded.payload, updated_at=excluded.updated_at", (uid, b["payload"], time.time()))
        return {"ok": True}

    def location_get(self, uid: str):
        with self.s.conn() as c:
            r = c.execute("SELECT payload, updated_at FROM location WHERE user_id=?", (uid,)).fetchone()
        if not r:
            raise ApiError(404, "no_location")
        return {"payload": r["payload"], "updated_at": r["updated_at"]}


def make_handler(svc: Service):
    store = svc.s

    class Handler(BaseHTTPRequestHandler):
        server_version = "SafeVault/0.1"

        def log_message(self, fmt, *args):  # shovqinni kamaytirish
            pass

        # -- yordamchilar --
        def _json_out(self, status: int, obj: dict):
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_JSON:
                raise ApiError(413, "too_large")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                obj = json.loads(raw or b"{}")
            except ValueError as e:
                raise ApiError(400, "bad_json") from e
            if not isinstance(obj, dict):
                raise ApiError(400, "bad_json")
            return obj

        def _dispatch(self, method: str):
            try:
                path, _, qs = self.path.partition("?")
                q = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
                from urllib.parse import unquote
                q = {k: unquote(v) for k, v in q.items()}
                if method == "GET" and path == "/v1/health":
                    return self._json_out(200, {"ok": True, "version": "0.1"})
                if method == "GET" and path == "/v1/auth/params":
                    return self._json_out(200, svc.params(q))
                if method == "POST" and path.startswith("/tg/") and svc.webhook:
                    if not svc.webhook(path, self.headers, self._body()):
                        raise ApiError(404, "not_found")
                    return self._json_out(200, {"ok": True})
                if method == "POST":
                    simple = {"/v1/auth/otp": svc.otp_request, "/v1/auth/register": svc.register,
                              "/v1/auth/login": svc.login, "/v1/auth/recover": svc.recover_start,
                              "/v1/auth/reset": svc.reset_password}
                    if path in simple:
                        return self._json_out(200, simple[path](self._body()))
                # ---- quyidagilar kirishni talab qiladi ----
                uid = svc.auth(self.headers.get("Authorization"))
                if method == "POST" and path == "/v1/files/missing":
                    return self._json_out(200, svc.files_missing(uid, self._body()))
                if method == "GET" and path == "/v1/files":
                    return self._json_out(200, svc.files_list(uid))
                if method == "GET" and path == "/v1/status":
                    return self._json_out(200, svc.status(uid))
                if method == "POST" and path == "/v1/location":
                    return self._json_out(200, svc.location_put(uid, self._body()))
                if method == "GET" and path == "/v1/location":
                    return self._json_out(200, svc.location_get(uid))
                m = re.fullmatch(r"/v1/files/([0-9a-f]{64})", path)
                if method == "PUT" and m:
                    return self._put_file(uid, m.group(1))
                m = re.fullmatch(r"/v1/files/([0-9a-f]{32})", path)
                if method == "GET" and m:
                    return self._get_file(uid, m.group(1))
                raise ApiError(404, "not_found")
            except ApiError as e:
                self._json_out(e.status, {"error": e.code, **e.extra})
            except Exception as e:  # noqa: BLE001
                import sys, traceback
                traceback.print_exc(file=sys.stderr)
                self._json_out(500, {"error": "server_error"})

        def _put_file(self, uid: str, tag: str):
            meta = self.headers.get("X-Meta", "")
            if not meta or len(meta) > 8192:
                raise ApiError(400, "bad_request", field="X-Meta")
            n = int(self.headers.get("Content-Length") or -1)
            if n < 0:
                raise ApiError(411, "length_required")
            if n > MAX_FILE:
                raise ApiError(413, "too_large")
            fid = uuid.uuid4().hex
            tmp = store.tmp_path(uid, fid)
            left = n
            digest = hashlib.sha256()
            try:
                with open(tmp, "wb") as f:
                    while left:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            raise ApiError(400, "truncated_upload")
                        f.write(chunk)
                        digest.update(chunk)
                        left -= len(chunk)
                with store.conn() as c:
                    dup = c.execute("SELECT id FROM files WHERE user_id=? AND content_tag=?", (uid, tag)).fetchone()
                if dup:
                    return self._json_out(200, {"id": dup["id"], "duplicate": True})
                store.blob_commit(uid, fid, tmp, n, digest.hexdigest())
                try:
                    with store.conn() as c:
                        c.execute("INSERT INTO files VALUES(?,?,?,?,?,?)", (fid, uid, tag, meta, n, time.time()))
                except sqlite3.IntegrityError:  # xuddi shu fayl bir vaqtda ikki marta yuborilgan
                    store.blob_delete(uid, fid)
                    with store.conn() as c:
                        dup = c.execute("SELECT id FROM files WHERE user_id=? AND content_tag=?", (uid, tag)).fetchone()
                    return self._json_out(200, {"id": dup["id"], "duplicate": True})
                store.flush()  # fayl metama'lumoti omborga yozilmaguncha telefonga "saqlandi" demaymiz
                self._json_out(201, {"id": fid, "duplicate": False})
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

        def _get_file(self, uid: str, fid: str):
            with store.conn() as c:
                r = c.execute("SELECT size FROM files WHERE id=? AND user_id=?", (fid, uid)).fetchone()
            if not r:
                raise ApiError(404, "not_found")
            try:
                chunks = store.blob_open(uid, fid)
            except FileNotFoundError:
                raise ApiError(404, "not_found")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(r["size"]))
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(chunk)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

    return Handler


def create_server(data_dir: str, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    svc = Service(Store(data_dir))
    srv = ThreadingHTTPServer((host, port), make_handler(svc))
    srv.daemon_threads = True
    srv.svc = svc
    return srv


def main():
    data = os.environ.get("SAFEVAULT_DATA", "./data")
    host = os.environ.get("SAFEVAULT_HOST", "127.0.0.1")
    port = int(os.environ.get("SAFEVAULT_PORT", "8080"))
    srv = create_server(data, host, port)
    print(f"SafeVault server: http://{host}:{port}  (ma'lumotlar: {os.path.abspath(data)})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
