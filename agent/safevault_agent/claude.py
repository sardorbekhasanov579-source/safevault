"""So'rovni Claude orqali tahlil qilish (ixtiyoriy). Claude'ga FAQAT foydalanuvchi yozgan matn va bugungi sana
yuboriladi, fayl nomlari yoki mazmuni yuborilmaydi."""
from __future__ import annotations

import datetime as dt
import json
import urllib.request

TOOL = {
    "name": "search_files",
    "description": "Foydalanuvchi zaxiralagan fayllarni qidirish parametrlari.",
    "input_schema": {
        "type": "object",
        "properties": {
            "keywords": {"type": "array", "items": {"type": "string"},
                         "description": "Fayl nomida uchrashi mumkin bo'lgan so'zlar, ildiz shaklida (diplomimni -> diplom). Sana, 'topib ber' kabi so'zlarsiz."},
            "category": {"type": "string", "enum": ["photo", "video", "contact", "document"],
                         "description": "Faqat foydalanuvchi turini aniq aytgan bo'lsa."},
            "saved_from": {"type": "string", "description": "Saqlangan sana boshi, YYYY-MM-DD (shu kun ham kiradi)"},
            "saved_to": {"type": "string", "description": "Saqlangan sana oxiri, YYYY-MM-DD (shu kun ham kiradi)"},
            "latest_only": {"type": "boolean", "description": "Faqat eng oxirgi bitta fayl so'ralgan bo'lsa true"},
        },
        "required": ["keywords"],
    },
}


def _date(s):
    try:
        return dt.date.fromisoformat(s) if s else None
    except ValueError:
        return None


def extract(api_key: str, text: str, today: dt.date, model: str = "claude-haiku-5-5",
            base_url: str = "https://api.anthropic.com") -> dict:
    system = (f"Bugungi sana: {today.isoformat()} (hafta kuni: {today.strftime('%A')}). Foydalanuvchi o'zbek tilida zaxiradagi "
              "faylni qidiryapti. Faqat search_files asbobini chaqir. 'O'tgan oy' = oldingi kalendar oy, "
              "'o'tgan hafta' = oldingi dushanba-yakshanba. Sana aytilmagan bo'lsa saved_from/saved_to ni bermang.")
    body = {"model": model, "max_tokens": 300, "system": system, "tools": [TOOL],
            "tool_choice": {"type": "tool", "name": "search_files"},
            "messages": [{"role": "user", "content": text}]}
    req = urllib.request.Request(base_url + "/v1/messages", data=json.dumps(body).encode(), method="POST",
                                 headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    for block in data.get("content", []):
        if block.get("type") == "tool_use":
            a = block.get("input") or {}
            cat = a.get("category")
            return {"keywords": [str(k).lower() for k in a.get("keywords", []) if str(k).strip()],
                    "category": cat if cat in ("photo", "video", "contact", "document") else None,
                    "start": _date(a.get("saved_from")), "end": _date(a.get("saved_to")),
                    "latest": bool(a.get("latest_only"))}
    raise ValueError("Claude javobida asbob chaqiruvi yo'q")
