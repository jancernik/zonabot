"""Subscription checks: baseline, regular check, forced check, delivery and failure handling.

All browser and Telegram I/O happens outside the store lock. Results are committed only if the
chat's `generation` is unchanged, so a URL change or disable during a check discards it.
"""
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime

from . import texts
from .listings import PageKind, parse_results_page
from .store import ACTIVE, PENDING_BASELINE, SeenListing
from .urls import page_url

logger = logging.getLogger(__name__)


class FetchFailed(Exception):
    pass


@dataclass(frozen=True)
class Outcome:
    status: str
    reschedule: bool = True
    delay: float | None = None


class SubscriptionService:
    def __init__(self, store, browser, telegram, settings, clock=time, rng=None, sleep=time.sleep):
        self.store = store
        self.browser = browser
        self.telegram = telegram
        self.settings = settings
        self.clock = clock
        self.rng = rng or random.Random()
        self.sleep = sleep
        self._failures_in_a_row = 0
        self._admin_alerted = False

    def run(self, chat_id, generation, forced=False):
        with self.store.lock:
            user = self.store.get(chat_id)
            if user is None or user.generation != generation or not user.url:
                return Outcome("skipped", reschedule=False)
            if not user.notifications and not forced:
                return Outcome("skipped", reschedule=False)
            if not user.notifications:
                mode = "peek"
            elif user.state == PENDING_BASELINE:
                mode = "baseline"
            else:
                mode = "check"
            url = user.url
            seen_ids = set(user.seen)

        try:
            if mode == "peek":
                pages = self._fetch(url, 1)
            elif mode == "baseline":
                pages = self._fetch(url, self.settings.baseline_max_pages)
            else:
                pages = self._fetch(
                    url, self.settings.check_max_pages,
                    keep_going=lambda page: all(listing.id not in seen_ids for listing in page.listings),
                )
        except FetchFailed as exc:
            return self._on_failure(chat_id, generation, mode, forced, exc)

        self._on_fetch_success()
        if mode == "peek":
            self._send(chat_id, texts.forced_while_disabled(_total(pages)))
            return Outcome("peeked", reschedule=False)
        if mode == "baseline":
            return self._commit_baseline(chat_id, generation, pages)
        return self._commit_check(chat_id, generation, url, pages, forced)

    def _fetch(self, url, max_pages, keep_going=None):
        pages = []
        for number in range(1, max_pages + 1):
            if number > 1:
                self.sleep(self.rng.uniform(*self.settings.page_pause))
            try:
                result = self.browser.load(page_url(url, number))
            except Exception as exc:
                raise FetchFailed(f"page {number}: {type(exc).__name__}: {exc}") from exc
            page = parse_results_page(result.html, result.url)
            if page.kind is PageKind.UNRECOGNIZED:
                raise FetchFailed(f"page {number} is not a results page ({result.url})")
            if number > 1 and page.page != number:
                break  # Zonaprop redirects pages past the end to page 1.
            pages.append(page)
            if not page.has_next or (keep_going and not keep_going(page)):
                break
        return pages

    def _current(self, chat_id, generation):
        user = self.store.get(chat_id)
        if user is not None and user.generation == generation and user.notifications:
            return user
        return None

    def _commit_baseline(self, chat_id, generation, pages):
        now = self.clock.time()
        with self.store.lock:
            user = self._current(chat_id, generation)
            if user is None:
                return Outcome("discarded", reschedule=False)
            user.seen = {l.id: SeenListing(l.url, now, now) for l in _unique(pages)}
            user.state = ACTIVE
            self._mark_success(user, now)
            self.store.save()
        logger.info(f"Baseline for {chat_id}: {len(user.seen)} listings over {len(pages)} page(s)")
        self._send(chat_id, texts.baseline_summary(_total(pages)))
        return Outcome("baseline")

    def _commit_check(self, chat_id, generation, url, pages, forced):
        now = self.clock.time()
        present = _unique(pages)
        with self.store.lock:
            user = self._current(chat_id, generation)
            if user is None:
                return Outcome("discarded", reschedule=False)
            new = [l for l in present if l.id not in user.seen]
            for listing in present:
                if listing.id in user.seen:
                    user.seen[listing.id].last_seen = now
                else:
                    user.seen[listing.id] = SeenListing(listing.url, now, now)
            self.store.prune_seen(user, now, self.settings.seen_retention_days)
            recovered = user.failure_notice_sent
            self._mark_success(user, now)
            self.store.save()
        logger.info(f"Check for {chat_id}: {len(present)} listings, {len(new)} new")
        if recovered:
            self._send(chat_id, texts.CHECKS_RECOVERED)
        self._deliver(chat_id, generation, url, new)
        if forced and not new:
            self._send(chat_id, texts.forced_nothing_new(_total(pages)))
        return Outcome("checked")

    def _deliver(self, chat_id, generation, search_url, new):
        """Newest `flood_cap` listings one by one (oldest of them first), then one digest for the rest."""
        cap = self.settings.flood_cap
        individual = list(reversed(new[:cap]))
        remaining = len(new) - len(individual)
        messages = [(listing.url, False) for listing in individual]
        if remaining:
            messages.append((texts.digest(remaining, search_url), True))
        sent = 0
        for index, (text, is_digest) in enumerate(messages):
            with self.store.lock:
                if self._current(chat_id, generation) is None:
                    logger.info(f"Stopping delivery to {chat_id}: subscription changed")
                    return sent
            last = index == len(messages) - 1
            if self._send(chat_id, text, texts.disable_button() if last else None, preview=not is_digest):
                sent += 1
        return sent

    def _mark_success(self, user, now):
        user.consecutive_failures = 0
        user.failure_notice_sent = False
        user.last_scan = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

    def _on_failure(self, chat_id, generation, mode, forced, exc):
        logger.warning(f"{mode} for {chat_id} failed: {exc}")
        self._failures_in_a_row += 1
        notice = None
        failures = 1
        with self.store.lock:
            user = self.store.get(chat_id)
            if user is not None and user.generation == generation:
                user.consecutive_failures += 1
                failures = user.consecutive_failures
                if not user.failure_notice_sent:
                    if mode == "baseline" and failures >= self.settings.baseline_failures_before_notice:
                        notice = texts.BASELINE_STILL_TRYING
                    elif mode == "check" and failures >= self.settings.check_failures_before_notice:
                        notice = texts.checks_failing(user.last_scan)
                    user.failure_notice_sent = notice is not None
                self.store.save()
        if notice:
            self._send(chat_id, notice)
        elif forced:
            self._send(chat_id, texts.FETCH_FAILED)
        self._maybe_alert_admin(exc)
        delays = self.settings.retry_delays
        return Outcome("failed", delay=delays[min(failures, len(delays)) - 1])

    def _on_fetch_success(self):
        if self._admin_alerted and self.settings.admin_chat_id:
            self._send(self.settings.admin_chat_id, texts.ADMIN_RECOVERED)
        self._failures_in_a_row = 0
        self._admin_alerted = False

    def _maybe_alert_admin(self, exc):
        if (
            self.settings.admin_chat_id
            and not self._admin_alerted
            and self._failures_in_a_row >= self.settings.admin_alert_after_failures
        ):
            self._admin_alerted = True
            self._send(self.settings.admin_chat_id, texts.admin_failures(self._failures_in_a_row, exc))

    def _send(self, chat_id, text, reply_markup=None, preview=True):
        try:
            return self.telegram.send_message(chat_id, text, reply_markup=reply_markup, disable_web_page_preview=not preview)
        except Exception as exc:
            logger.error(f"Sending to {chat_id} failed: {exc}")
            return False


def _unique(pages):
    listings, ids = [], set()
    for page in pages:
        for listing in page.listings:
            if listing.id not in ids:
                ids.add(listing.id)
                listings.append(listing)
    return listings


def _total(pages):
    first = pages[0]
    if first.kind is PageKind.EMPTY:
        return 0
    return first.total if first.total is not None else len(_unique(pages))
