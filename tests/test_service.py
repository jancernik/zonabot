"""Subscription lifecycle driven through the bot, scheduler and service."""
import json
import threading

import pytest

from fakes import FakeTelegram
from pages import challenge_page, empty_page, real_page, results_page
from world import CHAT, SEARCH, WATCHED, make_world
from zonabot import texts
from zonabot.browser import FetchResult
from zonabot.store import ACTIVE, PENDING_BASELINE, SeenListing
from zonabot.urls import normalize_search_url, page_url

LISTING = "https://www.zonaprop.com.ar/propiedades/clasificado/alclapin-departamento-{}.html"


def ids(*numbers):
    return [LISTING.format(n) for n in numbers]


def subscribed(world, *page1_ids, **page_kwargs):
    world.page(1, results_page(list(page1_ids), **page_kwargs))
    world.subscribe()


# Subscription and baseline

def test_submitting_a_url_baselines_with_one_summary_and_no_listing_messages(world):
    world.page(1, lambda url: real_page("user-search-p1"))
    world.send("/start")
    world.telegram.sent.clear()
    world.send(SEARCH)
    assert world.telegram.texts(CHAT) == [texts.link_set(SEARCH)]
    assert world.user().state == PENDING_BASELINE and world.user().url == WATCHED

    assert world.run_due() == 1
    assert world.telegram.texts(CHAT)[1:] == [texts.baseline_summary(26)]
    assert world.listings_sent() == []
    assert world.user().state == ACTIVE and len(world.user().seen) == 26


def test_baseline_reads_every_page_until_the_site_redirects_past_the_end(world):
    p1 = page_url(WATCHED, 1)
    world.page(1, results_page(list(range(1, 31)), total=65, has_next=True))
    world.page(2, results_page(list(range(31, 61)), total=65, has_next=True))
    world.page(3, FetchResult(p1, results_page(list(range(1, 31)), total=65, has_next=True)))
    world.subscribe()
    assert world.browser.fetched == [page_url(WATCHED, n) for n in (1, 2, 3)]
    assert len(world.user().seen) == 60


def test_baseline_stops_at_the_page_cap(tmp_path):
    world = make_world(tmp_path, baseline_max_pages=2)
    for n in (1, 2, 3):
        world.page(n, results_page([n * 100 + i for i in range(30)], total=900, has_next=True))
    world.subscribe()
    assert len(world.browser.fetched) == 2 and len(world.user().seen) == 60


def test_baseline_summary_uses_the_site_total(world):
    world.page(1, results_page([1, 2], total=577, has_next=False))
    world.send("/start")
    world.send(SEARCH)
    world.run_due()
    assert world.telegram.texts()[-1] == texts.baseline_summary(577)


def test_genuine_empty_baseline_then_first_listing_is_notified(world):
    world.page(1, empty_page(), results_page([1]))
    world.subscribe()
    world.tick()
    assert world.listings_sent() == ids(1)


def test_blocked_baseline_retries_with_backoff_and_never_floods(world):
    world.page(1, challenge_page(), challenge_page(), challenge_page(), challenge_page(), results_page(list(range(1, 31))))
    world.send("/start")
    world.send(SEARCH)
    world.telegram.sent.clear()
    world.run_due()
    assert world.user().state == PENDING_BASELINE and world.telegram.sent == []
    for delay in (60, 300, 900):
        assert world.tick(delay - 1) == 0
        assert world.tick(2) == 1
    assert world.telegram.texts() == [texts.BASELINE_STILL_TRYING]
    world.tick(901)
    assert world.telegram.texts() == [texts.BASELINE_STILL_TRYING, texts.baseline_summary(30)]
    assert world.listings_sent() == [] and world.user().state == ACTIVE


def test_baseline_page_two_failure_stores_nothing(world):
    world.page(1, results_page([1, 2], has_next=True))
    world.page(2, TimeoutError("chromedriver read timeout"))
    world.send("/start")
    world.send(SEARCH)
    world.run_due()
    assert world.user().state == PENDING_BASELINE and world.user().seen == {}


# Regular checks and delivery

def test_unchanged_results_send_nothing(world):
    subscribed(world, 3, 2, 1)
    world.page(1, results_page([3, 2, 1]))
    world.tick()
    world.tick()
    assert world.telegram.sent == []


def test_reloading_the_real_page_with_fresh_tracking_ids_sends_nothing(world):
    world.page(1, lambda url: real_page("user-search-p1"))
    world.subscribe()
    for _ in range(3):
        world.tick()
    assert world.telegram.sent == [] and len(world.user().seen) == 26


