"""User state persisted as JSON (schema 2), with v1 migration, atomic saves and a .bak copy."""
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .listings import canonical_listing_url, listing_id

logger = logging.getLogger(__name__)

SCHEMA = 2
PENDING_BASELINE = "pending_baseline"
ACTIVE = "active"


class StoreError(Exception):
    pass


def backup_path(path):
    return path.with_name(path.name + ".bak")


@dataclass
class SeenListing:
    url: str
    first_seen: float
    last_seen: float


@dataclass
class User:
    url: str | None = None
    original_url: str | None = None
    notifications: bool = True
    awaiting_url: bool = False
    state: str = PENDING_BASELINE
    generation: int = 0
    seen: dict = field(default_factory=dict)
    last_scan: str | None = None
    consecutive_failures: int = 0
    failure_notice_sent: bool = False

    def to_dict(self):
        data = asdict(self)
        data["seen"] = {lid: asdict(s) for lid, s in self.seen.items()}
        return data

    @classmethod
    def from_dict(cls, data):
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known["seen"] = {lid: SeenListing(**s) for lid, s in (data.get("seen") or {}).items()}
        return cls(**known)

    def new_generation(self):
        """Invalidate queued and in-flight checks for this chat."""
        self.generation += 1
        self.consecutive_failures = 0
        self.failure_notice_sent = False


def migrate_v1(data, now):
    """Pre-refactor format: {chat_id: {url, original_url, notifications, last_seen_links, initialized, ...}}."""
    users = {}
    for chat_id, old in data.items():
        seen = {}
        for link in old.get("last_seen_links") or []:
            lid = listing_id(link)
            if lid and lid not in seen:
                seen[lid] = SeenListing(canonical_listing_url(link), now, now)
        users[str(chat_id)] = User(
            url=old.get("url"),
            original_url=old.get("original_url"),
            notifications=bool(old.get("notifications", True)),
            awaiting_url=bool(old.get("awaiting_url", False)),
            state=ACTIVE if old.get("initialized") else PENDING_BASELINE,
            seen=seen,
            last_scan=old.get("last_scan"),
        )
    return users


class Store:
    def __init__(self, path, users=None, telegram_offset=None, clock=time):
        self.path = Path(path)
        self.users = users if users is not None else {}
        self.telegram_offset = telegram_offset
        self.lock = threading.RLock()
        self._clock = clock

    @property
    def backup_path(self):
        return backup_path(self.path)

    @classmethod
    def load(cls, path, clock=time):
        """A corrupt file is moved aside only once the backup has loaded, so a refused start
        is refused again on every restart."""
        path = Path(path)
        backup = backup_path(path)
        try:
            return cls._from_data(path, _read(path), clock)
        except FileNotFoundError:
            if not backup.exists():
                return cls(path, clock=clock)
            corrupt = False
        except ValueError as exc:
            corrupt = True
            logger.error(f"Data file {path} is corrupt ({exc})")

        try:
            data = _read(backup)
        except (FileNotFoundError, ValueError) as exc:
            raise StoreError(f"No usable user data: {path} is corrupt or missing and {backup} failed ({exc})") from exc
        store = cls._from_data(path, data, clock)
        if corrupt:
            corrupt_copy = path.with_name(f"{path.name}.corrupt-{int(clock.time())}")
            os.replace(path, corrupt_copy)
            logger.error(f"Moved the corrupt data file to {corrupt_copy}")
        logger.warning(f"Loaded user data from backup {backup}")
        return store

    @classmethod
    def _from_data(cls, path, data, clock):
        if "schema" not in data:
            logger.info(f"Migrating {len(data)} users from the v1 data format")
            return cls(path, migrate_v1(data, clock.time()), None, clock)
        if data["schema"] != SCHEMA:
            raise StoreError(f"Unsupported data schema {data['schema']!r} in {path}")
        users = {chat: User.from_dict(u) for chat, u in data.get("users", {}).items()}
        return cls(path, users, data.get("telegram_offset"), clock)

    def to_data(self):
        with self.lock:
            return {
                "schema": SCHEMA,
                "telegram_offset": self.telegram_offset,
                "users": {chat: user.to_dict() for chat, user in self.users.items()},
            }

    def save(self):
        """Write to a temp file and rename it over the data file; the previous version goes to .bak."""
        with self.lock:
            payload = json.dumps(self.to_data(), indent=2, ensure_ascii=False)
            tmp = self.path.with_name(f".{self.path.name}.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
            os.replace(tmp, self.path)

    def get(self, chat_id):
        return self.users.get(str(chat_id))

    def add_user(self, chat_id):
        with self.lock:
            user = self.users[str(chat_id)] = User()
            return user

    def prune_seen(self, user, now, retention_days):
        cutoff = now - retention_days * 86400
        user.seen = {lid: s for lid, s in user.seen.items() if s.last_seen >= cutoff}


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value is not an object")
    return data
