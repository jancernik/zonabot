"""Page loading through SeleniumBase in undetected-chromedriver mode on the desktop display."""
import gc
import glob
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

RUNTIME_DIR = Path(f"/run/user/{os.getuid()}")
X11_SOCKET_DIR = Path("/tmp/.X11-unix")


@dataclass(frozen=True)
class FetchResult:
    url: str
    html: str


class DisplayUnavailable(RuntimeError):
    pass


def configure_display():
    """Point Chrome at the desktop session (GNOME autologin, Xwayland :0) and report whether it is up.

    After boot the service starts before Xwayland creates its auth file, and each desktop session
    gets a new one, so this runs before every load.
    """
    display = os.environ.setdefault("DISPLAY", ":0")
    current = os.environ.get("XAUTHORITY")
    if not (current and os.path.exists(current)):
        found = _find_xauthority()
        if found:
            os.environ["XAUTHORITY"] = found
        else:
            os.environ.pop("XAUTHORITY", None)
    return "XAUTHORITY" in os.environ and _x_socket_exists(display)


def wait_for_display(timeout=120, poll=2, sleep=time.sleep, monotonic=time.monotonic):
    deadline = monotonic() + timeout
    while not configure_display():
        if monotonic() >= deadline:
            return False
        sleep(poll)
    return True


def _find_xauthority():
    sessions = sorted(glob.glob(str(RUNTIME_DIR / ".mutter-Xwaylandauth.*")), key=_mtime, reverse=True)
    home_auth = os.path.expanduser("~/.Xauthority")
    for path in [*sessions, home_auth]:
        if os.path.exists(path):
            return path
    return None


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _x_socket_exists(display):
    """Only local displays (`:N`) have a socket to check."""
    if not display.startswith(":"):
        return True
    number = display[1:].split(".")[0]
    return (X11_SOCKET_DIR / f"X{number}").exists()


class SeleniumBaseBrowser:
    """One fresh browser per page load."""

    def __init__(self, headless=False, reconnect_time=4, captcha_timeout=30):
        self.headless = headless
        self.reconnect_time = reconnect_time
        self.captcha_timeout = captcha_timeout

    def load(self, url):
        from seleniumbase import SB

        if not self.headless and not configure_display():
            raise DisplayUnavailable(f"desktop display {os.environ.get('DISPLAY')} is not up yet (no Xwayland auth file or X socket)")
        options = {"uc": True, "headless": True} if self.headless else {"uc": True, "xvfb": False}
        try:
            with SB(**options) as driver:
                try:
                    driver.uc_open_with_reconnect(url, self.reconnect_time)
                    if not self.headless:
                        self._click_captcha(driver)
                    driver.sleep(1)
                    return FetchResult(driver.get_current_url(), driver.get_page_source())
                finally:
                    self._close_windows(driver)
        finally:
            self._kill_leftover_chrome()

    def _click_captcha(self, driver):
        def task():
            try:
                driver.uc_gui_click_captcha()
            except Exception as exc:
                logger.debug(f"CAPTCHA click unavailable: {exc}")

        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        thread.join(timeout=self.captcha_timeout)
        if thread.is_alive():
            logger.warning("CAPTCHA handling timed out, continuing anyway")

    def _close_windows(self, driver):
        try:
            for handle in driver.window_handles:
                driver.switch_to.window(handle)
                driver.close()
        except Exception:
            pass

    def _kill_leftover_chrome(self):
        """Kills every Chrome process of this user, including ones the bot did not start."""
        if not self.headless:
            for name in ("chrome", "chromium"):
                try:
                    subprocess.run(["pkill", "-f", name], capture_output=True, timeout=5)
                except Exception:
                    pass
        gc.collect()