def test_new_listing_is_sent_as_a_clean_link_with_the_disable_button(world):
    subscribed(world, 2, 1)
    world.page(1, results_page([3, 2, 1]))
    world.tick()
    assert world.listings_sent() == ids(3)
    assert world.telegram.sent[-1].reply_markup == texts.disable_button()
    assert world.telegram.sent[-1].disable_web_page_preview is False


def test_listings_that_drop_out_and_return_are_not_resent(world):
    subscribed(world, 2, 1)
    world.page(1, results_page([2]), results_page([2, 1]))
    world.tick()
    world.tick()
    assert world.telegram.sent == []


def test_suggested_cards_are_never_notified(world):
    subscribed(world, 1)
    world.page(1, results_page([1], suggested=[90, 91]))
    world.tick()
    assert world.telegram.sent == []


def test_check_follows_pages_only_while_every_card_is_new(world):
    subscribed(world, 3, 2, 1)
    world.page(1, results_page([10, 9, 8, 7], has_next=True))
    world.page(2, results_page([6, 5, 4, 3], has_next=True))
    world.page(3, AssertionError("page 3 must not be fetched"))
    world.browser.fetched.clear()
    world.tick()
    assert world.browser.fetched == [page_url(WATCHED, 1), page_url(WATCHED, 2)]
    assert world.listings_sent() == ids(4, 5, 6, 7, 8, 9, 10)


def test_listings_shifting_up_from_page_two_after_a_full_baseline_are_not_sent(world):
    world.page(1, results_page(list(range(1, 31)), has_next=True))
    world.page(2, results_page(list(range(31, 61)), has_next=False))
    world.subscribe()
    world.page(1, results_page(list(range(2, 32)), has_next=True))
    world.tick()
    assert world.telegram.sent == []


def test_flood_guard_sends_ten_newest_then_one_digest(world):
    subscribed(world, 1)
    world.page(1, results_page(list(range(26, 0, -1))))
    world.tick()
    texts_sent = world.telegram.texts()
    assert world.listings_sent() == ids(*range(17, 27))
    assert texts_sent[-1] == texts.digest(15, WATCHED)
    assert len(texts_sent) == 11
    assert [m.reply_markup for m in world.telegram.sent].count(texts.disable_button()) == 1
    assert world.telegram.sent[-1].reply_markup == texts.disable_button()
    assert len(world.user().seen) == 26


def test_flood_guard_without_digest_at_exactly_the_cap(world):
    subscribed(world, 1)
    world.page(1, results_page(list(range(11, 0, -1))))
    world.tick()
    assert len(world.telegram.sent) == 10 and world.listings_sent() == ids(*range(2, 12))


def test_failed_send_is_not_retried_later(world):
    subscribed(world, 1)
    world.page(1, results_page([2, 1]))
    world.telegram.fail_next = 3
    world.tick()
    world.tick()
    assert world.telegram.sent == [] and "2" in world.user().seen


def test_seen_listings_are_pruned_after_the_retention_period(world):
    subscribed(world, 1)
    world.user().seen["old"] = SeenListing("o", 0.0, world.clock.time() - 31 * 86400)
    world.page(1, results_page([1]))
    world.tick()
    assert set(world.user().seen) == {"1"}


# Changes while a check is running

def test_disabling_mid_check_sends_nothing_and_keeps_seen(world):
    subscribed(world, 1)

    def disable_then_load(url):
        world.press(texts.DISABLE_CALLBACK)
        return results_page([3, 2, 1])

    world.page(1, disable_then_load)
    world.tick()
    assert world.listings_sent() == [] and set(world.user().seen) == {"1"}


def test_changing_url_mid_check_discards_the_old_results(world):
    subscribed(world, 1)
    other = "https://www.zonaprop.com.ar/departamentos-alquiler-belgrano.html"
    world.page(1, results_page([1, 2, 3], total=3), url=normalize_search_url(other))

    def change_url_then_load(url):
        world.send(other)
        return results_page([5, 4, 1])

    world.page(1, change_url_then_load)
    world.telegram.sent.clear()
    world.tick()
    assert world.listings_sent() == []
    world.run_due()
    assert world.telegram.texts()[-1] == texts.baseline_summary(3)
    assert set(world.user().seen) == {"1", "2", "3"}


def test_disabling_during_delivery_stops_the_remaining_messages(world):
    subscribed(world, 1)
    world.page(1, results_page([6, 5, 4, 3, 2, 1]))
    send = world.telegram.send_message

    def send_then_disable(*args, **kwargs):
        result = send(*args, **kwargs)
        world.bot.disable(CHAT)
        return result

    world.telegram.send_message = send_then_disable
    world.tick()
    assert len(world.listings_sent()) == 1


