import threading
from pathlib import Path

from fakes import message_update
from pages import results_page
from world import CHAT, SEARCH, make_world
from zonabot import app as app_module
from zonabot import texts
from zonabot.app import App, build
from zonabot.config import Settings
from zonabot.store import Store
from zonabot.telegram_api import TelegramError


def make_app(world, **kwargs):
    return App(world.settings, world.store, world.telegram, world.scheduler, world.bot,
               clock=world.clock, resource_check=kwargs.pop("resource_check", lambda: None), **kwargs)


def test_restart_schedules_enabled_subscriptions_without_messages(tmp_path):
    world = make_world(tmp_path)
    world.page(1, results_page([1]))
    world.subscribe()
    world.send("/start", "7")
    world.send(SEARCH, "7")
    world.send(texts.MENU_TOGGLE, "7")
    world.send("/start", "8")

    restarted = make_world(tmp_path)
    restarted.store = world.reload_store()
    restarted.service.store = restarted.bot.store = restarted.store
    make_app(restarted).schedule_existing_subscriptions()
    assert [j.chat_id for j in restarted.scheduler.pending()] == [CHAT]
    restarted.page(1, results_page([1]))
    restarted.run_due()
    assert restarted.telegram.sent == []


def test_poll_handles_updates_and_persists_the_offset(world):
    app = make_app(world)
    world.telegram.updates.extend([message_update(10, CHAT, "/start"), message_update(11, CHAT, "hola")])
    assert app.poll_once() == 2
    assert world.reload_store().telegram_offset == 12
    assert world.telegram.texts()[:3] == list(texts.WELCOME)

    calls = []
    world.telegram.get_updates = lambda offset=None, timeout=0: calls.append(offset) or []
    app.poll_once()
    assert calls == [12]


def test_a_failing_handler_does_not_block_later_updates(world):
    app = make_app(world)
    handled = []

    def handle(update):
        handled.append(update["update_id"])
        if update["update_id"] == 1:
            raise RuntimeError("bug")

    world.bot.handle_update = handle
    world.telegram.updates.extend([message_update(1, CHAT, "a"), message_update(2, CHAT, "b")])
    app.poll_once()
    assert handled == [1, 2] and world.store.telegram_offset == 3


def test_telegram_errors_are_survived(world):
    app = make_app(world)

    def fail(offset=None, timeout=0):
        raise TelegramError("502")

    world.telegram.get_updates = fail
    app.stop_event.set()
    assert app.poll_once() == 0


def test_run_forever_stops_cleanly_and_saves(world):
    app = make_app(world)
    polls = threading.Event()

    def get_updates(offset=None, timeout=0):
        polls.set()
        app.stop_event.wait(0.01)
        return []

    world.telegram.get_updates = get_updates
    thread = threading.Thread(target=app.run_forever)
    thread.start()
    assert polls.wait(1)
    app.request_stop()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert world.store.path.exists()


def test_run_forever_logs_resources_every_interval(world):
    checks = []
    app = make_app(world, resource_check=lambda: checks.append(world.clock.monotonic()))
    polls = []

    def get_updates(offset=None, timeout=0):
        polls.append(1)
        world.clock.advance(200)
        if len(polls) == 3:
            app.request_stop()
        return []

    world.telegram.get_updates = get_updates
    app.run_forever()
    assert len(checks) == 2


def test_build_wires_without_network(tmp_path):
    app = build(Settings(token="t"), Store(tmp_path / "d.json"))
    assert app.scheduler is app.bot.scheduler


def test_run_refuses_to_start_without_token(monkeypatch):
    monkeypatch.setattr(app_module, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "configure_logging", lambda *a, **k: None)
    assert app_module.run() == 1


def test_run_refuses_to_start_on_unrecoverable_data(monkeypatch, tmp_path):
    (tmp_path / "user_data.json").write_text("{broken")
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("ZONABOT_DATA_FILE", str(tmp_path / "user_data.json"))
    for name in ("load_dotenv", "configure_logging"):
        monkeypatch.setattr(app_module, name, lambda *a, **k: None)
    waits = []
    monkeypatch.setattr(app_module, "wait_for_display", lambda timeout: waits.append(timeout) or False)
    monkeypatch.setattr(app_module.resources, "log_startup_resources", lambda: None)
    assert app_module.run() == 1
    assert waits == [app_module.DISPLAY_WAIT]


def test_main_entrypoint_delegates_to_the_app():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    assert "from zonabot.app import run" in source
