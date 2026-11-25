"""Kompyuterdagi SafeVault ma'lumotlarini (C:\\SafeVaultData) bulut omboriga ko'chiradi.

Ishlatish (Windows PowerShell, loyiha papkasida; avval serverni to'xtating):
  $env:SAFEVAULT_S3_ENDPOINT="https://s3.eu-central-003.backblazeb2.com"
  $env:SAFEVAULT_S3_BUCKET="..."; $env:SAFEVAULT_S3_KEY_ID="..."; $env:SAFEVAULT_S3_SECRET="..."
  python deploy\\migrate_to_cloud.py C:\\SafeVaultData

Skript: fayllarni (shifrlangan bloblar) omborga yuklaydi, bazaning nusxasini yuklaydi va Render'ga qo'yiladigan
SAFEVAULT_PEPPER_B64 qiymatini chiqaradi (server_secret.key shu qiymatning asli: usiz eski parollar/sessiyalar ishlamaydi).
Qayta ishga tushirsangiz, omborda bor fayllar o'tkazib yuboriladi. Mahalliy fayllar o'zgarmaydi."""
import base64
import gzip
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from safevault_server.s3 import S3  # noqa: E402
from safevault_server.store import DB_KEY  # noqa: E402


def migrate(data_dir: str, s3: S3, log=print) -> str:
    db_path = os.path.join(data_dir, "vault.db")
    key_path = os.path.join(data_dir, "server_secret.key")
    if not os.path.exists(db_path) or not os.path.exists(key_path):
        raise SystemExit(f"{data_dir} ichida vault.db va server_secret.key topilmadi.")
    if s3.get(DB_KEY) is not None:
        raise SystemExit("Omborda baza allaqachon bor. Ustiga yozmaslik uchun to'xtatildi (bo'sh ombor yoki yangi bucket oling).")
    blobs = os.path.join(data_dir, "blobs")
    n = skipped = total = 0
    for uid in sorted(os.listdir(blobs)) if os.path.isdir(blobs) else []:
        udir = os.path.join(blobs, uid)
        for fid in sorted(os.listdir(udir)):
            if fid.endswith((".part", ".tmp")):
                continue
            p = os.path.join(udir, fid)
            size = os.path.getsize(p)
            total += size
            key = f"blobs/{uid}/{fid}"
            got = None
            try:
                got = s3.open_stream(key)
            except Exception:  # noqa: BLE001  (yo'q bo'lsa yuklanadi)
                pass
            if got and got[0] == size:
                skipped += 1
                continue
            import hashlib
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            s3.put_file(key, p, size, h.hexdigest())
            n += 1
            log(f"  yuklandi: {fid[:8]}… ({size // 1024} KB)")
    log(f"Fayllar: {n} ta yuklandi, {skipped} tasi omborda bor edi ({total // (1024 * 1024)} MB)")
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src, dst = sqlite3.connect(db_path), sqlite3.connect(tmp)
        src.backup(dst)
        dst.close()
        src.close()
        with open(tmp, "rb") as f:
            s3.put(DB_KEY, gzip.compress(f.read(), compresslevel=6))
    finally:
        os.remove(tmp)
    log("Baza nusxasi yuklandi.")
    with open(key_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    s3 = S3.from_env()
    if not s3:
        raise SystemExit("SAFEVAULT_S3_ENDPOINT / _BUCKET / _KEY_ID / _SECRET muhit o'zgaruvchilari berilmagan.")
    pepper = migrate(sys.argv[1], s3)
    print("\nRender'da Environment ga qo'ying:\nSAFEVAULT_PEPPER_B64 = " + pepper)
    print("(Bu qiymat maxfiy: hech kimga yubormang.)")


if __name__ == "__main__":
    main()
