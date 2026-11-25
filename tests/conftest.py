import os
import re
import sqlite3
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "client"))
sys.path.insert(0, os.path.join(ROOT, "agent"))

from safevault_server.app import create_server  # noqa: E402
from safevault_client.client import VaultClient  # noqa: E402


class Env:
    def __init__(self, data_dir, url):
        self.data_dir, self.url = data_dir, url

    def client(self, device="phone-1"):
        return VaultClient(self.url, device)

    def last_code(self, kind_prefix: str, target: str) -> str:
        """Dev 'SMS/email' qutisidan (outbox) oxirgi kodni o'qiydi."""
        con = sqlite3.connect(os.path.join(self.data_dir, "vault.db"))
        row = con.execute("SELECT message FROM outbox WHERE kind=? AND target=? ORDER BY id DESC LIMIT 1",
                          (kind_prefix, target)).fetchone()
        con.close()
        return re.search(r"(\d{6})", row[0]).group(1)

    def notices(self, target: str):
        con = sqlite3.connect(os.path.join(self.data_dir, "vault.db"))
        rows = con.execute("SELECT message FROM outbox WHERE kind='notice-email' AND target=?", (target,)).fetchall()
        con.close()
        return [r[0] for r in rows]


@pytest.fixture()
def env(tmp_path):
    srv = create_server(str(tmp_path), "127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield Env(str(tmp_path), f"http://127.0.0.1:{port}")
    srv.shutdown()
    srv.server_close()
