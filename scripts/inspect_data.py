"""Read-only look at a user_data.json (v1 or v2) as the bot would load it.

    venv/bin/python scripts/inspect_data.py ~/zonabot/user_data.json

Loads a temporary copy, since loading can move a corrupt data file aside.
Chat ids are masked in the output.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zonabot.store import Store, backup_path  # noqa: E402


def mask(chat_id):
    return f"…{chat_id[-3:]}" if len(chat_id) > 3 else "…"


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    source = Path(argv[1]).expanduser()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / source.name
        shutil.copy2(source, copy)
        if backup_path(source).exists():
            shutil.copy2(backup_path(source), backup_path(copy))
        store = Store.load(copy)
    print(f"users: {len(store.users)}  telegram_offset: {store.telegram_offset}")
    for chat_id, user in store.users.items():
        with_query = sum("?" in s.url for s in user.seen.values())
        print(
            f"  {mask(chat_id)}: notifications={user.notifications} state={user.state} "
            f"generation={user.generation} seen={len(user.seen)} (with query: {with_query}) "
            f"url_set={bool(user.url)} last_scan={user.last_scan}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
