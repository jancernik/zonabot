"""One real page load from Zonaprop with the production browser setup. VM only:

    ZONABOT_LIVE=1 venv/bin/python -m pytest -m live tests/live

Never talks to Telegram. Detects selector drift and Cloudflare blocking.
"""
import os

import pytest

from zonabot.browser import SeleniumBaseBrowser
from zonabot.listings import PageKind, parse_results_page
from zonabot.urls import normalize_search_url

pytestmark = [pytest.mark.live, pytest.mark.timeout(300)]

DEFAULT_SEARCH = "https://www.zonaprop.com.ar/departamentos-alquiler-capital-federal.html"


def test_live_search_page_is_recognized():
    url = normalize_search_url(os.environ.get("ZONABOT_LIVE_URL", DEFAULT_SEARCH))
    result = SeleniumBaseBrowser().load(url)
    page = parse_results_page(result.html, result.url)
    assert page.kind in (PageKind.RESULTS, PageKind.EMPTY), f"unrecognized page at {result.url}"
    if page.kind is PageKind.RESULTS:
        assert page.total and all(l.id.isdigit() and "?" not in l.url for l in page.listings)