def test_overlapping_runs_for_one_chat_never_send_a_listing_twice(world):
    subscribed(world, 1)
    both_loaded = threading.Barrier(2, timeout=2)

    def after_both_loaded(url):
        both_loaded.wait()
        return results_page([3, 2, 1])

    world.page(1, after_both_loaded)
    generation = world.user().generation
    threads = [threading.Thread(target=world.service.run, args=(CHAT, generation)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert sorted(world.listings_sent()) == sorted(ids(2, 3))


def test_stale_generation_job_is_skipped(world):
    subscribed(world, 1)
    world.page(1, results_page([2, 1]))
    outcome = world.service.run(CHAT, world.user().generation - 1)
    assert outcome.status == "skipped" and not outcome.reschedule
    assert world.listings_sent() == []


# Disable and re-enable

def test_reenabling_rebaselines_silently_with_one_summary(world):
    subscribed(world, 2, 1)
    world.send(texts.MENU_TOGGLE)
    world.page(1, results_page([9, 8, 7, 2, 1]))
    assert world.tick() == 0
    world.send(texts.MENU_TOGGLE)
    world.telegram.sent.clear()
    world.run_due()
    assert world.telegram.texts() == [texts.baseline_summary(5)]
    world.tick()
    assert world.listings_sent() == []


# Forced checks

def test_forced_check_delivers_new_listings_without_extra_reply(world):
    subscribed(world, 1)
    world.page(1, results_page([2, 1]))
    world.send(texts.MENU_FORCE)
    world.run_due()
    assert world.telegram.texts() == [texts.FORCE_ACK, LISTING.format(2)]


def test_forced_check_with_nothing_new_says_so(world):
    subscribed(world, 2, 1, total=2)
    world.page(1, results_page([2, 1], total=2))
    world.send(texts.MENU_FORCE)
    world.run_due()
    assert world.telegram.texts() == [texts.FORCE_ACK, texts.forced_nothing_new(2)]


def test_forced_check_before_baseline_runs_the_baseline(world):
    world.page(1, TimeoutError("down"), results_page([1, 2]))
    world.send("/start")
    world.send(SEARCH)
    world.run_due()
    world.telegram.sent.clear()
    world.send(texts.MENU_FORCE)
    world.run_due()
    assert world.telegram.texts() == [texts.FORCE_ACK, texts.baseline_summary(2)]


def test_forced_check_while_disabled_only_reports(world):
    subscribed(world, 1)
    world.send(texts.MENU_TOGGLE)
    world.page(1, results_page([3, 2, 1], total=3))
    world.telegram.sent.clear()
    world.send(texts.MENU_FORCE)
    world.run_due()
    assert world.telegram.texts() == [texts.FORCE_ACK, texts.forced_while_disabled(3)]
    assert set(world.user().seen) == {"1"}


def test_forced_check_on_failure_says_so_and_keeps_the_regular_schedule(world):
    subscribed(world, 1)
    regular = [j for j in world.scheduler.pending() if not j.forced]
    world.page(1, challenge_page())
    world.send(texts.MENU_FORCE)
    world.run_due()
    assert world.telegram.texts()[-1] == texts.FETCH_FAILED
    assert [j for j in world.scheduler.pending() if not j.forced] == regular


# Failures and admin alerts

def test_check_failures_keep_seen_and_back_off(world):
    subscribed(world, 1)
    world.page(1, TimeoutError("hang"))
    world.tick()
    delays = []
    for _ in range(3):
        job = world.scheduler.pending()[0]
        delays.append(round(job.due - world.clock.monotonic()))
        world.tick(job.due - world.clock.monotonic() + 0.1)
    assert delays == [60, 300, 900]
    assert set(world.user().seen) == {"1"} and world.listings_sent() == []


def test_admin_is_alerted_once_after_repeated_failures_and_on_recovery(tmp_path):
    world = make_world(tmp_path, admin_chat_id="1000", admin_alert_after_failures=3, retry_delays=(10.0,))
    world.page(1, results_page([1]))
    world.subscribe()
    world.page(1, TimeoutError("read timeout"), TimeoutError("read timeout"), TimeoutError("read timeout"),
               TimeoutError("read timeout"), results_page([1]))
    world.tick()
    for _ in range(3):
        world.tick(11)
    admin = world.telegram.texts("1000")
    assert len(admin) == 1 and admin[0].startswith("ZonaBot: fallaron 3 búsquedas seguidas")
    world.tick(11)
    assert world.telegram.texts("1000")[-1] == texts.ADMIN_RECOVERED
    assert world.listings_sent() == []


def test_no_admin_messages_without_admin_chat(world):
    subscribed(world, 1)
    world.page(1, TimeoutError("down"))
    for _ in range(8):
        world.tick(901)
    assert {m.chat_id for m in world.telegram.sent} == {CHAT}


def test_failing_checks_tell_the_user_once_and_again_on_recovery(world):
    subscribed(world, 1)
    last_scan = world.user().last_scan
    world.page(1, *[TimeoutError("chrome not reachable")] * 8, results_page([2, 1]))
    world.tick()
    for _ in range(world.settings.check_failures_before_notice - 2):
        world.tick(901)
    assert world.telegram.sent == []
    world.tick(901)
    assert world.telegram.texts(CHAT) == [texts.checks_failing(last_scan)]
    for _ in range(4):
        world.tick(901)
    assert len(world.telegram.sent) == 1
    world.tick(901)
    assert world.telegram.texts(CHAT) == [texts.checks_failing(last_scan), texts.CHECKS_RECOVERED, LISTING.format(2)]
    assert world.user().consecutive_failures == 0 and not world.user().failure_notice_sent


def test_failure_notice_survives_a_restart(world):
    subscribed(world, 1)
    world.page(1, TimeoutError("down"))
    world.tick()
    for _ in range(world.settings.check_failures_before_notice):
        world.tick(901)
    assert world.reload_store().get(CHAT).failure_notice_sent


def test_forced_check_that_crosses_the_notice_threshold_sends_one_message(tmp_path):
    world = make_world(tmp_path, check_failures_before_notice=1)
    world.page(1, results_page([1]))
    world.subscribe()
    world.page(1, challenge_page())
    world.send(texts.MENU_FORCE)
    world.run_due()
    assert world.telegram.texts() == [texts.FORCE_ACK, texts.checks_failing(world.user().last_scan)]


def test_checks_failing_text_shows_the_last_successful_check():
    assert "14/11 22:59" in texts.checks_failing("2026-11-14 22:59:25")
    assert texts.checks_failing(None) and texts.checks_failing("garbage")


# Restart

def test_restart_resumes_without_summary(world, tmp_path):
    subscribed(world, 2, 1)
    restarted = make_world(tmp_path)
    restarted.store = world.reload_store()
    restarted.service.store = restarted.bot.store = restarted.store
    restarted.page(1, results_page([3, 2, 1]))
    restarted.scheduler.schedule(CHAT, restarted.user().generation)
    restarted.run_due()
    assert restarted.telegram.texts() == [LISTING.format(3)]


@pytest.mark.parametrize("telegram_failures", [1, 5])
def test_summary_send_failure_does_not_break_the_baseline(world, telegram_failures):
    world.telegram = FakeTelegram(fail_next=telegram_failures)
    world.service.telegram = world.bot.telegram = world.telegram
    world.page(1, results_page([1]))
    world.send("/start")
    world.send(SEARCH)
    world.run_due()
    assert world.user().state == ACTIVE


# Disabled chats and persistence order

def test_disabled_chat_is_not_fetched(world):
    subscribed(world, 1)
    world.send(texts.MENU_TOGGLE)
    world.browser.fetched.clear()
    outcome = world.service.run(CHAT, world.user().generation)
    assert outcome.status == "skipped" and world.browser.fetched == []


def test_new_listings_are_saved_as_seen_before_the_first_send(world):
    subscribed(world, 1)
    world.page(1, results_page([2, 1]))
    seen_on_disk = []
    send = world.telegram.send_message
    world.telegram.send_message = lambda *a, **k: seen_on_disk.append(
        sorted(json.loads(world.store.path.read_text())["users"][CHAT]["seen"])) or send(*a, **k)
    world.tick()
    assert seen_on_disk == [["1", "2"]]


def test_disable_and_reenable_during_a_check_rebaselines_instead_of_flooding(world):
    subscribed(world, 1, 2, 3)

    def off_and_on_then_load(url):
        world.send(texts.MENU_TOGGLE)
        world.send(texts.MENU_TOGGLE)
        return results_page([9, 8, 7, 3, 2, 1])

    world.page(1, off_and_on_then_load, results_page([9, 8, 7, 3, 2, 1]))
    world.tick()
    assert world.listings_sent() == []
    assert world.telegram.texts()[-1] == texts.baseline_summary(6)
