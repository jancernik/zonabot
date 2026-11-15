"""The `world` fixture wires the real store, service, scheduler and bot to a fake browser, Telegram and clock."""
import random
from dataclasses import dataclass, replace

import pytest

from fakes import FakeBrowser, FakeClock, FakeTelegram, callback_update, message_update
from zonabot.bot import Bot
from zonabot.config import Settings
from zonabot.scheduler import Scheduler
from zonabot.service import SubscriptionService
from zonabot.store import Store
from zonabot.urls import normalize_search_url, page_url

SEARCH = "https://www.zonaprop.com.ar/departamentos-alquiler-palermo.html"
WATCHED = normalize_search_url(SEARCH)
CHAT = "42"

TEST_SETTINGS = Settings(token="test-token", page_pause=(0.0, 0.0), startup_stagger=(0.0, 0.0))


@dataclass
class World:
    settings: Settings
    store: Store
    browser: FakeBrowser
    telegram: FakeTelegram
    clock: FakeClock
    service: SubscriptionService
    scheduler: Scheduler
    bot: Bot
    _update_id: int = 0

    def page(self, number, *responses, url=WATCHED):
        self.browser.script(page_url(url, number), *responses)

    def send(self, text, chat_id=CHAT):
        self._update_id += 1
        self.bot.handle_update(message_update(self._update_id, chat_id, text))

    def press(self, data, chat_id=CHAT, message_id=7):
        self._update_id += 1
        self.bot.handle_update(callback_update(self._update_id, chat_id, data, message_id))

    def subscribe(self, chat_id=CHAT, url=SEARCH):
        """Sends /start and the URL, runs the baseline and clears recorded messages."""
        self.send("/start", chat_id)
        self.send(url, chat_id)
        self.run_due()
        self.telegram.sent.clear()

    def run_due(self):
        return self.scheduler.run_pending()

    def tick(self, seconds=None):
        """Advance past the next regular check and run what is due."""
        self.clock.advance(seconds if seconds is not None else self.settings.check_interval[1] + 1)
        return self.run_due()

    def user(self, chat_id=CHAT):
        return self.store.get(chat_id)

    def listings_sent(self, chat_id=CHAT):
        return self.telegram.listing_texts(chat_id)

    def reload_store(self):
        return Store.load(self.store.path, clock=self.clock)


def make_world(tmp_path, **overrides):
    settings = replace(TEST_SETTINGS, **overrides)
    clock = FakeClock()
    store = Store(tmp_path / "user_data.json", clock=clock)
    browser = FakeBrowser()
    telegram = FakeTelegram()
    rng = random.Random(1234)
    service = SubscriptionService(store, browser, telegram, settings, clock=clock, rng=rng, sleep=clock.sleep)
    scheduler = Scheduler(service.run, interval=settings.check_interval, clock=clock, rng=rng)
    bot = Bot(store, telegram, scheduler)
    return World(settings, store, browser, telegram, clock, service, scheduler, bot)


@pytest.fixture
def world(tmp_path):
    return make_world(tmp_path)
