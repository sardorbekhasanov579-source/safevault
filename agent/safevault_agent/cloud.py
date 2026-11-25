"""Agentni serverda (konteynerda) interaktivsiz ishga tushirish.

Sozlash kompyuterda bir marta qilinadi (QAYTA_SOZLASH.bat), so'ng state.json base64 ko'rinishida
SAFEVAULT_AGENT_STATE_B64 muhit o'zgaruvchisiga beriladi. Saqlangan holat (disk yoki ombor) muhit qiymatidan ustun turadi; qiymatni majburan almashtirish uchun SAFEVAULT_AGENT_STATE_FORCE=1 qo'ying.

Bulut rejimi (SAFEVAULT_S3_* berilgan): agent holati shifrlangan ko'rinishda omborda ham saqlanadi (kalit: SAFEVAULT_PEPPER_B64
dan hosil qilinadi), shuning uchun xizmat qayta ishga tushsa ham egasi, PIN va boshqa sozlamalar yo'qolmaydi.
Telegram yangilanishlari webhook orqali keladi: bepul xizmat uxlab qolsa, Telegramning o'zi uni uyg'otadi."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import queue
import sys
import threading

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from safevault_client import crypto as C
from safevault_client.client import VaultClient

from .bot import Bot
from .state import State, home_dir, new_pairing_code
from .tg import Telegram

STATE_OBJECT = "agent/state.enc"
_AAD = b"safevault-agent-state"


def _s3():
    try:
        from safevault_server.s3 import S3
    except ImportError:  # agent serversiz (kompyuterda) ishlayapti
        return None
    return S3.from_env()


def _pepper() -> bytes | None:
    raw = os.environ.get("SAFEVAULT_PEPPER_B64", "").strip()
    return base64.b64decode(raw) if raw else None


def _state_key(pepper: bytes) -> bytes:
    return hashlib.sha256(b"safevault-agent-state-key" + pepper).digest()


def encrypt_state(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, _AAD)


def decrypt_state(key: bytes, blob: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], _AAD)


def load_state() -> State:
    s3, pepper = _s3(), _pepper()
    key = _state_key(pepper) if (s3 and pepper) else None
    path = os.path.join(home_dir(), "state.json")
    if key:  # omborda saqlangan holat (xizmat qayta ishga tushganda diskda hech narsa yo'q)
        try:
            blob = s3.get(STATE_OBJECT)
            if blob:
                plain = decrypt_state(key, blob)  # avval ochamiz: xato bo'lsa fayl buzilmasin
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(plain)
        except Exception as e:  # noqa: BLE001
            print(f"[agent] omborda saqlangan holat o'qilmadi ({type(e).__name__}): muhit qiymatidan boshlanadi", file=sys.stderr, flush=True)
    st = State()
    raw = os.environ.get("SAFEVAULT_AGENT_STATE_B64", "").strip()
    if raw:
        if not st.ready or os.environ.get("SAFEVAULT_AGENT_STATE_FORCE") == "1":  # birinchi marta yoki majburiy yangilash
            try:
                data = json.loads(base64.b64decode(raw))
            except Exception as e:  # noqa: BLE001  (qiymat xabarga chiqmaydi)
                raise SystemExit(f"SAFEVAULT_AGENT_STATE_B64 o'qilmadi ({type(e).__name__}). Faylni base64 ga qaytadan aylantiring.")
            st.set(**data)
    if key:
        def push(data: bytes):
            try:
                s3.put(STATE_OBJECT, encrypt_state(key, data))
            except Exception as e:  # noqa: BLE001
                print(f"[agent] holat omborga yozilmadi: {type(e).__name__}", file=sys.stderr, flush=True)

        st.remote = push
        if st.ready:
            push(json.dumps(st.d).encode())
    override = os.environ.get("SAFEVAULT_AGENT_SERVER")
    if st.ready and override and st.get("server") != override:
        st.set(server=override)
    return st


def _make_bot(st: State) -> Bot:
    if st.get("owner_chat") is None and not st.get("pair_code"):
        st.set(pair_code=new_pairing_code())
    if st.get("owner_chat") is None:
        print(f"[agent] Bot hali ulanmagan. Telegram'da botga yuboring:  /ulash {st.get('pair_code')}", flush=True)
    vault = VaultClient(st.get("server"), st.get("device_id"))
    vault.token, vault.mk = st.get("token"), C.b64d(st.get("mk"))
    return Bot(st, Telegram(st.get("tg_token")), vault)


def run_cloud():
    """Agent tayyor bo'lmasa False qaytaradi (server ishlashda davom etadi), aks holda botni (long polling) ishga tushiradi."""
    st = load_state()
    if not st.ready:
        print("[agent] Agent sozlanmagan: SAFEVAULT_AGENT_STATE_B64 berilmagan. Faqat server ishlayapti.", file=sys.stderr, flush=True)
        return False
    _make_bot(st).run()
    return True


def webhook_secret(pepper: bytes) -> str:
    return hmac.new(pepper, b"telegram-webhook", hashlib.sha256).hexdigest()[:48]


def start_webhook(svc, public_url: str) -> bool:
    """Botni webhook rejimida ishga tushiradi (bloklamaydi). Agent sozlanmagan bo'lsa False."""
    st = load_state()
    if not st.ready:
        print("[agent] Agent sozlanmagan: SAFEVAULT_AGENT_STATE_B64 berilmagan. Faqat server ishlayapti.", file=sys.stderr, flush=True)
        return False
    bot = _make_bot(st)
    secret = webhook_secret(svc.s.pepper)
    q: "queue.Queue[dict]" = queue.Queue()
    seen = {"last": -1}

    def on_request(path: str, headers, body) -> bool:
        if path != f"/tg/{secret}" or not hmac.compare_digest(headers.get("X-Telegram-Bot-Api-Secret-Token", ""), secret):
            return False
        if isinstance(body, dict) and isinstance(body.get("update_id"), int):
            q.put(body)  # tezda 200 qaytariladi; ishlov tartib bilan alohida oqimda
        return True

    def worker():
        while True:
            upd = q.get()
            if upd["update_id"] <= seen["last"]:  # Telegram qayta yuborgan nusxa
                continue
            seen["last"] = upd["update_id"]
            try:
                bot.keepalive_tick()
                bot.handle_update(upd)
            except Exception as e:  # noqa: BLE001
                print(f"[agent] yangilanish ishlanmadi: {type(e).__name__}", file=sys.stderr, flush=True)

    def register():
        import time
        for i in range(6):
            try:
                from .bot import COMMANDS
                bot.tg.set_commands(COMMANDS)
                bot.tg.set_webhook(f"{public_url.rstrip('/')}/tg/{secret}", secret)
                print("[agent] Telegram webhook o'rnatildi", flush=True)
                return
            except Exception as e:  # noqa: BLE001
                print(f"[agent] webhook o'rnatilmadi ({type(e).__name__}); qayta uriniladi", file=sys.stderr, flush=True)
                time.sleep(5 * (i + 1))

    svc.webhook = on_request
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=register, daemon=True).start()
    return True
