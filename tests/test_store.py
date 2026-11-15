import json
import os

import pytest

from fakes import FakeClock
from zonabot.store import ACTIVE, PENDING_BASELINE, SeenListing, Store, StoreError, User

BASE = "https://www.zonaprop.com.ar/propiedades/clasificado/alclapin-departamento-"


def tracked(listing, search_id, pos=1):
    return f"{BASE}{listing}.html?n_src=Listado&n_pg=1&n_pos={pos}&n_search_id={search_id}"


def v1_user(**overrides):
    user = {
        "url": "https://www.zonaprop.com.ar/x-publicado-hace-menos-de-1-dia-orden-publicado-descendente.html",
        "original_url": "https://www.zonaprop.com.ar/x.html",
        "notifications": False,
        "last_seen_links": [tracked(1, "a"), tracked(2, "a", 2), tracked(1, "b", 7), tracked(3, "c"), tracked(2, "c")],
        "last_scan": "2026-11-12 19:58:52",
        "awaiting_url": False,
        "initialized": True,
    }
    user.update(overrides)
    return user


@pytest.fixture
def clock():
    return FakeClock(start=1_800_000_000)


def test_missing_file_is_an_empty_store(tmp_path, clock):
    store = Store.load(tmp_path / "user_data.json", clock=clock)
    assert store.users == {} and store.telegram_offset is None


def test_round_trip(tmp_path, clock):
    store = Store(tmp_path / "user_data.json", clock=clock)
    user = store.add_user("42")
    user.url, user.state, user.generation = "u", ACTIVE, 3
    user.seen = {"1": SeenListing(f"{BASE}1.html", 1.0, 2.0)}
    store.telegram_offset = 99
    store.save()
    loaded = Store.load(store.path, clock=clock)
    assert loaded.users == store.users and loaded.telegram_offset == 99
    assert json.loads(store.path.read_text())["schema"] == 2


def test_v1_migration_dedupes_tracking_links_by_listing_id(tmp_path, clock):
    path = tmp_path / "user_data.json"
    path.write_text(json.dumps({"42": v1_user()}))
    user = Store.load(path, clock=clock).get("42")
    assert list(user.seen) == ["1", "2", "3"]
    assert user.seen["1"] == SeenListing(f"{BASE}1.html", clock.time(), clock.time())
    assert (user.url, user.original_url, user.notifications, user.last_scan) == (
        v1_user()["url"], v1_user()["original_url"], False, "2026-11-12 19:58:52",
    )
    assert user.state == ACTIVE and user.generation == 0 and user.awaiting_url is False


def test_v1_migration_maps_uninitialized_users_to_pending_baseline(tmp_path, clock):
    path = tmp_path / "user_data.json"
    path.write_text(json.dumps({"7": v1_user(initialized=False, last_seen_links=[], notifications=True), "8": {"url": None}}))
    store = Store.load(path, clock=clock)
    assert store.get("7").state == PENDING_BASELINE and store.get("7").notifications is True
    assert store.get("8") == User(url=None)


def test_v1_migration_of_the_production_shape(tmp_path, clock):
    """Every listing is stored several times, once per tracking query."""
    links = [tracked(60680000 + i, f"s{j}", pos=i) for j in range(8) for i in range(28)] + [tracked(60690000 + i, "z") for i in range(4)]
    path = tmp_path / "user_data.json"
    path.write_text(json.dumps({"870000000": v1_user(last_seen_links=links[:230])}))
    user = Store.load(path, clock=clock).get("870000000")
    assert len(user.seen) == len({link.split("-")[-1].split(".")[0] for link in links[:230]})
    assert all("?" not in s.url for s in user.seen.values())


def test_save_is_atomic_and_keeps_previous_version_as_backup(tmp_path, clock):
    store = Store(tmp_path / "user_data.json", clock=clock)
    store.add_user("1")
    store.save()
    first = store.path.read_text()
    store.add_user("2")
    store.save()
    assert store.backup_path.read_text() == first
    assert set(json.loads(store.path.read_text())["users"]) == {"1", "2"}
    assert not list(tmp_path.glob(".*.tmp"))


def test_failed_save_keeps_previous_data(tmp_path, clock, monkeypatch):
    store = Store(tmp_path / "user_data.json", clock=clock)
    store.add_user("1")
    store.save()
    before = store.path.read_text()

    def disk_full(fd):
        raise OSError("disk full")

    store.add_user("2")
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", disk_full)
        with pytest.raises(OSError):
            store.save()
    assert store.path.read_text() == before


def test_corrupt_file_recovers_from_backup_and_keeps_the_corrupt_copy(tmp_path, clock):
    store = Store(tmp_path / "user_data.json", clock=clock)
    store.add_user("1").url = "u"
    store.save()
    store.save()
    corrupt = b'{"schema": 2, "users": {"1": {"url": '
    store.path.write_bytes(corrupt)

    loaded = Store.load(store.path, clock=clock)
    assert loaded.get("1").url == "u"
    kept = list(tmp_path.glob("user_data.json.corrupt-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == corrupt


def test_corrupt_file_without_backup_refuses_every_start(tmp_path, clock):
    """systemd restarts the bot after a refusal; the restart must not come up empty."""
    path = tmp_path / "user_data.json"
    corrupt = b'{"42": {"url": "https://www.zonaprop.com.ar/x.html", "notif'
    path.write_bytes(corrupt)
    for _ in range(2):
        with pytest.raises(StoreError):
            Store.load(path, clock=clock)
    assert [p.name for p in tmp_path.iterdir()] == ["user_data.json"] and path.read_bytes() == corrupt


def test_corrupt_file_with_a_corrupt_backup_refuses_every_start(tmp_path, clock):
    path = tmp_path / "user_data.json"
    path.write_bytes(b"{")
    path.with_name("user_data.json.bak").write_bytes(b"{")
    for _ in range(2):
        with pytest.raises(StoreError):
            Store.load(path, clock=clock)
    assert path.read_bytes() == b"{"


def test_unknown_schema_is_refused(tmp_path, clock):
    path = tmp_path / "user_data.json"
    path.write_text(json.dumps({"schema": 3, "users": {}}))
    with pytest.raises(StoreError):
        Store.load(path, clock=clock)


def test_prune_drops_listings_not_seen_within_retention(clock):
    store = Store("unused.json", clock=clock)
    user = store.add_user("1")
    now = clock.time()
    user.seen = {"old": SeenListing("o", now - 40 * 86400, now - 31 * 86400), "recent": SeenListing("r", now - 40 * 86400, now - 29 * 86400)}
    store.prune_seen(user, now, 30)
    assert list(user.seen) == ["recent"]


def test_new_generation_resets_failure_tracking():
    user = User(generation=4, consecutive_failures=3, failure_notice_sent=True)
    user.new_generation()
    assert (user.generation, user.consecutive_failures, user.failure_notice_sent) == (5, 0, False)
