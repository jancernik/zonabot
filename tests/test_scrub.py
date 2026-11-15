import json

import pytest

from fakes import FIXTURES
from pages import card_html, empty_page
from scripts.scrub_fixtures import parse_replacements, scrub_meta, scrub_page
from zonabot.listings import PageKind, parse_results_page

PAGES = sorted((FIXTURES / "zonaprop").glob("*.html"))


def raw_results_page():
    cards = card_html(60704169).replace(
        "alclapin-departamento-60704169", "alclapin-2-ambientes-calle-falsa-123-60704169"
    ).replace("<h3>", '<img src="https://img/x.jpg" alt="Juan Pérez"><h3 title="Calle Falsa 123">')
    return (
        "<!DOCTYPE html><html><head><title>1.234 Departamentos en Palermo - Zonaprop</title>"
        '<meta name="description" content="Palermo"><script>var phone = "1155550000";</script></head>'
        f'<body><!-- comment --><h1>1.234 Departamentos</h1>{cards}<p style="color:red">Calle Falsa 123</p>'
        '<a data-qa="PAGING_NEXT" href="/departamentos-palermo-pagina-2.html" aria-label="Palermo">2</a></body></html>'
    )


def test_scrub_keeps_what_the_parser_reads_and_drops_the_rest():
    raw = raw_results_page()
    scrubbed = scrub_page(raw, parse_replacements(["palermo=barrio-uno"]))
    before, after = parse_results_page(raw), parse_results_page(scrubbed)
    assert [l.id for l in after.listings] == [l.id for l in before.listings] == ["60704169"]
    assert (after.kind, after.total, after.has_next) == (before.kind, before.total, before.has_next)
    for gone in ("Calle Falsa", "calle-falsa", "Juan", "1155550000", "<script", "<img", "<meta", "comment", "style=", "Palermo", "palermo"):
        assert gone not in scrubbed, gone
    assert "<title>1.234 resultados - Zonaprop</title>" in scrubbed
    assert 'href="/departamentos-barrio-uno-pagina-2.html"' in scrubbed
    assert after.listings[0].url.endswith("/alclapin-60704169.html")


def test_scrub_keeps_the_no_results_marker():
    scrubbed = scrub_page(empty_page())
    assert parse_results_page(scrubbed).kind is PageKind.EMPTY
    assert "no hay propiedades" in scrubbed


def test_scrub_meta_rewrites_urls_title_and_links():
    meta = {
        "requested_url": "https://www.zonaprop.com.ar/departamentos-palermo.html",
        "title": "26 Departamentos en Palermo - Zonaprop",
        "legacy_links": ["/propiedades/clasificado/alclapin-lindo-depto-palermo-123.html?n_search_id=a"],
    }
    assert scrub_meta(meta, [("palermo", "barrio-uno")]) == {
        "requested_url": "https://www.zonaprop.com.ar/departamentos-barrio-uno.html",
        "title": "26 resultados - Zonaprop",
        "legacy_links": ["/propiedades/clasificado/alclapin-123.html?n_search_id=a"],
    }


def test_parse_replacements_rejects_malformed_pairs():
    with pytest.raises(ValueError):
        parse_replacements(["palermo"])


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_committed_fixtures_are_scrubbed(page):
    html = page.read_text(encoding="utf-8")
    meta = json.loads(page.with_suffix(".json").read_text(encoding="utf-8"))
    assert scrub_page(html) == html, "run scripts/scrub_fixtures.py on tests/fixtures/zonaprop"
    assert scrub_meta(meta) == meta
