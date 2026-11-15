import threading
import time

from fakes import FakeClock
from zonabot.scheduler import Scheduler
from zonabot.service import Outcome


class Recorder:
    def __init__(self, outcome=None):
        self.calls = []
        self.outcome = outcome or Outcome("checked")

    def __call__(self, chat_id, generation, forced):
        self.calls.append((chat_id, generation, forced))
        return self.outcome(chat_id) if callable(self.outcome) else self.outcome


def make(outcome=None, interval=(240.0, 360.0)):
    clock = FakeClock()
    run = Recorder(outcome)
    return Scheduler(run, interval=interval, clock=clock), run, clock


def test_jobs_run_when_due_in_order():
    s, run, clock = make()
    s.schedule("a", 1, delay=10)
    s.schedule("b", 1, delay=5)
    assert s.run_pending() == 0
    clock.advance(10)
    assert s.run_pending() == 2
    assert [c[0] for c in run.calls] == ["b", "a"]


def test_rescheduling_a_chat_replaces_its_chain():
    s, run, clock = make()
    for generation in (1, 2, 3):
        s.schedule("a", generation)
    assert s.run_pending() == 1
    assert run.calls == [("a", 3, False)]
    assert len(s.pending()) == 1


def test_cancel_drops_the_chain():
    s, run, _ = make()
    s.schedule("a", 1)
    s.cancel("a")
    assert s.run_pending() == 0 and s.pending() == []


def test_regular_jobs_reschedule_within_the_interval():
    s, run, clock = make(interval=(240.0, 360.0))
    s.schedule("a", 1)
    s.run_pending()
    (job,) = s.pending()
    assert 240 <= job.due - clock.monotonic() <= 360
    assert job.generation == 1


def test_outcome_delay_and_no_reschedule_are_honored():
    s, run, clock = make(outcome=lambda chat: Outcome("failed", delay=60.0) if chat == "a" else Outcome("skipped", reschedule=False))
    s.schedule("a", 1)
    s.schedule("b", 1)
    s.run_pending()
    assert [(j.chat_id, j.due - clock.monotonic()) for j in s.pending()] == [("a", 60.0)]


def test_crashing_job_is_retried_after_the_error_delay():
    def boom(chat_id, generation, forced):
        raise RuntimeError("bug")

    clock = FakeClock()
    s = Scheduler(boom, clock=clock, error_delay=60.0)
    s.schedule("a", 1)
    s.run_pending()
    assert [j.due - clock.monotonic() for j in s.pending()] == [60.0]


def test_forced_jobs_run_first_and_do_not_touch_the_chain():
    s, run, clock = make()
    s.schedule("a", 1)
    s.schedule_forced("b", 7)
    s.run_pending()
    assert run.calls == [("b", 7, True), ("a", 1, False)]
    assert [j.chat_id for j in s.pending()] == ["a"]


def test_chain_replaced_during_a_run_is_not_continued():
    holder = {}

    def run(chat_id, generation, forced):
        holder["s"].schedule(chat_id, generation + 1, delay=1000)
        return Outcome("checked")

    clock = FakeClock()
    s = holder["s"] = Scheduler(run, clock=clock)
    s.schedule("a", 1)
    s.run_pending()
    assert [(j.generation, j.due - clock.monotonic()) for j in s.pending()] == [(2, 1000)]


def test_forced_check_runs_promptly_while_many_chats_are_subscribed():
    ran = threading.Event()

    def run(chat_id, generation, forced):
        if forced:
            ran.set()
        return Outcome("checked")

    s = Scheduler(run, interval=(240.0, 360.0))
    for i in range(20):
        s.schedule(str(i), 1)
    s.start()
    try:
        time.sleep(0.05)
        s.schedule_forced("42", 1)
        assert ran.wait(1.0)
    finally:
        assert s.stop(timeout=2)


def test_stop_waits_for_the_running_job_and_reports_a_hang():
    release, started = threading.Event(), threading.Event()

    def run(chat_id, generation, forced):
        started.set()
        release.wait(5)
        return Outcome("checked")

    s = Scheduler(run)
    s.schedule("a", 1)
    s.start()
    assert started.wait(1)
    assert s.stop(timeout=0.05) is False
    release.set()
    assert s.stop(timeout=2) is True


def test_worker_sleeps_until_a_job_is_added():
    ran = threading.Event()
    s = Scheduler(lambda *a: ran.set() or Outcome("checked", reschedule=False))
    s.start()
    try:
        time.sleep(0.05)
        assert not ran.is_set()
        s.schedule("a", 1)
        assert ran.wait(1)
    finally:
        s.stop(timeout=2)
