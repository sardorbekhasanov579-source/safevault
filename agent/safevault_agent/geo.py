"""Koordinatadan taxminiy manzil (OpenStreetMap Nominatim). Faqat egasi /joylashuv so'raganda, uning o'z kompyuteridan chaqiriladi."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request


def reverse_geocode(lat: float, lon: float, base_url: str = "https://nominatim.openstreetmap.org") -> str | None:
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": 18, "accept-language": "uz,ru,en"})
    req = urllib.request.Request(f"{base_url}/reverse?{q}", headers={"User-Agent": "SafeVault/0.2 (personal backup app)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            name = json.loads(r.read()).get("display_name")
        return str(name)[:200] if name else None
    except Exception:  # noqa: BLE001  (manzil ixtiyoriy)
        return None
