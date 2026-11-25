"""Agent holati: server ulanishi, Telegram sozlamalari, egasi (chat_id). Fayl: ~/.safevault_agent/state.json

DIQQAT: bu faylda shifrlash kaliti (mk) va Telegram tokeni bor — uni hech kimga bermang.
Agent faqat sizning shaxsiy kompyuteringiz yoki serveringizda ishlaydi."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time


def home_dir() -> str:
    return os.environ.get("SAFEVAULT_AGENT_HOME") or os.path.join(os.path.expanduser("~"), ".safevault_agent")


def new_pairing_code() -> str:
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))


def hash_pin(pin: str, salt: bytes | None = None) -> dict:
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return {"salt": salt.hex(), "hash": h.hex()}


def check_pin(pin: str, stored: dict) -> bool:
    h = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(stored["salt"]), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(h.hex(), stored["hash"])


class State:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(home_dir(), "state.json")
        self.remote = None  # bulut rejimi: save() dan keyin chaqiriladigan funksiya(bytes) — holat omborga ham yoziladi
        self.d: dict = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.d = json.load(f)

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, **kw):
        self.d.update(kw)
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.d, f)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        if self.remote:
            self.remote(json.dumps(self.d).encode())

    @property
    def ready(self) -> bool:
        return all(self.d.get(k) for k in ("server", "token", "mk", "device_id", "tg_token"))
