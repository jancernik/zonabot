# Zonaprop result pages

Real pages captured with `scripts/capture_fixtures.py` and scrubbed with `scripts/scrub_fixtures.py`.
Each `.json` has the requested and final URL and `legacy_links`, the listing links the original
bot extracted from the page.

| Fixture | Page |
|---|---|
| `user-search-p1` | multi-neighborhood search, 26 results, one page |
| `user-search-p2-past-end` | same search, page 2 (redirected to page 1) |
| `caba-1dia-p1`, `caba-1dia-p2` | CABA, 577 results, pages 1 and 2 |
| `caba-all-p1` | CABA without filters, 19.010 results |
| `palermo-1dia-cheap-1result` | 1 result |
| `coghlan-1dia-cheap-0results` | no results |

Markup:
- A listing is `div.postingCardLayout-module__posting-card-layout` with `data-id` (the listing id,
  also the `-(\d+)\.html` part of `data-to-posting`) and `data-to-posting` (link plus a
  tracking query that changes on every page load).
- Cards inside `div.thin-postings-container` are suggestions, not results.
- 30 listings per page. `a[data-qa="PAGING_NEXT"]` exists only when there is a next page.
- Page N adds `-pagina-N` before `.html`; a page past the end redirects to page 1.
- The total count is the leading number of `<title>`, with `.` as thousands separator.
- A page with no results has `h4.postingsNoResults-module__title` and only suggestion cards.
