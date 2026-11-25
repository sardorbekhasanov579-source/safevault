"""Server + Telegram bot bitta jarayonda (bitta konteyner): Render, Koyeb, Fly.io kabi joylar uchun.

Muhit o'zgaruvchilari: PORT yoki SAFEVAULT_PORT, SAFEVAULT_DATA, SAFEVAULT_AGENT_HOME, SAFEVAULT_AGENT_STATE_B64,
SAFEVAULT_TG_TOKEN / SAFEVAULT_TG_CHAT (tasdiqlash kodlari Telegramga), SAFEVAULT_ALLOWED_PHONES.
Bepul bulut (Render + Backblaze B2): SAFEVAULT_S3_ENDPOINT, _BUCKET, _KEY_ID, _SECRET, SAFEVAULT_PEPPER_B64.
Ommaviy manzil (SAFEVAULT_PUBLIC_URL yoki Render bergan RENDER_EXTERNAL_URL) bo'lsa, bot webhook rejimida ishlaydi."""
import os
import signal
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("server", "client", "agent"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from safevault_server.app import create_server  # noqa: E402


def main():
    port = int(os.environ.get("PORT") or os.environ.get("SAFEVAULT_PORT") or "8080")
    data = os.environ.get("SAFEVAULT_DATA", "/data")
    srv = create_server(data, os.environ.get("SAFEVAULT_HOST", "0.0.0.0"), port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"SafeVault server: port {port}, ma'lumotlar: {os.path.abspath(data)}", flush=True)

    def bye(*_):  # xizmat to'xtashidan oldin bazani omborga yozib qo'yamiz
        try:
            srv.svc.s.flush()
        finally:
            os._exit(0)

    signal.signal(signal.SIGTERM, bye)
    os.environ.setdefault("SAFEVAULT_AGENT_SERVER", f"http://127.0.0.1:{port}")
    public = os.environ.get("SAFEVAULT_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")

    if public and srv.svc.s.s3:
        from safevault_agent.cloud import start_webhook

        try:
            start_webhook(srv.svc, public)
        except SystemExit as e:
            print(f"[agent] to'xtadi: {e}", file=sys.stderr, flush=True)
        while True:  # server va webhook oqimlari ishlab turadi
            time.sleep(3600)

    from safevault_agent.cloud import run_cloud

    while True:  # bot qulasa qayta ishga tushiriladi; server doim ishlab turadi
        try:
            if not run_cloud():
                break
        except SystemExit as e:
            print(f"[agent] to'xtadi: {e}", file=sys.stderr, flush=True)
            break
        except Exception as e:  # noqa: BLE001
            print(f"[agent] xato: {type(e).__name__}; 10 soniyadan keyin qayta uriniladi", file=sys.stderr, flush=True)
            time.sleep(10)
    while True:  # agent yo'q bo'lsa ham server o'chmasin
        time.sleep(3600)


if __name__ == "__main__":
    main()
