"""Python yadrosidan Dart testlari uchun vektorlar yaratadi: python tests/gen_vectors.py"""
import hashlib, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "client"))
from safevault_client import crypto as C

salt = bytes(range(16))
kek, auth = C.password_keys("Parol-123", salt)
code = "ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ23-4567"
rsalt = bytes(range(16, 32))
rkek, rauth = C.recovery_keys(code, rsalt)
wkey = bytes(range(32, 64))
wblob = C.wrap(wkey, b"asosiy kalit 32 bayt........", b"sv-mk")
mk = bytes(range(64, 96))
plain = "Salom, dunyo! Diplom №1".encode()
fblob = C.encrypt_file(mk, plain)
big = bytes((i * 7) % 251 for i in range(C.CHUNK + 5))  # 2 bo'lak
bigblob = C.encrypt_file(mk, big)
sha = hashlib.sha256(plain).digest()
meta = {"name": "diplom.pdf", "category": "document", "mtime": 1700000000}

v = {
  "password": {"password": "Parol-123", "salt": salt.hex(), "kdf": C.DEFAULT_KDF, "kek": kek.hex(), "auth": auth.hex()},
  "recovery": {"code": code, "salt": rsalt.hex(), "kek": rkek.hex(), "auth": rauth.hex()},
  "wrap": {"key": wkey.hex(), "aad": "sv-mk", "plaintext": b"asosiy kalit 32 bayt........".hex(), "blob": wblob.hex()},
  "file": {"mk": mk.hex(), "plaintext": plain.hex(), "blob": fblob.hex()},
  "bigfile": {"mk": mk.hex(), "length": len(big), "sha256": hashlib.sha256(big).hexdigest(), "blob": bigblob.hex()},
  "tag": {"mk": mk.hex(), "sha256": sha.hex(), "tag": C.content_tag(mk, sha)},
  "json": {"mk": mk.hex(), "aad": "sv-meta", "blob": C.encrypt_json(mk, meta, b"sv-meta"), "obj": meta},
}
out = os.path.join(ROOT, "app", "test", "vectors.json")
with open(out, "w") as f:
    json.dump(v, f)
print("yozildi:", out, os.path.getsize(out), "bayt")
