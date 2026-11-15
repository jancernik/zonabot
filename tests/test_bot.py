"""Telegram handler behavior: menu, links, toggles and the inline disable button."""
import json

from world import CHAT, SEARCH, WATCHED
from zonabot import texts
from zonabot.store import ACTIVE, PENDING_BASELINE, User


def start(world, chat_id=CHAT):
    world.send("/start", chat_id)
    world.telegram.sent.clear()
    return world.user(chat_id)


def test_start_registers_user_and_sends_welcome(world):
    world.send("/start")
    assert world.user() == User()
    assert world.telegram.texts() == list(texts.WELCOME)
    assert all(m.reply_markup == texts.main_menu_keyboard() for m in world.telegram.sent)
    assert CHAT in json.loads(world.store.path.read_text())["users"]


def test_start_again_is_ignored(world):
    start(world)
    world.send("/start")
    assert world.telegram.sent == [] and world.user() == User()


def test_unknown_user_is_asked_to_start(world):
    world.send("hola")
    assert world.telegram.texts() == [texts.START_FIRST]
    assert world.telegram.sent[0].reply_markup is None
    assert world.user() is None


def test_sending_a_url_sets_the_search_and_queues_a_baseline(world):
    user = start(world)
    user.state, user.seen = ACTIVE, {"1": None}
    world.send(SEARCH)
    user = world.user()
    assert (user.url, user.original_url, user.state, user.seen, user.generation) == (WATCHED, SEARCH, PENDING_BASELINE, {}, 1)
    assert world.telegram.texts() == [texts.link_set(SEARCH)]
    assert world.telegram.sent[0].disable_web_page_preview is True
    assert [(j.chat_id, j.generation, j.forced) for j in world.scheduler.pending()] == [(CHAT, 1, False)]


def test_resending_the_url_quickly_keeps_one_chain(world):
    start(world)
    for _ in range(3):
        world.send(SEARCH)
    assert [(j.chat_id, j.generation) for j in world.scheduler.pending()] == [(CHAT, 3)]


def test_url_while_disabled_is_stored_but_not_checked(world):
    start(world)
    world.send(texts.MENU_TOGGLE)
    world.send(SEARCH)
    assert world.user().url == WATCHED and world.scheduler.pending() == []


def test_change_link_flow(world):
    start(world)
    world.send(texts.MENU_CHANGE_LINK)
    assert world.user().awaiting_url is True
    assert world.telegram.texts() == [texts.ASK_FOR_LINK]
    world.send("no es un link")
    assert world.user().awaiting_url is False
    assert world.telegram.texts()[-1] == texts.INVALID_LINK
    world.send(texts.MENU_CHANGE_LINK)
    world.send(SEARCH)
    assert world.user().url == WATCHED


def test_show_info(world):
    start(world)
    world.send(texts.MENU_INFO)
    world.send(SEARCH)
    world.user().last_scan = "2026-11-12 19:58:52"
    world.send(texts.MENU_INFO)
    assert world.telegram.texts()[0] == texts.info(True, None, None)
    assert world.telegram.texts()[-1] == f"- Notificaciones: Activadas\n- Última búsqueda: 2026-11-12 19:58:52\n- Link de búsqueda: {SEARCH}"


def test_menu_toggle_off_then_on(world):
    start(world)
    world.send(SEARCH)
    world.telegram.sent.clear()
    world.send(texts.MENU_TOGGLE)
    assert world.user().notifications is False and world.scheduler.pending() == []
    world.user().state = ACTIVE
    world.send(texts.MENU_TOGGLE)
    assert world.telegram.texts() == [texts.notifications_state(False), texts.notifications_state(True)]
    assert world.user().state == PENDING_BASELINE
    assert [j.generation for j in world.scheduler.pending()] == [world.user().generation]


def test_force_without_url_asks_for_one(world):
    start(world)
    world.send(texts.MENU_FORCE)
    assert world.telegram.texts() == [texts.NEED_LINK_FIRST]
    assert world.scheduler.pending() == []


def test_force_with_url_queues_a_forced_job(world):
    start(world)
    world.send(SEARCH)
    world.telegram.sent.clear()
    world.send(texts.MENU_FORCE)
    assert world.telegram.texts() == [texts.FORCE_ACK]
    assert [j.forced for j in world.scheduler.pending()] == [True, False]


def test_unknown_text_and_commands(world):
    start(world)
    world.send("/help")
    assert world.telegram.sent == []
    world.send("qué tal")
    assert world.telegram.texts() == list(texts.NOT_UNDERSTOOD)


def test_non_text_updates_are_ignored(world):
    world.bot.handle_update({"update_id": 1, "message": {"chat": {"id": 42}, "photo": []}})
    world.bot.handle_update({"update_id": 2, "edited_message": {"chat": {"id": 42}, "text": "hola"}})
    assert world.telegram.sent == []


# Inline disable button

def test_b04_disable_button_never_enables(world):
    start(world)
    world.send(SEARCH)
    world.press(texts.DISABLE_CALLBACK)
    world.press(texts.DISABLE_CALLBACK)
    assert world.user().notifications is False and world.scheduler.pending() == []


def test_b04_disable_button_answers_and_removes_the_keyboard(world):
    start(world)
    world.press(texts.DISABLE_CALLBACK, message_id=55)
    assert world.telegram.callback_answers == [("q1", texts.DISABLED_CALLBACK_ANSWER)]
    assert world.telegram.markup_edits == [(CHAT, 55, {})]


def test_b04_legacy_toggle_buttons_only_disable_their_own_chat(world):
    start(world, "42")
    start(world, "99")
    world.press("toggle_99", chat_id="42")
    assert world.user("42").notifications is False
    assert world.user("99").notifications is True


def test_b04_disable_bumps_the_generation_only_when_it_changes_something(world):
    start(world)
    world.press(texts.DISABLE_CALLBACK)
    generation = world.user().generation
    world.press(texts.DISABLE_CALLBACK)
    assert world.user().generation == generation == 1


def test_disable_button_from_unknown_chat_is_answered(world):
    world.press(texts.DISABLE_CALLBACK, chat_id="77")
    assert world.telegram.callback_answers == [("q1", texts.DISABLED_CALLBACK_ANSWER)]
    assert world.user("77") is None


def test_unknown_callback_data_is_answered_without_action(world):
    start(world)
    world.press("something-else")
    assert world.telegram.callback_answers == [("q1", None)]
    assert world.user().notifications is True
