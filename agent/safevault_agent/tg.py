"""Telegram Bot API klienti (faqat standart kutubxona)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_UPLOAD = 50 * 1024 * 1024  # Telegram bot hujjat yuklash chegarasi


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, api_base: str = "https://api.telegram.org"):
        self._root = f"{api_base}/bot{token}"

    def _call(self, method: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 40) -> dict:
        req = urllib.request.Request(f"{self._root}/{method}", data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise TelegramError(f"{method}: HTTP {e.code}") from None  # URL (token) xabarga chiqmaydi
        except urllib.error.URLError as e:
            raise TelegramError(f"{method}: ulanish xatosi") from None
        if not res.get("ok"):
            raise TelegramError(f"{method}: {res.get('description', 'xato')}")
        return res["result"]

    def _json(self, method: str, payload: dict, timeout: int = 40):
        return self._call(method, json.dumps(payload).encode(), {"Content-Type": "application/json"}, timeout)

    def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict]:
        p = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            p["offset"] = offset
        return self._json("getUpdates", p, timeout=timeout + 10)

    def set_webhook(self, url: str, secret_token: str):
        """Telegram yangilanishlarni shu manzilga yuboradi (bepul bulutda xizmat uxlab qolsa ham uni uyg'otadi)."""
        return self._json("setWebhook", {"url": url, "secret_token": secret_token, "max_connections": 1,
                                          "allowed_updates": ["message", "callback_query"], "drop_pending_updates": False})

    def delete_webhook(self):
        return self._json("deleteWebhook", {"drop_pending_updates": False})

    def send_message(self, chat_id, text: str, buttons: list[list[tuple[str, str]]] | None = None,
                     keyboard: list[list[str]] | None = None):
        """buttons: xabar ostidagi tugmalar (inline). keyboard: yozish maydoni yonida doim turadigan tugmalar."""
        p = {"chat_id": chat_id, "text": text[:4000]}
        if buttons:
            p["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
        elif keyboard:
            p["reply_markup"] = {"keyboard": [[{"text": t} for t in row] for row in keyboard],
                                 "resize_keyboard": True, "is_persistent": True}
        return self._json("sendMessage", p)

    def delete_message(self, chat_id, message_id: int):
        return self._json("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    def set_commands(self, commands: list[tuple[str, str]]):
        """Telegram'dagi '/' menyusi (yozish maydoni yonidagi tugma) uchun buyruqlar ro'yxati."""
        return self._json("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})

    def answer_callback(self, callback_id: str, text: str | None = None):
        p = {"callback_query_id": callback_id}
        if text:
            p["text"] = text
        return self._json("answerCallbackQuery", p)

    def send_location(self, chat_id, lat: float, lon: float):
        return self._json("sendLocation", {"chat_id": chat_id, "latitude": lat, "longitude": lon})

    def send_document(self, chat_id, filename: str, data: bytes, caption: str | None = None):
        boundary = uuid.uuid4().hex
        safe = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        body = bytearray()

        def field(name: str, value: str):
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

        field("chat_id", str(chat_id))
        if caption:
            field("caption", caption[:1000])
        body.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{safe}"\r\n'
                     "Content-Type: application/octet-stream\r\n\r\n").encode())
        body.extend(data)
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        return self._call("sendDocument", bytes(body), {"Content-Type": f"multipart/form-data; boundary={boundary}"}, 300)
