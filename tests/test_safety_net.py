import os
import socket
import subprocess
from pathlib import Path

import pytest
import requests

from safety import NetworkBlocked, SubprocessBlocked
from fakes import FakeBrowser, FakeClock, FakeTelegram


def test_external_dns_is_blocked():
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("www.zonaprop.com.ar", 443)


def test_external_http_is_blocked():
    with pytest.raises(NetworkBlocked):
        requests.get("https://api.telegram.org/", timeout=1)


def test_external_ip_connect_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s, pytest.raises(NetworkBlocked):
        s.connect(("1.1.1.1", 443))


def test_loopback_is_allowed():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=1):
            pass


def test_subprocesses_are_blocked():
    with pytest.raises(SubprocessBlocked):
        subprocess.run(["pkill", "-f", "chrome"])
    with pytest.raises(SubprocessBlocked):
        os.system("true")


def test_secrets_unset_and_cwd_isolated(tmp_path):
    assert "TELEGRAM_TOKEN" not in os.environ
    assert Path.cwd() == tmp_path


def test_fake_browser_scripts_sequences_and_errors():
    browser = FakeBrowser({"u": ["<a>", TimeoutError("hang"), "<b>"]})
    assert browser.fetch("u") == "<a>"
    with pytest.raises(TimeoutError):
        browser.fetch("u")
    assert browser.fetch("u") == "<b>"
    assert browser.fetch("u") == "<b>"
    assert browser.fetched == ["u"] * 4
    with pytest.raises(AssertionError):
        browser.fetch("other")


def test_fake_telegram_records_and_fails_on_demand():
    tg = FakeTelegram(fail_next=1)
    assert tg.send_message(1, "https://x") is False
    assert tg.send_message(1, "https://x") is True
    assert tg.send_message(2, "hola") is True
    assert tg.listing_texts(1) == ["https://x"]
    assert tg.texts() == ["https://x", "hola"]


def test_fake_clock_sleep_advances():
    clock = FakeClock(start=10)
    clock.sleep(5)
    assert clock.time() == 15
