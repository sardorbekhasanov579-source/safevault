"""Minimal S3-mos mijoz (Backblaze B2, Cloudflare R2, MinIO ...) — faqat standart kutubxona, AWS Signature V4.

Muhit o'zgaruvchilari: SAFEVAULT_S3_ENDPOINT (masalan https://s3.us-west-004.backblazeb2.com), SAFEVAULT_S3_BUCKET,
SAFEVAULT_S3_KEY_ID, SAFEVAULT_S3_SECRET, ixtiyoriy SAFEVAULT_S3_REGION (bo'lmasa endpoint nomidan olinadi)."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import http.client
import os
import re
import time
import urllib.parse

CHUNK = 1 << 20


class S3Error(Exception):
    def __init__(self, status: int, body: bytes = b"", op: str = ""):
        super().__init__(f"S3 {op} xatosi: HTTP {status}")
        self.status = status
        self.body = body


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign_v4(method: str, host: str, canonical_uri: str, query: dict, headers: dict, payload_hash: str,
            key_id: str, secret: str, region: str, amz_date: str, service: str = "s3") -> str:
    """Authorization sarlavhasi qiymatini qaytaradi. headers: imzolanadigan qo'shimcha sarlavhalar (host, x-amz-* ni o'zi qo'shadi)."""
    h = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    h["host"] = host
    h["x-amz-date"] = amz_date
    h["x-amz-content-sha256"] = payload_hash
    names = sorted(h)
    canon_headers = "".join(f"{k}:{h[k]}\n" for k in names)
    signed = ";".join(names)
    cq = "&".join(f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(str(v), safe='-_.~')}" for k, v in sorted(query.items()))
    creq = "\n".join([method, canonical_uri, cq, canon_headers, signed, payload_hash])
    date = amz_date[:8]
    scope = f"{date}/{region}/{service}/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(creq.encode()).hexdigest()])
    k = _hmac(("AWS4" + secret).encode(), date)
    for part in (region, service, "aws4_request"):
        k = _hmac(k, part)
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"


class S3:
    def __init__(self, endpoint: str, bucket: str, key_id: str, secret: str, region: str | None = None):
        u = urllib.parse.urlparse(endpoint if "://" in endpoint else "https://" + endpoint)
        self.scheme = u.scheme or "https"
        self.host = u.netloc
        self.bucket, self.key_id, self.secret = bucket, key_id, secret
        m = re.match(r"s3\.([a-z0-9-]+)\.", u.hostname or "")
        self.region = region or (m.group(1) if m else "us-east-1")

    @classmethod
    def from_env(cls) -> "S3 | None":
        e = os.environ
        need = ("SAFEVAULT_S3_ENDPOINT", "SAFEVAULT_S3_BUCKET", "SAFEVAULT_S3_KEY_ID", "SAFEVAULT_S3_SECRET")
        if not all(e.get(k) for k in need):
            return None
        return cls(e[need[0]], e[need[1]], e[need[2]], e[need[3]], e.get("SAFEVAULT_S3_REGION") or None)

    # ---- ichki ----
    def _conn(self, timeout: int = 60):
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.host, timeout=timeout)

    def _uri(self, key: str) -> str:
        return "/" + urllib.parse.quote(self.bucket + "/" + key.lstrip("/"), safe="/-_.~")

    def _request(self, method: str, key: str, body, size: int, payload_hash: str, extra: dict | None = None, timeout: int = 60):
        """Ulanishni ochib, javob sarlavhalarini o'qiydi. body: bytes | fayl obyekti | None."""
        uri = self._uri(key)
        amz = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        headers = dict(extra or {})
        auth = sign_v4(method, self.host, uri, {}, headers, payload_hash, self.key_id, self.secret, self.region, amz)
        conn = self._conn(timeout)
        try:
            conn.putrequest(method, uri, skip_host=False, skip_accept_encoding=True)
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.putheader("x-amz-date", amz)
            conn.putheader("x-amz-content-sha256", payload_hash)
            conn.putheader("Authorization", auth)
            if method in ("PUT", "POST"):
                conn.putheader("Content-Length", str(size))
            conn.endheaders()
            if isinstance(body, (bytes, bytearray)):
                conn.send(body)
            elif body is not None:
                left = size
                while left:
                    chunk = body.read(min(CHUNK, left))
                    if not chunk:
                        raise OSError("fayl kutilganidan qisqa")
                    conn.send(chunk)
                    left -= len(chunk)
            resp = conn.getresponse()
            return conn, resp
        except Exception:
            conn.close()
            raise

    def _retry(self, fn, tries: int = 3):
        last = None
        for i in range(tries):
            try:
                return fn()
            except S3Error as e:
                if e.status < 500 and e.status != 429:
                    raise
                last = e
            except (OSError, http.client.HTTPException) as e:
                last = e
            time.sleep(0.5 * (i + 1))
        raise last  # type: ignore[misc]

    # ---- ochiq metodlar ----
    def put(self, key: str, data: bytes):
        h = hashlib.sha256(data).hexdigest()

        def go():
            conn, resp = self._request("PUT", key, data, len(data), h)
            try:
                body = resp.read()
                if resp.status not in (200, 201, 204):
                    raise S3Error(resp.status, body, "PUT")
            finally:
                conn.close()

        self._retry(go)

    def put_file(self, key: str, path: str, size: int, sha256_hex: str):
        def go():
            with open(path, "rb") as f:
                conn, resp = self._request("PUT", key, f, size, sha256_hex, timeout=300)
                try:
                    body = resp.read()
                    if resp.status not in (200, 201, 204):
                        raise S3Error(resp.status, body, "PUT")
                finally:
                    conn.close()

        self._retry(go)

    def get(self, key: str) -> bytes | None:
        def go():
            conn, resp = self._request("GET", key, None, 0, hashlib.sha256(b"").hexdigest())
            try:
                body = resp.read()
                if resp.status == 404:
                    return None
                if resp.status != 200:
                    raise S3Error(resp.status, body, "GET")
                return body
            finally:
                conn.close()

        return self._retry(go)

    def open_stream(self, key: str):
        """(hajm, baytlar_iteratori). Fayl topilmasa S3Error(404)."""
        conn, resp = self._request("GET", key, None, 0, hashlib.sha256(b"").hexdigest(), timeout=300)
        if resp.status != 200:
            body = resp.read()
            conn.close()
            raise S3Error(resp.status, body, "GET")
        size = int(resp.getheader("Content-Length") or -1)

        def it():
            try:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    yield chunk
            finally:
                conn.close()

        return size, it()

    def delete(self, key: str):
        def go():
            conn, resp = self._request("DELETE", key, None, 0, hashlib.sha256(b"").hexdigest())
            try:
                body = resp.read()
                if resp.status not in (200, 204, 404):
                    raise S3Error(resp.status, body, "DELETE")
            finally:
                conn.close()

        self._retry(go)
