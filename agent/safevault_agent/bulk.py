"""Ko'p faylni bir yo'la yuklab olish: fayllar Telegram chegarasiga (50 MB) sig'adigan ZIP qismlarga bo'linadi."""
from __future__ import annotations

import io
import re
import zipfile

PART_LIMIT = 45 * 1024 * 1024  # Telegram 50 MB ruxsat beradi; ZIP qo'shimcha joyi uchun zaxira qoldiramiz
PARTS_PER_STEP = 10            # bir bosishda eng ko'pi bilan shuncha ZIP; qolganini "Davom" tugmasi yuboradi


def plan_zips(files: list[dict], limit: int | None = None) -> tuple[list[list[dict]], list[dict]]:
    """Fayllarni (eng yangisi birinchi) qismlarga bo'ladi. Bitta o'zi limitdan katta fayllar alohida qaytariladi."""
    limit = PART_LIMIT if limit is None else limit
    parts: list[list[dict]] = []
    too_big: list[dict] = []
    cur: list[dict] = []
    size = 0
    for f in sorted(files, key=lambda x: -x["uploaded_at"]):
        if f["size"] > limit:
            too_big.append(f)
            continue
        if cur and size + f["size"] > limit:
            parts.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += f["size"]
    if cur:
        parts.append(cur)
    return parts, too_big


def _safe(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or "fayl"
    return name[:120]


def build_zip(vault, files: list[dict]) -> bytes:
    """Fayllarni zaxiradan olib shifrini ochadi va bitta ZIP qiladi (bir xil nomlar raqam bilan ajratiladi)."""
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            name = _safe(f.get("name", "fayl"))
            base, dot, ext = name.rpartition(".")
            if not dot:
                base, ext = name, ""
            n, cand = 1, name
            while cand.lower() in used:
                n += 1
                cand = f"{base} ({n}).{ext}" if ext else f"{base} ({n})"
            used.add(cand.lower())
            z.writestr(cand, vault.restore(f["id"]))
    return buf.getvalue()
