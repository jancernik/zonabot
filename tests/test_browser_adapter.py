"""SeleniumBaseBrowser against a fake `seleniumbase` module: same calls as production."""
import os
import sys
import threading
import types

import pytest

from zonabot import browser as browser_module
from zonabot.browser import DisplayUnavailable, FetchResult, SeleniumBaseBrowser, configure_display, wait_for_display


class FakeSBDriver:
    def __init__(self, log, captcha=None):
        self.log = log
        self._captcha = captcha
        self.window_handles = ["w1"]
        self.switch_to = types.SimpleNamespace(window=lambda h: log.append(("switch", h)))

    def uc_open_with_reconnect(self, url, reconnect_time):
        self.log.append(("open", url, reconnect_time, sys.stdout))

    def uc_gui_click_captcha(self):
        self.log.append(("captcha",))
        if self._captcha:
            self._captcha()

    def sleep(self, seconds):
        self.log.append(("sleep", seconds))

    def get_current_url(self):
        return "https://www.zonaprop.com.ar/final.html"

    def get_page_source(self):
        return "<html>ok</html>"

    def close(self):
        self.log.append(("close",))


class Desktop:
    """A fake GNOME session: Xwayland auth files in a runtime dir and X sockets in a socket dir."""

    def __init__(self, root, monkeypatch):
        self.runtime = root / "run-user"
        self.sockets = root / "X11-unix"
        self.home = root / "home"
        for path in (self.runtime, self.sockets, self.home):
            path.mkdir()
        monkeypatch.setattr(browser_module, "RUNTIME_DIR", self.runtime)
        monkeypatch.setattr(browser_module, "X11_SOCKET_DIR", self.sockets)
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("XAUTHORITY", raising=False)

    def start_session(self, suffix="ABC", display=0):
        auth = self.runtime / f".mutter-Xwaylandauth.{suffix}"
        auth.write_bytes(b"cookie")
        (self.sockets / f"X{display}").touch()
        return str(auth)

    def end_session(self):
        for path in [*self.runtime.iterdir(), *self.sockets.iterdir()]:
            path.unlink()


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    return Desktop(tmp_path, monkeypatch)


@pytest.fixture
def fake_sb(monkeypatch, desktop):
    desktop.start_session()
    state = {"log": [], "options": [], "captcha": None}

    class SB:
        def __init__(self, **options):
            state["options"].append(options)

        def __enter__(self):
            return FakeSBDriver(state["log"], state["captcha"])

        def __exit__(self, *exc):
            state["log"].append(("exit",))
            return False

    monkeypatch.setitem(sys.modules, "seleniumbase", types.SimpleNamespace(SB=SB))
    killed = []
    monkeypatch.setattr(browser_module.subprocess, "run", lambda args, **k: killed.append(args) or state["log"].append(("kill", args[-1])))
    state["killed"] = killed
    return state


def test_load_uses_the_production_seleniumbase_calls(fake_sb):
    result = SeleniumBaseBrowser().load("https://www.zonaprop.com.ar/x.html")
    assert result == FetchResult("https://www.zonaprop.com.ar/final.html", "<html>ok</html>")
    assert fake_sb["options"] == [{"uc": True, "xvfb": False}]
    names = [entry[0] for entry in fake_sb["log"]]
    assert names == ["open", "captcha", "sleep", "switch", "close", "exit", "kill", "kill"]
    assert fake_sb["log"][0][1:3] == ("https://www.zonaprop.com.ar/x.html", 4)
    assert fake_sb["killed"] == [["pkill", "-f", "chrome"], ["pkill", "-f", "chromium"]]


def test_headless_mode_for_local_integration_tests(fake_sb):
    SeleniumBaseBrowser(headless=True).load("http://127.0.0.1:1/x.html")
    assert fake_sb["options"] == [{"uc": True, "headless": True}]
    assert "captcha" not in [e[0] for e in fake_sb["log"]] and fake_sb["killed"] == []


def test_hanging_captcha_click_times_out(fake_sb):
    release = threading.Event()
    fake_sb["captcha"] = lambda: release.wait(5)
    try:
        assert SeleniumBaseBrowser(captcha_timeout=0.05).load("u").html == "<html>ok</html>"
    finally:
        release.set()


