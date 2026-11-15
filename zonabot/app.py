"""Telegram long polling runs on the main thread and browser jobs on the scheduler thread."""
import logging
import os
import random
import signal
import sys
import threading
import time

from dotenv import load_dotenv

from . import resources
from .bot import Bot
from .browser import SeleniumBaseBrowser, wait_for_display
from .config import Settings
from .logging_setup import configure_logging
from .scheduler import Scheduler
from .service import SubscriptionService
from .store import Store, StoreError
from .telegram_api import TelegramClient, TelegramError

logger = logging.getLogger(__name__)

DISPLAY_WAIT = 120


class App:
    def __init__(self, settings, store, telegram, scheduler, bot, clock=time, rng=None,
                 resource_check=resources.check_resources, reboot=resources.reboot_system, poll_timeout=30):
        self.settings = settings
        self.store = store
        self.telegram = telegram
        self.scheduler = scheduler
        self.bot = bot
        self.clock = clock
        self.rng = rng or random.Random()
        self.resource_check = resource_check
        self.reboot = reboot
        self.poll_timeout = poll_timeout
        self.stop_event = threading.Event()
        self.reboot_requested = False

    def schedule_existing_subscriptions(self):
        """Resumes after a restart without messaging anyone. Pending chats re-run their baseline and
        active chats continue with regular checks."""
        with self.store.lock:
            subscriptions = [(c, u.generation) for c, u in self.store.users.items() if u.notifications and u.url]
        for chat_id, generation in subscriptions:
            self.scheduler.schedule(chat_id, generation, delay=self.rng.uniform(*self.settings.startup_stagger))
        logger.info(f"Scheduled {len(subscriptions)} subscription(s)")

    def poll_once(self):
        try:
            updates = self.telegram.get_updates(self.store.telegram_offset, timeout=self.poll_timeout)
        except TelegramError as exc:
            logger.error(f"getUpdates failed: {exc}")
            self.stop_event.wait(5)
            return 0
        for update in updates:
            try:
                self.bot.handle_update(update)
            except Exception:
                logger.exception(f"Error handling update {update.get('update_id')}")
            with self.store.lock:
                self.store.telegram_offset = update["update_id"] + 1
                self.store.save()
        return len(updates)

    def request_stop(self, *_):
        logger.info("Stop requested")
        self.stop_event.set()

    def run_forever(self):
        self.schedule_existing_subscriptions()
        self.scheduler.start()
        last_resource_check = self.clock.monotonic()
        while not self.stop_event.is_set():
            if self.clock.monotonic() - last_resource_check > resources.CHECK_INTERVAL:
                self.resource_check(self._reboot)
                last_resource_check = self.clock.monotonic()
            try:
                self.poll_once()
            except Exception:
                logger.exception("Error in polling loop")
                self.stop_event.wait(5)
        self.shutdown(job_timeout=60 if self.reboot_requested else 120)
        if self.reboot_requested:
            try:
                self.reboot()
            except Exception as exc:
                logger.error(f"Failed to reboot system: {exc}")
                sys.exit(1)

    def shutdown(self, job_timeout=120):
        logger.info("Shutting down: waiting for the running check to finish")
        if not self.scheduler.stop(timeout=job_timeout):
            logger.warning("A check is still running; exiting without waiting for it")
        self.store.save()
        logger.info("Shutdown complete")

    def _reboot(self):
        self.reboot_requested = True
        self.stop_event.set()


def build(settings, store):
    telegram = TelegramClient(settings.token)
    service = SubscriptionService(store, SeleniumBaseBrowser(), telegram, settings)
    scheduler = Scheduler(service.run, interval=settings.check_interval)
    return App(settings, store, telegram, scheduler, Bot(store, telegram, scheduler))


def run():
    load_dotenv()
    configure_logging()
    settings = Settings.from_env()
    logger.info("=" * 60)
    logger.info("Starting ZonaProp Bot")
    logger.info("=" * 60)
    if not settings.token:
        logger.critical("TELEGRAM_TOKEN is not set")
        return 1
    if wait_for_display(timeout=DISPLAY_WAIT):
        logger.info(f"Desktop display ready (DISPLAY={os.environ.get('DISPLAY')}, XAUTHORITY={os.environ.get('XAUTHORITY')})")
    else:
        logger.warning(f"Desktop display not up after {DISPLAY_WAIT} s; checks will retry until it is")
    resources.log_startup_resources()
    try:
        store = Store.load(settings.data_file)
    except StoreError as exc:
        logger.critical(f"Refusing to start: {exc}")
        return 1
    app = build(settings, store)
    signal.signal(signal.SIGINT, app.request_stop)
    signal.signal(signal.SIGTERM, app.request_stop)
    logger.info("Bot is running and ready for messages...")
    app.run_forever()
    return 0
