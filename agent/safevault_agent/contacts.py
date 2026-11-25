"""Zaxiradagi kontaktlar (kontaktlar.vcf) ni o'qish va ichidan qidirish."""
from __future__ import annotations

import re


def parse_vcf(text: str) -> list[dict]:
    """vCard matnidan [{'name': str, 'tels': [str, ...]}] chiqaradi (uzun qatorlar birlashtiriladi)."""
    text = re.sub(r"\r?\n[ \t]", "", text)  # vCard "folding"
    out, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        up = line.upper()
        if up == "BEGIN:VCARD":
            cur = {"name": "", "tels": []}
        elif up == "END:VCARD":
            if cur and (cur["name"] or cur["tels"]):
                out.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, _, val = line.partition(":")
            k = key.split(";")[0].upper()
            val = val.strip()
            if k == "FN" and val:
                cur["name"] = val
            elif k == "N" and not cur["name"]:
                cur["name"] = " ".join(p for p in reversed(val.split(";")[:2]) if p).strip()
            elif k == "TEL" and val:
                cur["tels"].append(val)
    return sorted(out, key=lambda c: c["name"].lower())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def search_contacts(contacts: list[dict], query: str) -> list[dict]:
    """Ism bo'laklari yoki raqam bo'yicha qidiradi (barcha so'zlar mos kelishi kerak)."""
    toks = [t for t in re.split(r"\s+", query.lower().strip()) if t]
    if not toks:
        return []
    res = []
    for c in contacts:
        name = c["name"].lower()
        digs = [_digits(t) for t in c["tels"]]
        ok = True
        for t in toks:
            td = _digits(t)
            if t in name or any(len(w) >= 3 and t.startswith(w) for w in name.split()) or (len(td) >= 3 and any(td in d for d in digs)):
                continue
            ok = False
            break
        if ok:
            res.append(c)
    return res


def format_contacts(contacts: list[dict], max_chars: int = 3500) -> list[str]:
    """Ro'yxatni Telegram xabar chegarasiga sig'adigan bo'laklarga ajratadi."""
    chunks, cur = [], ""
    for c in contacts:
        line = f"👤 {c['name'] or '(ismsiz)'} — {', '.join(c['tels']) if c['tels'] else 'raqam yo‘q'}\n"
        if len(cur) + len(line) > max_chars:
            chunks.append(cur.rstrip())
            cur = ""
        cur += line
    if cur:
        chunks.append(cur.rstrip())
    return chunks
