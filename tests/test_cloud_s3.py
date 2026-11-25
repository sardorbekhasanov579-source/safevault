"""Bulut rejimi: S3-mos omborda bloblar va baza nusxasi. Haqiqiy ombor o'rniga sun'iy S3 server (imzoni tekshiradi)."""
import base64
import hashlib
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from safevault_client.client import VaultClient
from safevault_server.app import create_server
from safevault_server.s3 import S3, S3Error, sign_v4

KEY_ID, SECRET, BUCKET, REGION = "AKIATESTKEY", "test-secret-key", "vault-bucket", "us-west-004"
PHONE, EMAIL, PW = "+998901234567", "sardor@gmail.com", "Kuchli-Parol-1"


class FakeS3(BaseHTTPRequestHandler):
    objects: dict = {}
    bad_signatures = 0

    def log_message(self, *a):
        pass

    def _check(self, body_hash: str) -> bool:
        auth = self.headers.get("Authorization", "")
        m = re.match(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, SignedHeaders=([^,]+), Signature=([0-9a-f]+)", auth)
        ok = bool(m) and m.group(1) == KEY_ID
        if ok:
            names = m.group(4).split(";")
            extra = {n: self.headers[n] for n in names if n not in ("host", "x-amz-date", "x-amz-content-sha256")}
            want = sign_v4(self.command, self.headers["Host"], self.path, {}, extra, body_hash, KEY_ID, SECRET,
                           m.group(3), self.headers["x-amz-date"])
            ok = want == auth and self.headers["x-amz-content-sha256"] == body_hash
        if not ok:
            type(self).bad_signatures += 1
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
        return ok

    def do_PUT(self):
        n = int(self.headers["Content-Length"])
        body = self.rfile.read(n)
        if not self._check(hashlib.sha256(body).hexdigest()):
            return
        self.objects[self.path] = body
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._check(hashlib.sha256(b"").hexdigest()):
            return
        body = self.objects.get(self.path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        if not self._check(hashlib.sha256(b"").hexdigest()):
            return
        self.objects.pop(self.path, None)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture()
def fake_s3(monkeypatch):
    FakeS3.objects = {}
    FakeS3.bad_signatures = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeS3)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SAFEVAULT_S3_ENDPOINT", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("SAFEVAULT_S3_BUCKET", BUCKET)
    monkeypatch.setenv("SAFEVAULT_S3_KEY_ID", KEY_ID)
    monkeypatch.setenv("SAFEVAULT_S3_SECRET", SECRET)
    monkeypatch.setenv("SAFEVAULT_S3_REGION", REGION)
    monkeypatch.setenv("SAFEVAULT_PEPPER_B64", base64.b64encode(b"p" * 32).decode())
    yield FakeS3
    srv.shutdown()
    srv.server_close()


def start(data_dir):
    srv = create_server(str(data_dir), "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def otp(data_dir, kind, target):
    import sqlite3
    con = sqlite3.connect(os.path.join(str(data_dir), "vault.db"))
    row = con.execute("SELECT message FROM outbox WHERE kind=? AND target=? ORDER BY id DESC LIMIT 1", (kind, target)).fetchone()
    con.close()
    return re.search(r"(\d{6})", row[0]).group(1)


def register(url, data_dir):
    c = VaultClient(url, "phone-1")
    c.request_otp("register", PHONE, EMAIL)
    c.register(PHONE, EMAIL, otp(data_dir, "otp-phone", PHONE), otp(data_dir, "otp-email", EMAIL), PW)
    return c


def test_sigv4_matches_aws_documented_example():
    a = sign_v4("GET", "examplebucket.s3.amazonaws.com", "/test.txt", {}, {"Range": "bytes=0-9"},
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", "20130524T000000Z")
    assert a.endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


def test_s3_client_put_get_delete(fake_s3):
    s3 = S3.from_env()
    assert s3.region == REGION
    s3.put("a/b.txt", b"salom")
    assert s3.get("a/b.txt") == b"salom"
    assert s3.get("yoq") is None
    size, it = s3.open_stream("a/b.txt")
    assert size == 5 and b"".join(it) == b"salom"
    with pytest.raises(S3Error) as e:
        s3.open_stream("yoq")
    assert e.value.status == 404
    s3.delete("a/b.txt")
    assert s3.get("a/b.txt") is None
    assert fake_s3.bad_signatures == 0


def test_cloud_backup_restore_roundtrip(fake_s3, tmp_path):
    srv, url = start(tmp_path)
    c = register(url, tmp_path)
    photo = os.urandom(2_500_000)
    r = c.backup(photo, {"name": "IMG_1.jpg", "category": "photo"})
    assert r["duplicate"] is False
    assert c.backup(photo, {"name": "nusxa.jpg"}) == {"duplicate": True}
    f = c.list_files()[0]
    assert c.restore(f["id"]) == photo
    blobs = [k for k in fake_s3.objects if "/blobs/" in k]
    assert len(blobs) == 1  # takroriy fayl omborga ikkinchi marta yozilmadi
    assert any(k.endswith("/db/vault.db.gz") for k in fake_s3.objects)
    # mahalliy diskda blob qolmaydi
    local = [n for _, _, names in os.walk(tmp_path) for n in names if n.endswith((".part",)) or len(n) == 32]
    assert not local, local
    # omborda ochiq matn yo'q
    assert b"IMG_1.jpg" not in b"".join(v for k, v in fake_s3.objects.items() if "/blobs/" in k)
    assert fake_s3.bad_signatures == 0
    srv.shutdown()
    srv.server_close()


def test_cloud_survives_restart_with_empty_disk(fake_s3, tmp_path):
    d1, d2 = tmp_path / "one", tmp_path / "two"
    d1.mkdir()
    d2.mkdir()
    srv, url = start(d1)
    c = register(url, d1)
    c.backup(b"DIPLOM" * 1000, {"name": "diplom.pdf", "category": "document"})
    srv.shutdown()
    srv.server_close()
    # yangi (bo'sh) disk: Render qayta ishga tushganini taqlid qiladi
    srv2, url2 = start(d2)
    c2 = VaultClient(url2, "phone-1")
    c2.login(PHONE, PW)
    files = c2.list_files()
    assert [f["name"] for f in files] == ["diplom.pdf"]
    assert c2.restore(files[0]["id"]) == b"DIPLOM" * 1000
    srv2.shutdown()
    srv2.server_close()


def test_cloud_mode_requires_pepper(fake_s3, tmp_path, monkeypatch):
    monkeypatch.delenv("SAFEVAULT_PEPPER_B64")
    with pytest.raises(SystemExit):
        create_server(str(tmp_path), "127.0.0.1", 0)


# ---------------- Agent: omborda shifrlangan holat va webhook ----------------
def _agent_env(monkeypatch, home):
    import json as _j
    data = {"server": "http://127.0.0.1:1", "token": "t", "mk": "bQ", "device_id": "d", "tg_token": "x", "owner_chat": 5}
    monkeypatch.setenv("SAFEVAULT_AGENT_HOME", str(home))
    monkeypatch.setenv("SAFEVAULT_AGENT_STATE_B64", base64.b64encode(_j.dumps(data).encode()).decode())
    monkeypatch.delenv("SAFEVAULT_AGENT_SERVER", raising=False)
    return data


def test_agent_state_persists_encrypted_in_bucket(fake_s3, tmp_path, monkeypatch):
    from safevault_agent import cloud
    _agent_env(monkeypatch, tmp_path / "a")
    st = cloud.load_state()
    assert st.ready
    st.set(owner_chat=77, pin={"salt": "aa", "hash": "bb"})
    blob = next(v for k, v in fake_s3.objects.items() if k.endswith("/agent/state.enc"))
    assert b"tg_token" not in blob and b"owner_chat" not in blob  # ochiq matn yo'q
    # Render qayta ishga tushdi: disk bo'sh, muhit qiymati eski, ombordagi holat g'olib
    _agent_env(monkeypatch, tmp_path / "b")
    st2 = cloud.load_state()
    assert st2.get("owner_chat") == 77 and st2.get("pin") == {"salt": "aa", "hash": "bb"}
    # boshqa pepper bilan ochib bo'lmaydi: muhit qiymatiga qaytiladi
    monkeypatch.setenv("SAFEVAULT_PEPPER_B64", base64.b64encode(b"q" * 32).decode())
    _agent_env(monkeypatch, tmp_path / "c")
    assert cloud.load_state().get("owner_chat") == 5


def test_webhook_route_checks_secret_and_dedupes(fake_s3, tmp_path, monkeypatch):
    import json as _j
    import time
    import urllib.request
    from safevault_agent import cloud
    _agent_env(monkeypatch, tmp_path / "a")
    got = []

    class FakeTg:
        def set_commands(self, c): pass
        def set_webhook(self, url, secret): got.append(("hook", url, secret))

    class FakeBot:
        tg = FakeTg()
        def keepalive_tick(self): pass
        def handle_update(self, upd): got.append(("upd", upd["update_id"]))

    monkeypatch.setattr(cloud, "_make_bot", lambda st: FakeBot())
    srv, url = start(tmp_path / "srv")
    assert cloud.start_webhook(srv.svc, "https://safevault.example.com/")
    secret = cloud.webhook_secret(srv.svc.s.pepper)

    def post(path, upd, header=None):
        req = urllib.request.Request(url + path, _j.dumps(upd).encode(), {"Content-Type": "application/json", **({"X-Telegram-Bot-Api-Secret-Token": header} if header else {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    assert post(f"/tg/{secret}", {"update_id": 1}, "noto'g'ri") == 404
    assert post("/tg/boshqa", {"update_id": 1}, secret) == 404
    assert post(f"/tg/{secret}", {"update_id": 10}, secret) == 200
    assert post(f"/tg/{secret}", {"update_id": 10}, secret) == 200  # Telegram qayta yuborsa
    assert post(f"/tg/{secret}", {"update_id": 11}, secret) == 200
    for _ in range(50):
        if ("upd", 11) in got:
            break
        time.sleep(0.1)
    assert [g for g in got if g[0] == "upd"] == [("upd", 10), ("upd", 11)]
    assert ("hook", f"https://safevault.example.com/tg/{secret}", secret) in got
    srv.shutdown()
    srv.server_close()


ENDPOINT_BACKUP = {}


def test_migrate_local_data_to_cloud(fake_s3, tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy"))
    import migrate_to_cloud
    monkeypatch.delenv("SAFEVAULT_PEPPER_B64")  # mahalliy server: pepper fayldan
    ENDPOINT_BACKUP["v"] = os.environ["SAFEVAULT_S3_ENDPOINT"]
    for k in [k for k in os.environ if k.startswith("SAFEVAULT_S3_")]:
        monkeypatch.delenv(k)
    local = tmp_path / "local"
    srv, url = start(local)
    c = register(url, local)
    c.backup(b"RASM" * 5000, {"name": "a.jpg", "category": "photo"})
    c.backup(b"PDF!" * 3000, {"name": "b.pdf", "category": "document"})
    srv.shutdown()
    srv.server_close()
    # ko'chirish
    s3_endpoint = ENDPOINT_BACKUP["v"]
    for k, v in {"SAFEVAULT_S3_ENDPOINT": s3_endpoint, "SAFEVAULT_S3_BUCKET": BUCKET,
                 "SAFEVAULT_S3_KEY_ID": KEY_ID, "SAFEVAULT_S3_SECRET": SECRET, "SAFEVAULT_S3_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    pepper = migrate_to_cloud.migrate(str(local), S3.from_env(), log=lambda *_: None)
    with pytest.raises(SystemExit):  # ikkinchi marta ustiga yozmaydi
        migrate_to_cloud.migrate(str(local), S3.from_env(), log=lambda *_: None)
    # yangi, bo'sh diskda, ko'chirilgan pepper bilan
    monkeypatch.setenv("SAFEVAULT_PEPPER_B64", pepper)
    srv2, url2 = start(tmp_path / "render")
    c2 = VaultClient(url2, "phone-1")
    c2.login(PHONE, PW)
    names = sorted(f["name"] for f in c2.list_files())
    assert names == ["a.jpg", "b.pdf"]
    assert c2.restore([f for f in c2.list_files() if f["name"] == "b.pdf"][0]["id"]) == b"PDF!" * 3000
    srv2.shutdown()
    srv2.server_close()
