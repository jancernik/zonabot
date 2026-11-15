"""Minimal Telegram Bot API client over requests (long polling)."""
import logging
import time

import requests

logger = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token, session=None, sleep=time.sleep, retries=3):
        self._token = token or ""
        self._session = session or requests.Session()
        self._sleep = sleep
        self._retries = retries

    def _url(self, method):
        return f"https://api.telegram.org/bot{self._token}/{method}"

    def _redact(self, value):
        text = str(value)
        return text.replace(self._token, "<token>") if self._token else text

    def send_message(self, chat_id, text, reply_markup=None, disable_web_page_preview=False):
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": disable_web_page_preview}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        for attempt in range(1, self._retries + 1):
            try:
                response = self._session.post(self._url("sendMessage"), json=payload, timeout=30)
                if response.status_code == 200:
                    return True
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited by Telegram, waiting {retry_after}s")
                    self._sleep(retry_after)
                    continue
                logger.error(f"Telegram sendMessage error {response.status_code}: {self._redact(response.text)}")
            except requests.exceptions.RequestException as exc:
                logger.error(f"Telegram sendMessage attempt {attempt}/{self._retries} failed: {self._redact(exc)}")
            if attempt < self._retries:
                self._sleep(2 ** (attempt - 1))
        logger.error(f"Failed to send Telegram message after {self._retries} attempts")
        return False

    def _call(self, method, payload):
        try:
            response = self._session.post(self._url(method), json=payload, timeout=30)
            if response.status_code != 200:
                logger.warning(f"Telegram {method} error {response.status_code}: {self._redact(response.text)}")
            return response.status_code == 200
        except requests.exceptions.RequestException as exc:
            logger.warning(f"Telegram {method} failed: {self._redact(exc)}")
            return False

    def answer_callback_query(self, callback_query_id, text=None):
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._call("answerCallbackQuery", payload)

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        return self._call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup or {}})

    def get_updates(self, offset=None, timeout=30):
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        try:
            response = self._session.get(self._url("getUpdates"), params=params, timeout=timeout + 5)
        except requests.exceptions.RequestException as exc:
            raise TelegramError(self._redact(exc)) from None
        if response.status_code != 200:
            raise TelegramError(f"getUpdates {response.status_code}: {self._redact(response.text)}")
        body = response.json()
        if not body.get("ok"):
            raise TelegramError(f"getUpdates not ok: {self._redact(body)}")
        return body.get("result", [])