def test_captcha_errors_are_ignored(fake_sb):
    def fail():
        raise RuntimeError("Can't connect to display")

    fake_sb["captcha"] = fail
    assert SeleniumBaseBrowser().load("u").html == "<html>ok</html>"


def test_b07_concurrent_loads_leave_stdout_alone(fake_sb):
    original = sys.stdout
    threads = [threading.Thread(target=SeleniumBaseBrowser().load, args=(f"u{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert sys.stdout is original
    assert all(entry[3] is original for entry in fake_sb["log"] if entry[0] == "open")


def test_errors_still_close_the_browser(fake_sb, monkeypatch):
    def broken_open(self, url, t):
        raise TimeoutError("read timeout")

    monkeypatch.setattr(FakeSBDriver, "uc_open_with_reconnect", broken_open)
    with pytest.raises(TimeoutError):
        SeleniumBaseBrowser().load("u")
    assert [e[0] for e in fake_sb["log"]][-4:] == ["close", "exit", "kill", "kill"]


def test_configure_display_uses_the_xwayland_auth_file(desktop):
    auth = desktop.start_session()
    assert configure_display() is True
    assert os.environ["DISPLAY"] == ":0" and os.environ["XAUTHORITY"] == auth


def test_configure_display_keeps_an_explicit_xauthority(desktop, monkeypatch):
    desktop.start_session()
    explicit = desktop.home / "custom-auth"
    explicit.write_bytes(b"cookie")
    monkeypatch.setenv("XAUTHORITY", str(explicit))
    assert configure_display() is True and os.environ["XAUTHORITY"] == str(explicit)


def test_configure_display_falls_back_to_home_xauthority(desktop):
    (desktop.sockets / "X0").touch()
    (desktop.home / ".Xauthority").write_bytes(b"cookie")
    assert configure_display() is True and os.environ["XAUTHORITY"] == str(desktop.home / ".Xauthority")


def test_configure_display_is_not_ready_without_the_x_socket(desktop):
    desktop.start_session()
    (desktop.sockets / "X0").unlink()
    assert configure_display() is False


def test_b11_display_that_appears_after_startup_is_picked_up(fake_sb, desktop):
    """Power loss: the service starts a few seconds before Xwayland creates its auth file."""
    desktop.end_session()
    assert configure_display() is False
    with pytest.raises(DisplayUnavailable):
        SeleniumBaseBrowser().load("u")
    assert fake_sb["options"] == [], "Chrome must not be launched without a display"

    auth = desktop.start_session("BV60Y3")
    assert SeleniumBaseBrowser().load("u").html == "<html>ok</html>"
    assert os.environ["XAUTHORITY"] == auth


def test_b11_new_desktop_session_replaces_a_stale_auth_file(fake_sb, desktop):
    first = configure_display() and os.environ["XAUTHORITY"]
    desktop.end_session()
    second = desktop.start_session("NEW123")
    SeleniumBaseBrowser().load("u")
    assert first != second and os.environ["XAUTHORITY"] == second


def test_headless_loads_do_not_need_a_desktop(fake_sb, desktop):
    desktop.end_session()
    SeleniumBaseBrowser(headless=True).load("u")
    assert fake_sb["options"] == [{"uc": True, "headless": True}]


def test_b11_wait_for_display_polls_until_the_session_is_up(desktop):
    clock = {"now": 0.0}

    def sleep(seconds):
        clock["now"] += seconds
        if clock["now"] >= 6:
            desktop.start_session()

    assert wait_for_display(timeout=120, poll=2, sleep=sleep, monotonic=lambda: clock["now"]) is True
    assert clock["now"] == 6


def test_wait_for_display_gives_up_after_the_timeout(desktop):
    clock = {"now": 0.0}

    def sleep(seconds):
        clock["now"] += seconds

    assert wait_for_display(timeout=10, poll=2, sleep=sleep, monotonic=lambda: clock["now"]) is False
    assert clock["now"] == 10
