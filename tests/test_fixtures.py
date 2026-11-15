"""Pins the facts in tests/fixtures/zonaprop/README.md that the parser relies on."""
import json
import re

import pytest
from bs4 import BeautifulSoup

from fakes import FIXTURES

CARD = "div.postingCardLayout-module__posting-card-layout"
NO_RESULTS = "h4.postingsNoResults-module__title"
PAGES = sorted(p.stem for p in (FIXTURES / "zonaprop").glob("*.html"))


def load(name):
    html = (FIXTURES / "zonaprop" / f"{name}.html").read_text(encoding="utf-8")
    meta = json.loads((FIXTURES / "zonaprop" / f"{name}.json").read_text(encoding="utf-8"))
    return BeautifulSoup(html, "html.parser"), meta


def result_cards(soup):
    return [c for c in soup.select(CARD) if not c.find_parent("div", class_="thin-postings-container")]



def test_fixture_set_is_complete():
    assert PAGES == [
        "caba-1dia-p1", "caba-1dia-p2", "caba-all-p1", "coghlan-1dia-cheap-0results",
        "palermo-1dia-cheap-1result", "user-search-p1", "user-search-p2-past-end",
    ]


def test_zero_result_page_markers():
    soup, meta = load("coghlan-1dia-cheap-0results")
    assert soup.select_one(NO_RESULTS) is not None
    assert soup.select_one("h1") is None
    assert not re.match(r"\s*\d", soup.title.string)
    assert soup.select(CARD) and not result_cards(soup)
    assert meta["legacy_links"] == []


@pytest.mark.parametrize("name", [p for p in PAGES if p != "coghlan-1dia-cheap-0results"])
def test_results_pages_have_no_empty_marker(name):
    assert load(name)[0].select_one(NO_RESULTS) is None


@pytest.mark.parametrize("name", [p for p in PAGES if p != "coghlan-1dia-cheap-0results"])
def test_data_id_matches_href_id_and_legacy_extraction(name):
    soup, meta = load(name)
    cards = result_cards(soup)
    ids = [c["data-id"] for c in cards]
    assert ids == [re.search(r"-(\d+)\.html", c["data-to-posting"]).group(1) for c in cards]
    assert ids == [re.search(r"-(\d+)\.html", h).group(1) for h in meta["legacy_links"]]
    assert len(ids) == len(set(ids)) <= 30


@pytest.mark.parametrize("name", [p for p in PAGES if p != "coghlan-1dia-cheap-0results"])
def test_hrefs_carry_per_load_tracking_params(name):
    _, meta = load(name)
    assert all("n_search_id=" in h for h in meta["legacy_links"])


@pytest.mark.parametrize(
    "name,total,has_next",
    [
        ("user-search-p1", 26, False),
        ("user-search-p2-past-end", 26, False),
        ("caba-1dia-p1", 577, True),
        ("caba-1dia-p2", 577, True),
        ("caba-all-p1", 19010, True),
        ("palermo-1dia-cheap-1result", 1, False),
    ],
)
def test_total_count_and_next_marker(name, total, has_next):
    soup, _ = load(name)
    assert int(re.match(r"\s*([\d.]+)", soup.title.string).group(1).replace(".", "")) == total
    assert (soup.select_one('a[data-qa="PAGING_NEXT"]') is not None) is has_next


def test_page_past_end_redirects_to_page_one():
    _, p1 = load("user-search-p1")
    _, p2 = load("user-search-p2-past-end")
    assert p2["requested_url"].endswith("-pagina-2.html")
    assert p2["final_url"] == p1["final_url"]
    assert "-pagina-" not in p2["final_url"]


def test_pages_do_not_overlap():
    p1 = {c["data-id"] for c in result_cards(load("caba-1dia-p1")[0])}
    p2 = {c["data-id"] for c in result_cards(load("caba-1dia-p2")[0])}
    assert not p1 & p2
