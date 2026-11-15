"""Single-worker job scheduler that runs one browser job at a time and one regular check chain per chat.

`schedule` replaces a chat's chain (older queued entries are dropped when popped).
Forced checks are one-off jobs that run before regular ones with the same due time.
"""
import heapq
import itertools
import logging
import random
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

FORCED, REGULAR = 0, 1


@dataclass(order=True)
class Job:
    due: float
    priority: int
    seq: int
    chat_id: str = field(compare=False)
    generation: int = field(compare=False)

    @property
    def forced(self):
        return self.priority == FORCED


class Scheduler:
    def __init__(self, run_job, interval=(240.0, 360.0), clock=time, rng=None, error_delay=60.0):
        self._run_job = run_job
        self._interval = interval
        self._clock = clock
        self._rng = rng or random.Random()
        self._error_delay = error_delay
        self._heap = []
        self._chains = {}
        self._seq = itertools.count()
        self._cond = threading.Condition()
        self._stopping = False
        self._thread = None
        self.running_job = None

    def schedule(self, chat_id, generation, delay=0.0):
        with self._cond:
            seq = next(self._seq)
            self._chains[str(chat_id)] = seq
            heapq.heappush(self._heap, Job(self._clock.monotonic() + delay, REGULAR, seq, str(chat_id), generation))
            self._cond.notify()

    def schedule_forced(self, chat_id, generation):
        with self._cond:
            heapq.heappush(self._heap, Job(self._clock.monotonic(), FORCED, next(self._seq), str(chat_id), generation))
            self._cond.notify()

    def cancel(self, chat_id):
        with self._cond:
            self._chains.pop(str(chat_id), None)

    def pending(self):
        with self._cond:
            return sorted(j for j in self._heap if self._is_live(j))

    def _is_live(self, job):
        return job.forced or self._chains.get(job.chat_id) == job.seq

    def _pop_due(self, now):
        while self._heap:
            job = self._heap[0]
            if not self._is_live(job):
                heapq.heappop(self._heap)
                continue
            if job.due <= now:
                return heapq.heappop(self._heap)
            return None
        return None

    def _next_due(self):
        live = [j.due for j in self._heap if self._is_live(j)]
        return min(live) if live else None

    def run_pending(self):
        """Run every job that is due now, in order. Returns the number of jobs run."""
        count = 0
        while True:
            with self._cond:
                job = self._pop_due(self._clock.monotonic())
            if job is None:
                return count
            self._execute(job)
            count += 1

    def _execute(self, job):
        self.running_job = job
        try:
            outcome = self._run_job(job.chat_id, job.generation, job.forced)
            reschedule, delay = outcome.reschedule, outcome.delay
        except Exception:
            logger.exception(f"Job for {job.chat_id} crashed")
            reschedule, delay = True, self._error_delay
        finally:
            self.running_job = None
        if job.forced or not reschedule:
            return
        with self._cond:
            if self._chains.get(job.chat_id) != job.seq:
                return
        self.schedule(job.chat_id, job.generation, delay if delay is not None else self._rng.uniform(*self._interval))

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            with self._cond:
                while True:
                    if self._stopping:
                        return
                    job = self._pop_due(self._clock.monotonic())
                    if job is not None:
                        break
                    next_due = self._next_due()
                    self._cond.wait(None if next_due is None else min(max(0.0, next_due - self._clock.monotonic()), 60.0))
            self._execute(job)

    def stop(self, timeout=None):
        """Stop after the running job (if any) finishes. Returns False if it is still running at `timeout`."""
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True
