"""Save real Zonaprop result pages as test fixtures.

Uses the same SeleniumBase setup as the bot (uc mode on the real display, captcha click),
one fresh browser per page, never touches Telegram or user_data.json. Pages are scrubbed
before they are written (see scrub_fixtures.py); `--replace OLD=NEW` also rewrites URLs.

    venv/bin/python scripts/capture_fixtures.py --out /tmp/fixtures URL [URL ...] [--replace OLD=NEW ...]
"""
import argparse
import os
import random
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zonabot.browser import configure_display  # noqa: E402
from zonabot.listings import CARD_SELECTOR  # noqa: E402
from scrub_fixtures import parse_replacements, scrub_meta, scrub_page, write_meta  # noqa: E402

LEGACY_EXTRACTION_JS = """
const suggested = document.querySelector("div.thin-postings-container");
suggested && suggested.parentNode && suggested.parentNode.removeChild(suggested);
return Array.from(document.querySelectorAll(arguments[0]))
  .map(el => el.getAttribute("data-to-posting"))
  .filter(Boolean);
"""


def slug(url):
    name = url.split("zonaprop.com.ar/", 1)[-1].split("?", 1)[0].removesuffix(".html")
    return re.sub(r"[^a-z0-9-]+", "-", name.lower())[:80].strip("-") or "root"


def click_captcha(driver, timeout=30):
    result = {}

    def task():
        try:
            driver.uc_gui_click_captcha()
            result["status"] = "clicked_or_absent"
        except Exception as exc:
            result["status"] = f"error: {exc}"

    thread = threading.Thread(target=task, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    return "timeout" if thread.is_alive() else result.get("status", "unknown")


def capture(url, out_dir, index, replacements=()):
    from seleniumbase import SB

    meta = {"index": index, "requested_url": url, "captured_at": datetime.now(timezone.utc).isoformat()}
    with SB(uc=True, xvfb=False) as driver:
        driver.uc_open_with_reconnect(url, 4)
        meta["captcha"] = click_captcha(driver)
        driver.sleep(1)
        html = driver.get_page_source()
        meta["final_url"] = driver.get_current_url()
        meta["title"] = driver.get_title()
        meta["canonical"] = driver.execute_script(
            "const l = document.querySelector('link[rel=canonical]'); return l ? l.href : null;"
        )
        meta["legacy_links"] = driver.execute_script(LEGACY_EXTRACTION_JS, CARD_SELECTOR)
    meta["legacy_count"] = len(meta["legacy_links"])
    meta = scrub_meta(meta, replacements)
    base = os.path.join(out_dir, f"{index:02d}-{slug(meta['requested_url'])}")
    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(scrub_page(html, replacements))
    write_meta(Path(base + ".json"), meta)
    return base, meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-loads", type=int, default=6)
    parser.add_argument("--pause-min", type=float, default=20)
    parser.add_argument("--pause-max", type=float, default=40)
    parser.add_argument("--replace", action="append", metavar="OLD=NEW")
    args = parser.parse_args(argv)
    try:
        replacements = parse_replacements(args.replace)
    except ValueError as exc:
        parser.error(str(exc))

    bad = [u for u in args.urls if not u.startswith("https://www.zonaprop.com.ar/")]
    if bad:
        parser.error(f"only https://www.zonaprop.com.ar/ URLs are allowed: {bad}")
    if len(args.urls) > args.max_loads:
        parser.error(f"{len(args.urls)} URLs exceeds --max-loads={args.max_loads}")

    os.makedirs(args.out, exist_ok=True)
    configure_display()
    for index, url in enumerate(args.urls, 1):
        if index > 1:
            time.sleep(random.uniform(args.pause_min, args.pause_max))
        try:
            base, meta = capture(url, args.out, index, replacements)
            print(f"[{index}] {meta['legacy_count']} cards, captcha={meta['captcha']}, final={meta['final_url']} -> {base}.html")
        except Exception as exc:
            print(f"[{index}] FAILED {url}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
