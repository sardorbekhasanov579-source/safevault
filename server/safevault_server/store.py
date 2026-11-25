"""Ma'lumotlar ombori: SQLite (metama'lumot) + diskdagi shifrlangan bloblar."""
from __future__ import annotations

import contextlib
import base64
import gzip
import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from .s3 import S3, S3Error

DB_KEY = "db/vault.db.gz"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, phone TEXT UNIQUE NOT NULL, email TEXT NOT NULL,
  pw_salt TEXT NOT NULL, rec_salt TEXT NOT NULL, kdf TEXT NOT NULL,
  auth_hash TEXT NOT NULL, rec_hash TEXT NOT NULL,
  wrapped_pw TEXT NOT NULL, wrapped_rec TEXT NOT NULL,
  fails INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS devices(
  user_id TEXT NOT NULL, device_id TEXT NOT NULL, first_seen REAL NOT NULL,
  PRIMARY KEY(user_id, device_id));
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, device_id TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS otps(
  id INTEGER PRIMARY KEY AUTOINCREMENT, purpose TEXT NOT NULL, target TEXT NOT NULL,
  code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reset_tokens(
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS files(
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, content_tag TEXT NOT NULL, meta TEXT NOT NULL,
  size INTEGER NOT NULL, uploaded_at REAL NOT NULL, UNIQUE(user_id, content_tag));
CREATE TABLE IF NOT EXISTS location(
  user_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, target TEXT NOT NULL,
  message TEXT NOT NULL, created_at REAL NOT NULL);
"""


class Store:
    """Ikki rejim: mahalliy (disk) va bulut (S3-mos ombor: bloblar + baza nusxasi). Bulut rejimi SAFEVAULT_S3_* bilan yoqiladi."""

    def __init__(self, data_dir: str):
        self.dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.s3 = S3.from_env()
        self.db_path = os.path.join(data_dir, "vault.db")
        pepper_b64 = os.environ.get("SAFEVAULT_PEPPER_B64", "").strip()
        if pepper_b64:
            self.pepper = base64.b64decode(pepper_b64)
        elif self.s3:
            raise SystemExit("Bulut rejimida SAFEVAULT_PEPPER_B64 kerak (migratsiya skripti uni chiqarib beradi).")
        else:
            key_path = os.path.join(data_dir, "server_secret.key")
            if not os.path.exists(key_path):
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(secrets.token_bytes(32))
            with open(key_path, "rb") as f:
                self.pepper = f.read()
        # bulut: baza nusxasi
        self._seq = threading.Lock()
        self._flush_lock = threading.Lock()
        self._want = 0
        self._done = 0
        if self.s3:
            self._restore_db()
            threading.Thread(target=self._flusher, daemon=True).start()
        else:
            os.makedirs(os.path.join(data_dir, "blobs"), exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)

    # ---- bulut: bazani saqlash ----
    def _restore_db(self):
        data = self.s3.get(DB_KEY)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.db_path + suffix)
            except OSError:
                pass
        if data:
            with open(self.db_path, "wb") as f:
                f.write(gzip.decompress(data))
            print("[store] baza ombordan tiklandi", file=sys.stderr, flush=True)
        else:
            print("[store] omborda baza yo'q: yangi baza ochiladi", file=sys.stderr, flush=True)

    def _snapshot(self) -> bytes:
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=self.dir)
        os.close(fd)
        try:
            src = sqlite3.connect(self.db_path, timeout=30)
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            with open(tmp, "rb") as f:
                return gzip.compress(f.read(), compresslevel=6)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def mark_dirty(self):
        if self.s3:
            with self._seq:
                self._want += 1

    def flush(self):
        """Baza nusxasini omborga yuklaydi (faqat bulut rejimida). Bir vaqtdagi chaqiruvlar birlashtiriladi."""
        if not self.s3:
            return
        with self._seq:
            my = self._want
        with self._flush_lock:
            if self._done >= my:
                return
            with self._seq:
                target = self._want
            self.s3.put(DB_KEY, self._snapshot())
            self._done = target

    def _flusher(self):
        while True:
            time.sleep(3)
            try:
                if self._done < self._want:
                    self.flush()
            except Exception as e:  # noqa: BLE001
                print(f"[store] baza nusxasi yuklanmadi: {type(e).__name__}; keyinroq qayta uriniladi", file=sys.stderr, flush=True)

    @contextlib.contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
            if c.total_changes:
                self.mark_dirty()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    # ---- bloblar ----
    def _blob_key(self, user_id: str, file_id: str) -> str:
        return f"blobs/{user_id}/{file_id}"

    def blob_commit(self, user_id: str, file_id: str, tmp_path: str, size: int, sha256_hex: str):
        """Vaqtinchalik faylni doimiy joyga qo'yadi (mahalliy: os.replace, bulut: omborga yuklaydi va tmp ni o'chiradi)."""
        if self.s3:
            self.s3.put_file(self._blob_key(user_id, file_id), tmp_path, size, sha256_hex)
            os.remove(tmp_path)
        else:
            os.replace(tmp_path, self.blob_path(user_id, file_id))

    def blob_open(self, user_id: str, file_id: str):
        """Baytlar iteratorini qaytaradi. Topilmasa FileNotFoundError."""
        if self.s3:
            try:
                _, it = self.s3.open_stream(self._blob_key(user_id, file_id))
            except S3Error as e:
                if e.status == 404:
                    raise FileNotFoundError(file_id) from e
                raise
            return it

        def local():
            with open(self.blob_path(user_id, file_id), "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    yield chunk

        if not os.path.exists(self.blob_path(user_id, file_id)):
            raise FileNotFoundError(file_id)
        return local()

    def blob_delete(self, user_id: str, file_id: str):
        if self.s3:
            self.s3.delete(self._blob_key(user_id, file_id))
        else:
            try:
                os.remove(self.blob_path(user_id, file_id))
            except OSError:
                pass

    def tmp_path(self, user_id: str, file_id: str) -> str:
        """Yuklanayotgan fayl uchun vaqtinchalik yo'l (mahalliy rejimda blob yonida)."""
        if self.s3:
            d = os.path.join(self.dir, "tmp")
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, file_id + ".part")
        return self.blob_path(user_id, file_id) + ".part"

    # ---- yordamchilar ----
    def mac(self, *parts: str) -> str:
        return hmac.new(self.pepper, "\x1f".join(parts).encode(), hashlib.sha256).hexdigest()

    def fake_salt(self, phone: str, label: str) -> str:
        """Mavjud bo'lmagan raqam uchun ham bir xil ko'rinadigan 'tuz' (foydalanuvchi mavjudligini yashiradi)."""
        raw = bytes.fromhex(self.mac("fake-salt", label, phone))[:16]  # haqiqiy tuz bilan bir xil shakl: 16 bayt, urlsafe base64
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def blob_path(self, user_id: str, file_id: str) -> str:
        d = os.path.join(self.dir, "blobs", user_id)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, file_id)

    # ---- yetkazib berish (dev: konsol + outbox) ----
    def deliver(self, kind: str, target: str, message: str):
        with self.conn() as c:
            c.execute("INSERT INTO outbox(kind,target,message,created_at) VALUES(?,?,?,?)",
                      (kind, target, message, time.time()))
        line = f"[{kind}] -> {target}: {message}"
        print(line, file=sys.stderr, flush=True)
        with open(os.path.join(self.dir, "outbox.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._telegram(f"{target}\n{message}")

    def _telegram(self, text: str):
        """Shaxsiy foydalanish: kodlar egasining Telegram chatiga yuboriladi (SMS provayderi o'rniga).
        SAFEVAULT_TG_TOKEN va SAFEVAULT_TG_CHAT berilgan bo'lsagina ishlaydi."""
        token = os.environ.get("SAFEVAULT_TG_TOKEN")
        chat = os.environ.get("SAFEVAULT_TG_CHAT")
        if not (token and chat):
            return

        def run():
            try:
                data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
                req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
                urllib.request.urlopen(req, timeout=10).read()
            except Exception as e:  # noqa: BLE001  (tokenni xato matniga chiqarmaymiz)
                print(f"[telegram] yuborilmadi: {type(e).__name__}", file=sys.stderr, flush=True)

        threading.Thread(target=run, daemon=True).start()
