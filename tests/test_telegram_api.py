import logging
import types

import pytest
import requests

from zonabot.telegram_api import TelegramClient, TelegramError

TOKEN = "123456:SECRET-token"


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def _next(self, method, url, kwargs):
        self.calls.append((method, url.rsplit("/", 1)[-1], kwargs))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def post(self, url, **kwargs):
        return self._next("post", url, kwargs)

    def get(self, url, **kwargs):
        return self._next("get", url, kwargs)


def response(status=200, body=None, headers=None, text=""):
    return types.SimpleNamespace(status_code=status, json=lambda: body or {"ok": True, "result": []}, headers=headers or {}, text=text)


def client(*responses):
    sleeps = []
    session = FakeSession(*responses)
    return TelegramClient(TOKEN, session=session, sleep=sleeps.append), session, sleeps


def test_send_message_payload():
    tg, session, _ = client(response())
    assert tg.send_message("42", "hola", reply_markup={"k": 1}, disable_web_page_preview=True) is True
    method, name, kwargs = session.calls[0]
    assert (method, name) == ("post", "sendMessage")
    assert kwargs["json"] == {"chat_id": "42", "text": "hola", "disable_web_page_preview": True, "reply_markup": {"k": 1}}


def test_send_message_waits_out_rate_limits():
    tg, session, sleeps = client(response(429, headers={"Retry-After": "7"}), response())
    assert tg.send_message("42", "x") is True
    assert sleeps == [7]


def test_send_message_gives_up_after_retries():
    tg, session, sleeps = client(response(500), response(500), response(500))
    assert tg.send_message("42", "x") is False
    assert len(session.calls) == 3 and sleeps == [1, 2]


def test_errors_never_log_the_token(caplog):
    error = requests.exceptions.ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
    tg, _, _ = client(error, error, error)
    with caplog.at_level(logging.ERROR):
        tg.send_message("42", "x")
    assert TOKEN not in caplog.text and "<token>" in caplog.text


def test_get_updates_params_and_result():
    tg, session, _ = client(response(body={"ok": True, "result": [{"update_id": 5}]}))
    assert tg.get_updates(offset=5, timeout=30) == [{"update_id": 5}]
    _, name, kwargs = session.calls[0]
    assert name == "getUpdates"
    assert kwargs["params"] == {"timeout": 30, "allowed_updates": ["message", "callback_query"], "offset": 5}
    assert kwargs["timeout"] == 35


@pytest.mark.parametrize("item", [response(502, text="Bad Gateway"), response(body={"ok": False}),
                                  requests.exceptions.ConnectionError(f"/bot{TOKEN}/getUpdates")])
def test_get_updates_failures_raise_without_the_token(item):
    tg, _, _ = client(item)
    with pytest.raises(TelegramError) as info:
        tg.get_updates()
    assert TOKEN not in str(info.value)


def test_callback_helpers():
    tg, session, _ = client(response(), response())
    tg.answer_callback_query("q1", "Listo")
    tg.edit_message_reply_markup("42", 7)
    assert [(c[1], c[2]["json"]) for c in session.calls] == [
        ("answerCallbackQuery", {"callback_query_id": "q1", "text": "Listo"}),
        ("editMessageReplyMarkup", {"chat_id": "42", "message_id": 7, "reply_markup": {}}),
    ]
