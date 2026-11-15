"""Test doubles for the browser, Telegram and time. No real I/O."""
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from zonabot.browser import FetchResult

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(relative_path):
    return (FIXTURES / relative_path).read_text(encoding="utf-8")


class FakeBrowser:
    """Serves scripted responses per URL.

    A response is an HTML string, an exception instance (raised), or a callable
    taking the URL and returning either. A per-URL list is consumed in order and
    its last item repeats. `default` answers URLs with no script.
    """

    def __init__(self, responses=None, default=None):
        self._responses = {url: self._as_queue(r) for url, r in (responses or {}).items()}
        self.default = default
        self.fetched = []
        self._lock = threading.Lock()

    @staticmethod
    def _as_queue(response):
        return deque(response if isinstance(response, list) else [response])

    def script(self, url, *responses):
        with self._lock:
            self._responses[url] = deque(responses)

    def fetch(self, url):
        with self._lock:
            self.fetched.append(url)
            queue = self._responses.get(url)
            if queue:
                response = queue.popleft() if len(queue) > 1 else queue[0]
            else:
                response = self.default
        if callable(response):
            response = response(url)
        if isinstance(response, BaseException):
            raise response
        if response is None:
            raise AssertionError(f"FakeBrowser has no response for {url}")
        return response

    def load(self, url):
        """zonabot Browser protocol. Plain HTML responses keep the requested URL as the final URL."""
        response = self.fetch(url)
        return response if isinstance(response, FetchResult) else FetchResult(url, response)


@dataclass
class SentMessage:
    chat_id: str
    text: str
    reply_markup: dict | None = None
    disable_web_page_preview: bool = False


@dataclass
class FakeTelegram:
    """Records outgoing calls. `fail_next` makes the next N sends fail."""

    sent: list = field(default_factory=list)
    callback_answers: list = field(default_factory=list)
    markup_edits: list = field(default_factory=list)
    updates: deque = field(default_factory=deque)
    fail_next: int = 0

    def __post_init__(self):
        self._lock = threading.Lock()

    def send_message(self, chat_id, text, reply_markup=None, disable_web_page_preview=False):
        with self._lock:
            if self.fail_next:
                self.fail_next -= 1
                return False
            self.sent.append(SentMessage(str(chat_id), text, reply_markup, disable_web_page_preview))
            return True

    def answer_callback_query(self, callback_query_id, text=None):
        self.callback_answers.append((callback_query_id, text))
        return True

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        self.markup_edits.append((str(chat_id), message_id, reply_markup))
        return True

    def get_updates(self, offset=None, timeout=0):
        batch = list(self.updates)
        self.updates.clear()
        return [u for u in batch if offset is None or u["update_id"] >= offset]

    def texts(self, chat_id=None):
        return [m.text for m in self.sent if chat_id is None or m.chat_id == str(chat_id)]

    def listing_texts(self, chat_id=None):
        return [t for t in self.texts(chat_id) if t.startswith("https://")]


class FakeClock:
    """Manual clock. `sleep` advances time instead of blocking."""

    def __init__(self, start=1_000_000.0):
        self._now = float(start)
        self._lock = threading.Lock()

    def time(self):
        with self._lock:
            return self._now

    monotonic = time

    def advance(self, seconds):
        with self._lock:
            self._now += seconds

    def sleep(self, seconds):
        self.advance(max(0.0, seconds))


def message_update(update_id, chat_id, text):
    return {"update_id": update_id, "message": {"message_id": update_id, "chat": {"id": int(chat_id)}, "text": text}}


def callback_update(update_id, chat_id, data, message_id=1, query_id="q1"):
    return {
        "update_id": update_id,
        "callback_query": {"id": query_id, "data": data, "message": {"message_id": message_id, "chat": {"id": int(chat_id)}}},
    }
