"""SafeVault shifrlash yadrosi (telefon tomoni).

Bu modul Dart/Flutter versiyasi uchun andoza (reference). Server hech qachon
parol, tiklash kodi yoki asosiy kalit (MK) ni ko'rmaydi.

Tuzilma:
  MK (32 bayt, tasodifiy)            -- hamma narsani ochadigan asosiy kalit
  parol  --scrypt--> 64 bayt         -- [0:32] KEK_parol (MK ni o'raydi), [32:64] auth_parol (serverga)
  tiklash kodi --HKDF--> 64 bayt     -- [0:32] KEK_tiklash, [32:64] auth_tiklash (serverga)
  fayl: har bir fayl uchun alohida FK, FK ni MK o'raydi, mazmun 1 MiB bo'laklarda ChaCha20-Poly1305.

v0.1 da scrypt ishlatiladi (bu muhitda Argon2id yo'q). Mobil ilovada Argon2id ga o'tish kerak.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DEFAULT_KDF = {"alg": "scrypt", "n": 2**15, "r": 8, "p": 1}
CHUNK = 1024 * 1024
FILE_MAGIC = b"SVF1"
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


class CryptoError(Exception):
    pass


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------- kalit hosil qilish ----------

def new_master_key() -> bytes:
    return os.urandom(32)


def new_salt() -> bytes:
    return os.urandom(16)


def password_keys(password: str, salt: bytes, kdf: dict = DEFAULT_KDF) -> tuple[bytes, bytes]:
    """(kek, auth) qaytaradi. Server faqat auth ning xeshini saqlaydi."""
    if kdf.get("alg") != "scrypt":
        raise CryptoError("noma'lum KDF")
    pw = unicodedata.normalize("NFKC", password).encode()
    raw = hashlib.scrypt(pw, salt=salt, n=kdf["n"], r=kdf["r"], p=kdf["p"],
                         dklen=64, maxmem=256 * 1024 * 1024)
    return raw[:32], raw[32:]


def new_recovery_code() -> str:
    """160 bit tasodifiy kod, ko'rinishi: ABCD-EFGH-... (8 guruh)."""
    raw = os.urandom(20)
    n = int.from_bytes(raw, "big")
    chars = [_B32[(n >> (5 * i)) & 31] for i in range(31, -1, -1)]
    s = "".join(chars)
    return "-".join(s[i:i + 4] for i in range(0, 32, 4))


def _parse_recovery_code(code: str) -> bytes:
    s = code.replace("-", "").replace(" ", "").upper()
    if len(s) != 32 or any(c not in _B32 for c in s):
        raise CryptoError("tiklash kodi noto'g'ri formatda")
    n = 0
    for c in s:
        n = (n << 5) | _B32.index(c)
    return n.to_bytes(20, "big")


def recovery_keys(code: str, salt: bytes) -> tuple[bytes, bytes]:
    raw = HKDF(algorithm=hashes.SHA256(), length=64, salt=salt, info=b"sv-recovery-v1").derive(
        _parse_recovery_code(code))
    return raw[:32], raw[32:]


# ---------- o'rash (wrap) ----------

def wrap(key: bytes, data: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def unwrap(key: bytes, blob: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], aad)
    except Exception as e:  # noqa: BLE001
        raise CryptoError("kalit noto'g'ri yoki ma'lumot buzilgan") from e


# ---------- fayl shifri ----------

def content_tag(mk: bytes, plaintext_sha256: bytes) -> str:
    """Takroriy yuklashni oldini olish uchun: server mazmunni bilmaydi, faqat HMAC ko'radi."""
    k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"sv-tag-v1").derive(mk)
    return hmac.new(k, plaintext_sha256, hashlib.sha256).hexdigest()


def encrypt_file(mk: bytes, data: bytes) -> bytes:
    fk = os.urandom(32)
    prefix = os.urandom(4)
    wrapped = wrap(mk, fk, b"sv-fk")
    out = bytearray(FILE_MAGIC + prefix + struct.pack(">H", len(wrapped)) + wrapped)
    aead = ChaCha20Poly1305(fk)
    total = len(data)
    n_chunks = max(1, -(-total // CHUNK))
    for i in range(n_chunks):
        chunk = data[i * CHUNK:(i + 1) * CHUNK]
        last = i == n_chunks - 1
        nonce = prefix + struct.pack(">Q", i)
        out += aead.encrypt(nonce, chunk, FILE_MAGIC + (b"\x01" if last else b"\x00"))
    return bytes(out)


def decrypt_file(mk: bytes, blob: bytes) -> bytes:
    if blob[:4] != FILE_MAGIC:
        raise CryptoError("fayl formati noto'g'ri")
    prefix = blob[4:8]
    (wl,) = struct.unpack(">H", blob[8:10])
    fk = unwrap(mk, blob[10:10 + wl], b"sv-fk")
    body = blob[10 + wl:]
    aead = ChaCha20Poly1305(fk)
    step = CHUNK + 16
    out = bytearray()
    pos, i = 0, 0
    while True:
        remaining = len(body) - pos
        if remaining < 16:
            raise CryptoError("fayl kesilgan")
        last = remaining <= step
        piece = body[pos:pos + (remaining if last else step)]
        nonce = prefix + struct.pack(">Q", i)
        try:
            out += aead.decrypt(nonce, piece, FILE_MAGIC + (b"\x01" if last else b"\x00"))
        except Exception as e:  # noqa: BLE001
            raise CryptoError("fayl buzilgan yoki kesilgan") from e
        if last:
            return bytes(out)
        pos += step
        i += 1


def encrypt_json(mk: bytes, obj: dict, aad: bytes) -> str:
    return b64e(wrap(mk, json.dumps(obj, ensure_ascii=False).encode(), aad))


def decrypt_json(mk: bytes, s: str, aad: bytes) -> dict:
    return json.loads(unwrap(mk, b64d(s), aad))
