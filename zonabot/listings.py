"""Parsing of Zonaprop result pages (see tests/fixtures/zonaprop/README.md for the markup)."""
import enum
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .urls import SITE, page_number

CARD_SELECTOR = "div.postingCardLayout-module__posting-card-layout"
SUGGESTIONS_CLASS = "thin-postings-container"
NO_RESULTS_SELECTOR = "h4.postingsNoResults-module__title"
NEXT_PAGE_SELECTOR = 'a[data-qa="PAGING_NEXT"]'

_ID_IN_URL = re.compile(r"-(\d+)\.html")
_LEADING_COUNT = re.compile(r"^\s*(\d[\d.]*)\s")


class PageKind(enum.Enum):
    RESULTS = "results"
    EMPTY = "empty"
    UNRECOGNIZED = "unrecognized"


@dataclass(frozen=True)
class Listing:
    id: str
    url: str


@dataclass(frozen=True)
class ResultsPage:
    kind: PageKind
    listings: tuple
    total: int | None
    has_next: bool
    page: int


def listing_id(url):
    match = _ID_IN_URL.search(url)
    return match.group(1) if match else None


def canonical_listing_url(url):
    """Listing link without the per-page-load tracking query (n_search_id, n_pos, ...)."""
    url = url.split("?", 1)[0]
    return url if url.startswith("http") else f"{SITE}{url}"


def _listing(card):
    href = card.get("data-to-posting")
    if not href:
        return None
    lid = card.get("data-id") or listing_id(href)
    return Listing(lid, canonical_listing_url(href)) if lid else None


def parse_results_page(html, url=None):
    soup = BeautifulSoup(html, "html.parser")
    listings, ids = [], set()
    for card in soup.select(CARD_SELECTOR):
        if card.find_parent(class_=SUGGESTIONS_CLASS):
            continue
        listing = _listing(card)
        if listing and listing.id not in ids:
            ids.add(listing.id)
            listings.append(listing)

    if listings:
        kind = PageKind.RESULTS
    elif soup.select_one(NO_RESULTS_SELECTOR):
        kind = PageKind.EMPTY
    else:
        kind = PageKind.UNRECOGNIZED

    title = soup.title.get_text() if soup.title else ""
    count = _LEADING_COUNT.match(title)
    return ResultsPage(
        kind=kind,
        listings=tuple(listings),
        total=int(count.group(1).replace(".", "")) if count else None,
        has_next=soup.select_one(NEXT_PAGE_SELECTOR) is not None,
        page=page_number(url) if url else 1,
    )
