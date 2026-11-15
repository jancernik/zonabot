"""Real headless Chrome through SeleniumBase on the captured pages, served from localhost.

Run with `-m browser`. The server sends `Content-Security-Policy: default-src 'none'`, so Chrome
loads none of the pages' external scripts, styles or trackers.
"""
import functools
import http.server
import json
import threading

import pytest

from fakes import FIXTURES, fixture_text
from zonabot.browser import SeleniumBaseBrowser
from zonabot.listings import PageKind, listing_id, parse_results_page

pytestmark = [pytest.mark.browser, pytest.mark.timeout(180)]

PAGES = ["user-search-p1", "caba-1dia-p2", "palermo-1dia-cheap-1result", "coghlan-1dia-cheap-0results"]


class IsolatedHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy", "default-src 'none'")
        super().end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(IsolatedHandler, directory=str(FIXTURES / "zonaprop"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    return SeleniumBaseBrowser(headless=True)


@pytest.mark.parametrize("name", PAGES)
def test_chrome_rendered_page_parses_like_the_legacy_extraction(server, browser, name):
    result = browser.load(f"{server}/{name}.html")
    page = parse_results_page(result.html, result.url)
    expected = [listing_id(h) for h in json.loads(fixture_text(f"zonaprop/{name}.json"))["legacy_links"]]
    assert [l.id for l in page.listings] == expected
    assert page.kind is (PageKind.RESULTS if expected else PageKind.EMPTY)
