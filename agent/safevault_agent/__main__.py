import sys

from safevault_client.client import VaultClient

from . import setup as setup_mod
from .bot import Bot
from .state import State, new_pairing_code
from .tg import Telegram
from safevault_client import crypto as C


def main():
    st = State()
    if "--setup" in sys.argv or not st.ready:
        st = setup_mod.run_setup(st)
    elif st.get("owner_chat") is None and not st.get("pair_code"):
        st.set(pair_code=new_pairing_code())
    if st.get("owner_chat") is None:
        print(f"Bot hali ulanmagan. Telegram'da botga yuboring:  /ulash {st.get('pair_code')}")
    vault = VaultClient(st.get("server"), st.get("device_id"))
    vault.token, vault.mk = st.get("token"), C.b64d(st.get("mk"))
    try:
        Bot(st, Telegram(st.get("tg_token")), vault).run()
    except KeyboardInterrupt:
        print("\nTo'xtatildi.")


main()
