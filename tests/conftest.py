import os
import socket
import subprocess

import pytest

from safety import (
    _blocked_subprocess,
    _denylist_getaddrinfo,
    _guarded_connect,
    _guarded_connect_ex,
    _guarded_getaddrinfo,
)
from world import world  # noqa: F401  (registers the fixture)


@pytest.fixture(autouse=True)
def safety_net(request, monkeypatch, tmp_path):
    """Isolate every test from the network, real processes, secrets and the working directory.

    `live` tests keep network access. `browser` tests may start Chrome and download chromedriver,
    but cannot resolve Zonaprop or Telegram hosts.
    """
    is_live = request.node.get_closest_marker("live") is not None
    is_browser = request.node.get_closest_marker("browser") is not None

    if is_live and os.environ.get("ZONABOT_LIVE") != "1":
        pytest.skip("live test: set ZONABOT_LIVE=1 (VM only)")

    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    monkeypatch.chdir(tmp_path)

    if is_browser:
        monkeypatch.setattr(socket, "getaddrinfo", _denylist_getaddrinfo)
    elif not is_live:
        monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
        monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
        monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)

    if not (is_live or is_browser):
        for name in ("run", "call", "check_call", "check_output", "Popen"):
            monkeypatch.setattr(subprocess, name, _blocked_subprocess)
        monkeypatch.setattr(os, "system", _blocked_subprocess)
    yield
