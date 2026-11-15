import json
from functools import lru_cache

import pytest

from fakes import fixture_text
from pages import challenge_page, empty_page, results_page
from zonabot.listings import PageKind, canonical_listing_url, listing_id, parse_results_page


@lru_cache(maxsize=None)
def parsed(name):
    meta = json.loads(fixture_text(f"zonaprop/{name}.json"))
    return parse_results_page(fixture_text(f"zonaprop/{name}.html"), meta["final_url"]), meta


@pytest.mark.parametrize(
    "name,kind,count,total,has_next,page",
    [
        ("user-search-p1", PageKind.RESULTS, 26, 26, False, 1),
        ("user-search-p2-past-end", PageKind.RESULTS, 26, 26, False, 1),
        ("caba-1dia-p1", PageKind.RESULTS, 30, 577, True, 1),
        ("caba-1dia-p2", PageKind.RESULTS, 30, 577, True, 2),
        ("caba-all-p1", PageKind.RESULTS, 30, 19010, True, 1),
        ("palermo-1dia-cheap-1result", PageKind.RESULTS, 1, 1, False, 1),
        ("coghlan-1dia-cheap-0results", PageKind.EMPTY, 0, None, False, 1),
    ],
)
def test_parses_captured_pages(name, kind, count, total, has_next, page):
    result, _ = parsed(name)
    assert (result.kind, len(result.listings), result.total, result.has_next, result.page) == (kind, count, total, has_next, page)


@pytest.mark.parametrize("name", ["user-search-p1", "caba-1dia-p1", "caba-1dia-p2", "caba-all-p1", "palermo-1dia-cheap-1result", "coghlan-1dia-cheap-0results"])
def test_matches_the_legacy_extraction_and_drops_suggestions(name):
    result, meta = parsed(name)
    assert [l.id for l in result.listings] == [listing_id(h) for h in meta["legacy_links"]]


@pytest.mark.parametrize("name", ["user-search-p1", "caba-1dia-p1"])
def test_b01_listing_urls_are_canonical_without_tracking(name):
    result, meta = parsed(name)
    assert [l.url for l in result.listings] == [canonical_listing_url(h) for h in meta["legacy_links"]]
    assert all("?" not in l.url and l.url.startswith("https://www.zonaprop.com.ar/propiedades/") for l in result.listings)


def test_b06_challenge_page_is_not_mistaken_for_empty_results():
    assert parse_results_page(challenge_page()).kind is PageKind.UNRECOGNIZED
    assert parse_results_page("").kind is PageKind.UNRECOGNIZED


def test_synthetic_pages_parse_like_real_ones():
    page = parse_results_page(results_page([3, 2, 1], suggested=[9], total=40, has_next=True))
    assert [l.id for l in page.listings] == ["3", "2", "1"]
    assert (page.kind, page.total, page.has_next) == (PageKind.RESULTS, 40, True)
    assert parse_results_page(empty_page()).kind is PageKind.EMPTY


def test_duplicate_cards_collapse_to_one_listing():
    html = results_page([1, 2, 1])
    assert html.count('data-id="1"') == 2
    assert [l.id for l in parse_results_page(html).listings] == ["1", "2"]


def test_listing_id_and_canonical_url():
    href = "/propiedades/clasificado/alclapin-depto-60704169.html?n_src=Listado&n_search_id=abc"
    assert listing_id(href) == "60704169"
    assert canonical_listing_url(href) == "https://www.zonaprop.com.ar/propiedades/clasificado/alclapin-depto-60704169.html"
    assert listing_id("/sin-id") is None
