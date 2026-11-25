"""Telefon (yoki sinov) mijozi: server bilan shifrlangan holda gaplashadi.

Mobil ilovadagi mantiqning Python andozasi — Dart versiyasi shu oqimni takrorlaydi.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

from . import crypto as C


class ApiFailure(Exception):
    def __init__(self, status: int, body: dict):
        super().__init__(f"{status} {body}")
        self.status, self.body = status, body

    @property
    def code(self) -> str:
        return self.body.get("error", "")


class VaultClient:
    def __init__(self, base_url: str, device_id: str):
        self.base = base_url.rstrip("/")
        self.device_id = device_id
        self.token: str | None = None
        self.mk: bytes | None = None  # faqat xotirada

    # ---- past daraja ----
    def _call(self, method: str, path: str, body: dict | None = None, data: bytes | None = None,
              headers: dict | None = None):
        h = dict(headers or {})
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        payload = data
        if body is not None:
            payload = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=payload, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())
            except Exception:  # noqa: BLE001
                err = {"error": "http_error"}
            raise ApiFailure(e.code, err) from None

    # ---- hisob ----
    def request_otp(self, purpose: str, phone: str, email: str | None = None):
        b = {"purpose": purpose, "phone": phone}
        if email:
            b["email"] = email
        return self._call("POST", "/v1/auth/otp", b)

    def register(self, phone: str, email: str, phone_code: str, email_code: str, password: str) -> str:
        """Hisob yaratadi. Tiklash kodini qaytaradi — foydalanuvchiga FAQAT BIR MARTA ko'rsatiladi."""
        mk = C.new_master_key()
        pw_salt, rec_salt = C.new_salt(), C.new_salt()
        code = C.new_recovery_code()
        kek_p, auth_p = C.password_keys(password, pw_salt)
        kek_r, auth_r = C.recovery_keys(code, rec_salt)
        res = self._call("POST", "/v1/auth/register", {
            "phone": phone, "email": email, "phone_code": phone_code, "email_code": email_code,
            "pw_salt": C.b64e(pw_salt), "rec_salt": C.b64e(rec_salt), "kdf": C.DEFAULT_KDF,
            "auth": C.b64e(auth_p), "rec_auth": C.b64e(auth_r),
            "wrapped_pw": C.b64e(C.wrap(kek_p, mk, b"sv-mk")),
            "wrapped_rec": C.b64e(C.wrap(kek_r, mk, b"sv-mk")),
            "device_id": self.device_id})
        self.token, self.mk = res["token"], mk
        return code

    def login(self, phone: str, password: str, phone_code: str | None = None, recovery_code: str | None = None):
        p = self._call("GET", "/v1/auth/params?phone=" + urllib.parse.quote(phone))
        kek, auth = C.password_keys(password, C.b64d(p["pw_salt"]), p["kdf"])
        body = {"phone": phone, "auth": C.b64e(auth), "device_id": self.device_id}
        if phone_code and recovery_code:
            _, rec_auth = C.recovery_keys(recovery_code, C.b64d(p["rec_salt"]))
            body.update(phone_code=phone_code, rec_auth=C.b64e(rec_auth))
        res = self._call("POST", "/v1/auth/login", body)
        self.mk = C.unwrap(kek, C.b64d(res["wrapped_pw"]), b"sv-mk")
        self.token = res["token"]

    def recover(self, phone: str, phone_code: str, email_code: str, recovery_code: str, new_password: str):
        """Parolni unutgan holat: telefon + email kodi + tiklash kodi -> yangi parol."""
        p = self._call("GET", "/v1/auth/params?phone=" + urllib.parse.quote(phone))
        kek_r, rec_auth = C.recovery_keys(recovery_code, C.b64d(p["rec_salt"]))
        res = self._call("POST", "/v1/auth/recover", {
            "phone": phone, "phone_code": phone_code, "email_code": email_code, "rec_auth": C.b64e(rec_auth)})
        mk = C.unwrap(kek_r, C.b64d(res["wrapped_rec"]), b"sv-mk")
        salt = C.new_salt()
        kek_p, auth_p = C.password_keys(new_password, salt)
        out = self._call("POST", "/v1/auth/reset", {
            "reset_token": res["reset_token"], "device_id": self.device_id, "pw_salt": C.b64e(salt),
            "kdf": C.DEFAULT_KDF, "auth": C.b64e(auth_p), "wrapped_pw": C.b64e(C.wrap(kek_p, mk, b"sv-mk"))})
        self.token, self.mk = out["token"], mk

    # ---- zaxira ----
    def backup(self, data: bytes, meta: dict) -> dict:
        assert self.mk, "avval kiring"
        tag = C.content_tag(self.mk, hashlib.sha256(data).digest())
        if not self._call("POST", "/v1/files/missing", {"tags": [tag]})["missing"]:
            return {"duplicate": True}
        blob = C.encrypt_file(self.mk, data)
        enc_meta = C.encrypt_json(self.mk, meta, b"sv-meta")
        return self._call("PUT", f"/v1/files/{tag}", data=blob,
                          headers={"X-Meta": enc_meta, "Content-Type": "application/octet-stream"})

    def list_files(self) -> list[dict]:
        out = []
        for f in self._call("GET", "/v1/files")["files"]:
            out.append({"id": f["id"], "size": f["size"], "uploaded_at": f["uploaded_at"],
                        **C.decrypt_json(self.mk, f["meta"], b"sv-meta")})
        return out

    def restore(self, file_id: str) -> bytes:
        return C.decrypt_file(self.mk, self._call("GET", f"/v1/files/{file_id}"))

    def status(self) -> dict:
        return self._call("GET", "/v1/status")

    # ---- joylashuv ----
    def send_location(self, lat: float, lon: float, accuracy_m: float, address: str | None = None, battery: int | None = None):
        payload = C.encrypt_json(self.mk, {"lat": lat, "lon": lon, "acc": accuracy_m, "addr": address, "bat": battery}, b"sv-loc")
        return self._call("POST", "/v1/location", {"payload": payload})

    def get_location(self) -> dict:
        r = self._call("GET", "/v1/location")
        return {**C.decrypt_json(self.mk, r["payload"], b"sv-loc"), "updated_at": r["updated_at"]}
