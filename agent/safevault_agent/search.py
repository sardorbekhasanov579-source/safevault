"""Zaxiradagi fayllarni nom, tur va saqlangan sana bo'yicha qidirish (o'zbekcha so'rovlar).

Server fayl nomlarini ko'ra olmaydi (ular shifrlangan), shuning uchun qidiruv shu agentda,
shifri ochilgan metama'lumotlar ustida bajariladi. Fayl MAZMUNI bo'yicha qidirish (OCR) hozircha yo'q.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

MONTHS = {"yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6, "iyul": 7,
          "avgust": 8, "sentabr": 9, "oktabr": 10, "noyabr": 11, "dekabr": 12}
CATEGORY_WORDS = {"rasm": "photo", "surat": "photo", "foto": "photo", "video": "video",
                  "kontakt": "contact", "raqam": "contact", "nomer": "contact", "hujjat": "document", "dokument": "document", "document": "document"}
STOP = {"topib", "top", "ber", "bering", "berchi", "menga", "mening", "meni", "saqlagan", "saqlangan",
        "saqlab", "saqlaganimni", "fayl", "faylni", "fayllar", "yubor", "yuboring", "kerak", "qidir",
        "qidirib", "ko'rsat", "ko'rsating", "yuklab", "olib", "iltimos", "edi", "bor", "va", "bilan",
        "uchun", "menda", "men", "bu", "shu", "oxirgi", "eng", "qani", "qayerda", "qaysi", "hammasi",
        "barcha", "o'tgan", "oldingi", "yil", "oy", "hafta", "kun", "bugun", "kecha"}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    for ch in "ʻʼ’‘`´":
        t = t.replace(ch, "'")
    return t


def _month_bounds(y: int, m: int):
    start = dt.date(y, m, 1)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return start, nxt - dt.timedelta(days=1)


def parse_query(text: str, today: dt.date | None = None) -> dict:
    """Qoida asosida: {'keywords': [...], 'category': str|None, 'start': date|None, 'end': date|None, 'latest': bool}"""
    today = today or dt.date.today()
    rest = " " + normalize(text) + " "
    start = end = None

    def take(pat: str) -> bool:
        nonlocal rest
        m = re.search(pat, rest)
        if not m:
            return False
        rest = rest[:m.start()] + " " + rest[m.end():]
        return True

    if take(r"(?<![a-z'])(o'tgan|oldingi|avvalgi) oy(?![a-z'])"):
        y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        start, end = _month_bounds(y, m)
    elif take(r"(?<![a-z'])bu oy(?![a-z'])"):
        start, end = _month_bounds(today.year, today.month)
    elif take(r"(?<![a-z'])(o'tgan|oldingi|avvalgi) hafta(?![a-z'])"):
        mon = today - dt.timedelta(days=today.weekday() + 7)
        start, end = mon, mon + dt.timedelta(days=6)
    elif take(r"(?<![a-z'])bu hafta(?![a-z'])"):
        start, end = today - dt.timedelta(days=today.weekday()), today
    elif take(r"(?<![a-z'])bugun(?![a-z'])"):
        start = end = today
    elif take(r"(?<![a-z'])kecha(?![a-z'])"):
        start = end = today - dt.timedelta(days=1)
    elif take(r"(?<![a-z'])(o'tgan|oldingi|avvalgi) yil(?![a-z'])"):
        start, end = dt.date(today.year - 1, 1, 1), dt.date(today.year - 1, 12, 31)
    elif take(r"(?<![a-z'])bu yil(?![a-z'])"):
        start, end = dt.date(today.year, 1, 1), today
    else:
        for name, num in MONTHS.items():
            m = re.search(rf"(?<![a-z'])({name})[a-z']*(\s+oy[a-z']*)?", rest)
            if m:
                ym = re.search(r"(?<!\d)(20\d\d)(?!\d)", rest)
                year = int(ym.group(1)) if ym else (today.year if num <= today.month else today.year - 1)
                start, end = _month_bounds(year, num)
                rest = rest[:m.start()] + " " + rest[m.end():]
                if ym:
                    rest = rest.replace(ym.group(1), " ")
                break

    latest = bool(re.search(r"(?<![a-z'])(oxirgi|eng so'nggi|so'nggi)(?![a-z'])", normalize(text)))
    category = None
    keywords: list[str] = []
    for tok in re.findall(r"[a-z0-9']+", rest):
        tok = tok.strip("'")
        if len(tok) < 3 or tok in STOP:
            continue
        cat = next((c for pref, c in CATEGORY_WORDS.items() if tok.startswith(pref)), None)
        if cat:
            category = category or cat
            continue
        keywords.append(tok)
    return {"keywords": keywords, "category": category, "start": start, "end": end, "latest": latest}


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9']+", normalize(name)) if w]


def _matches(tok: str, words: list[str], whole: str) -> bool:
    if len(tok) >= 4 and tok in whole:
        return True
    for w in words:  # "diplomimni" <-> "diplom": qo'shimcha qo'shilgan so'zni ham topadi
        if len(w) >= 4 and (tok.startswith(w) or (len(tok) >= 4 and w.startswith(tok))):
            return True
    return False


def search(index: list[dict], q: dict, limit: int = 8) -> tuple[list[dict], bool]:
    """(natijalar, toifa_filtri_yumshatildi). index: {name, category, size, uploaded_at, id}."""
    def run(use_category: bool):
        out = []
        for f in index:
            if use_category and q.get("category") and f.get("category") != q["category"]:
                continue
            ts = f.get("uploaded_at", 0)
            if q.get("start") and ts < dt.datetime.combine(q["start"], dt.time.min).timestamp():
                continue
            if q.get("end") and ts >= dt.datetime.combine(q["end"] + dt.timedelta(days=1), dt.time.min).timestamp():
                continue
            score = 0
            if q.get("keywords"):
                words, whole = _words(f.get("name", "")), normalize(f.get("name", ""))
                score = sum(1 for k in q["keywords"] if _matches(normalize(k), words, whole))
                if score == 0:
                    continue
            out.append((score, ts, f))
        out.sort(key=lambda x: (-x[0], -x[1]))
        return [x[2] for x in out][:1 if (q.get("latest") and out) else limit]

    res = run(True)
    if not res and q.get("category") and q.get("keywords"):  # faqat toifa so'ralgan bo'lsa (so'z yo'q), boshqa toifani ko'rsatmaymiz
        res2 = run(False)
        if res2:
            return res2, True
    return res, False


CATEGORY_NAMES = {"photo": "rasm", "video": "video", "document": "hujjat", "contact": "kontakt"}


def fmt_range(start: dt.date | None, end: dt.date | None) -> str:
    if not start and not end:
        return ""
    if start == end:
        return start.strftime("%d.%m.%Y")
    return f"{start.strftime('%d.%m.%Y') if start else '...'} – {end.strftime('%d.%m.%Y') if end else '...'}"


def describe_query(q: dict) -> str:
    """So'rov nimaga tushunilganini odamga tushunarli qilib yozadi."""
    parts = []
    if q.get("category"):
        parts.append(CATEGORY_NAMES.get(q["category"], q["category"]))
    if q.get("keywords"):
        parts.append("«" + " ".join(q["keywords"]) + "»")
    r = fmt_range(q.get("start"), q.get("end"))
    if r:
        parts.append(r)
    return ", ".join(parts) if parts else "barcha fayllar"


def summarize(index: list[dict]) -> str:
    """Zaxirada nima borligi: toifalar bo'yicha son va sana oralig'i."""
    if not index:
        return "Zaxira hali bo'sh."
    counts = {c: 0 for c in ("photo", "video", "document", "contact")}
    for f in index:
        counts[f.get("category", "document")] = counts.get(f.get("category", "document"), 0) + 1
    names = ", ".join(f"{n} ta {CATEGORY_NAMES[c]}" for c, n in counts.items())
    ts = [f.get("uploaded_at", 0) for f in index]
    d = lambda t: dt.datetime.fromtimestamp(t).strftime("%d.%m.%Y")  # noqa: E731
    span = d(min(ts)) if d(min(ts)) == d(max(ts)) else f"{d(min(ts))} dan {d(max(ts))} gacha"
    return f"Zaxirada: {names}. Saqlangan sanalar: {span}."
