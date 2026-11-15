"""Telegram update handling: menu, search URL submission, notifications toggle, forced checks."""
import logging

from . import texts
from .store import PENDING_BASELINE
from .urls import is_valid_search_url, normalize_search_url

logger = logging.getLogger(__name__)


class Bot:
    def __init__(self, store, telegram, scheduler):
        self.store = store
        self.telegram = telegram
        self.scheduler = scheduler

    def handle_update(self, update):
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
        elif "text" in (update.get("message") or {}):
            self._handle_message(update["message"])

    def _say(self, chat_id, text, menu=True, preview=True):
        self.telegram.send_message(
            chat_id, text, reply_markup=texts.main_menu_keyboard() if menu else None, disable_web_page_preview=not preview
        )

    def _handle_message(self, message):
        chat = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        if chat is None or not text:
            return
        chat_id = str(chat)
        logger.info(f"Received message from {chat_id}: {text}")

        with self.store.lock:
            user = self.store.get(chat_id)
            if user is None:
                if text == "/start":
                    self.store.add_user(chat_id)
                    self.store.save()
                    for line in texts.WELCOME:
                        self._say(chat_id, line)
                else:
                    self._say(chat_id, texts.START_FIRST, menu=False)
                return
            awaiting = user.awaiting_url
            if awaiting:
                user.awaiting_url = False
                self.store.save()

        if is_valid_search_url(text):
            self._set_search(chat_id, text)
        elif awaiting:
            self._say(chat_id, texts.INVALID_LINK)
        elif text == texts.MENU_CHANGE_LINK:
            with self.store.lock:
                user.awaiting_url = True
                self.store.save()
            self._say(chat_id, texts.ASK_FOR_LINK, menu=False)
        elif text == texts.MENU_TOGGLE:
            self._toggle(chat_id)
        elif text == texts.MENU_INFO:
            self._say(chat_id, texts.info(user.notifications, user.last_scan, user.original_url), preview=False)
        elif text == texts.MENU_FORCE:
            if not user.url:
                self._say(chat_id, texts.NEED_LINK_FIRST)
                return
            self._say(chat_id, texts.FORCE_ACK)
            self.scheduler.schedule_forced(chat_id, user.generation)
        elif text.startswith("/"):
            pass
        else:
            for line in texts.NOT_UNDERSTOOD:
                self._say(chat_id, line)

    def _set_search(self, chat_id, text):
        with self.store.lock:
            user = self.store.get(chat_id)
            user.url = normalize_search_url(text)
            user.original_url = text
            user.state = PENDING_BASELINE
            user.seen = {}
            user.new_generation()
            self.store.save()
            generation, enabled = user.generation, user.notifications
        self._say(chat_id, texts.link_set(text), preview=False)
        if enabled:
            self.scheduler.schedule(chat_id, generation)
        else:
            self.scheduler.cancel(chat_id)

    def _toggle(self, chat_id):
        with self.store.lock:
            user = self.store.get(chat_id)
            user.notifications = not user.notifications
            user.new_generation()
            if user.notifications:
                user.state = PENDING_BASELINE
            self.store.save()
            enabled, generation, has_url = user.notifications, user.generation, bool(user.url)
        self._say(chat_id, texts.notifications_state(enabled))
        if enabled and has_url:
            self.scheduler.schedule(chat_id, generation)
        else:
            self.scheduler.cancel(chat_id)

    def disable(self, chat_id):
        """Idempotent; affects only `chat_id`."""
        with self.store.lock:
            user = self.store.get(chat_id)
            if user is None:
                return False
            if user.notifications:
                user.notifications = False
                user.new_generation()
                self.store.save()
        self.scheduler.cancel(chat_id)
        return True

    def _handle_callback(self, query):
        query_id = query.get("id")
        data = query.get("data") or ""
        message = query.get("message") or {}
        chat = message.get("chat", {}).get("id")
        if not query_id or chat is None:
            return
        chat_id = str(chat)
        logger.info(f"Received callback query from {chat_id}: {data}")
        if data == texts.DISABLE_CALLBACK or data.startswith(texts.LEGACY_DISABLE_CALLBACK_PREFIX):
            self.disable(chat_id)
            self.telegram.answer_callback_query(query_id, texts.DISABLED_CALLBACK_ANSWER)
            self.telegram.edit_message_reply_markup(chat_id, message.get("message_id"), {})
        else:
            self.telegram.answer_callback_query(query_id)
