"""Agentni birinchi marta sozlash (interaktiv): zaxira hisobiga kirish + Telegram bot + ixtiyoriy PIN va Claude kaliti."""
from __future__ import annotations

import getpass
import secrets
import sys

from safevault_client import crypto as C
from safevault_client.client import ApiFailure, VaultClient

from .state import State, hash_pin, new_pairing_code


def ask(prompt: str, secret: bool = False, default: str = "") -> str:
    v = (getpass.getpass(prompt + ": ") if secret else input(prompt + (f" [{default}]" if default else "") + ": ")).strip()
    return v or default


def run_setup(state: State | None = None) -> State:
    st = state or State()
    print("=== SafeVault agentini sozlash ===")
    server = ask("Zaxira serveri manzili (masalan https://nom.duckdns.org yoki http://127.0.0.1:8080)", default=st.get("server") or "")
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    phone = ask("Telefon raqamingiz (+998...)", default=st.get("phone") or "")
    password = ask("Zaxira hisobi paroli (ekranda ko'rinmaydi)", secret=True)
    device_id = st.get("device_id") or "agent-" + secrets.token_hex(8)
    vault = VaultClient(server, device_id)
    try:
        vault.login(phone, password)
    except ApiFailure as e:
        if e.code != "new_device_required":
            raise SystemExit(f"Kirib bo'lmadi: {e.code or e.status}")
        print("Bu yangi qurilma deb hisoblanadi. Telefoningizga (yoki server oynasi / Telegram'ga) SMS kodi yuboriladi.")
        vault.request_otp("new_device", phone)
        code = ask("Kelgan 6 xonali kod")
        rec = ask("Tiklash kodingiz (XXXX-XXXX-...)")
        try:
            vault.login(phone, password, phone_code=code, recovery_code=rec)
        except (ApiFailure, C.CryptoError) as e2:
            raise SystemExit(f"Kirib bo'lmadi: {getattr(e2, 'code', e2)}")
    tg_token = ask("Telegram bot tokeni (@BotFather dan; ekranda ko'rinmaydi)", secret=True, default=st.get("tg_token") or "")
    key = ask("Gemini API kaliti (aistudio.google.com dan; ixtiyoriy, Enter = oddiy qidiruv; ekranda ko'rinmaydi)", secret=True)
    pin = ask("Bot uchun PIN (ixtiyoriy, Enter = PIN'siz; ekranda ko'rinmaydi)", secret=True)
    pair = new_pairing_code()
    st.set(server=server, phone=phone, device_id=device_id, token=vault.token, mk=C.b64e(vault.mk), tg_token=tg_token,
           gemini_key=key or None, pin=hash_pin(pin) if pin else None, owner_chat=None, pair_code=pair)
    print(f"\nTayyor. Endi Telegram'da botingizga quyidagini yuboring:\n\n    /ulash {pair}\n")
    return st
