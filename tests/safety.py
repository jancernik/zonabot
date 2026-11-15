"""Network/subprocess guards used by the autouse fixture in conftest.py."""
import ipaddress
import socket

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}

_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NetworkBlocked(RuntimeError):
    pass


class SubprocessBlocked(RuntimeError):
    pass


def _is_local(host):
    if host in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_address(sock, address):
    if sock.family == getattr(socket, "AF_UNIX", None):
        return
    host = address[0] if isinstance(address, tuple) else address
    if not _is_local(host):
        raise NetworkBlocked(f"test tried to connect to {address!r}")


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _is_local(host if isinstance(host, str) else (host or b"").decode()):
        raise NetworkBlocked(f"test tried to resolve {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)


def _guarded_connect(self, address):
    _check_address(self, address)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    _check_address(self, address)
    return _real_connect_ex(self, address)


def _blocked_subprocess(*args, **kwargs):
    raise SubprocessBlocked(f"test tried to run a subprocess: {args[0] if args else kwargs.get('args')!r}")


DENIED_HOST_PARTS = ("zonaprop", "telegram")


def _denylisted(host):
    host = (host.decode() if isinstance(host, bytes) else host or "").lower()
    return any(part in host for part in DENIED_HOST_PARTS)


def _denylist_getaddrinfo(host, *args, **kwargs):
    """Browser tests may download chromedriver, but never reach Zonaprop or Telegram."""
    if _denylisted(host):
        raise NetworkBlocked(f"browser test tried to resolve {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)
