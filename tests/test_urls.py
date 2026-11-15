import json

import pytest

from fakes import fixture_text
from zonabot.urls import is_valid_search_url, normalize_search_url, page_number, page_url

B = "https://www.zonaprop.com.ar/"
FILTERS = "publicado-hace-menos-de-1-dia-orden-publicado-descendente"
PROD_ORIGINAL = (
    B + "departamentos-alquiler-barrio-uno-barrio-dos"
    "-mas-de-3-ambientes-hasta-10-anos-menos-900000-pesos-orden-precio-descendente.html"
)


@pytest.mark.parametrize(
    "url,expected_slug",
    [
        ("departamentos-alquiler-palermo.html", f"departamentos-alquiler-{FILTERS}-palermo"),
        ("departamentos-venta-palermo.html", f"departamentos-venta-{FILTERS}-palermo"),
        ("departamentos-alquiler-palermo-orden-precio-descendente.html", f"departamentos-alquiler-{FILTERS}-palermo"),
        ("departamentos-alquiler-palermo-publicado-hace-menos-de-1-semana.html", f"departamentos-alquiler-{FILTERS}-palermo"),
        ("departamentos-alquiler-palermo-publicado-hace-menos-de-15-dias.html", f"departamentos-alquiler-{FILTERS}-palermo"),
        # B9 cases
        ("departamentos-alquiler.html", f"departamentos-alquiler-{FILTERS}"),
        ("departamentos-alquiler-temporal-palermo.html", f"departamentos-alquiler-temporal-{FILTERS}-palermo"),
        ("departamentos-alquiler-palermo-pagina-3.html", f"departamentos-alquiler-{FILTERS}-palermo"),
        ("departamentos-venta-palermo-publicado-hace-menos-de-3-dias.html", f"departamentos-venta-{FILTERS}-palermo"),
        ("departamentos-alquiler-palermo-orden-expensas-ascendente.html", f"departamentos-alquiler-{FILTERS}-palermo"),
        ("inmuebles-palermo.html", f"inmuebles-palermo-{FILTERS}"),
    ],
)
def test_normalize_forces_last_day_newest_first(url, expected_slug):
    assert normalize_search_url(B + url) == f"{B}{expected_slug}.html"


def test_b09_production_url_normalizes_to_the_url_the_bot_has_been_watching():
    watched = json.loads(fixture_text("zonaprop/user-search-p1.json"))["requested_url"]
    assert normalize_search_url(PROD_ORIGINAL) == watched


@pytest.mark.parametrize("url", [
    B + "departamentos-alquiler-palermo.html",
    B + "departamentos-alquiler.html",
    B + "departamentos-alquiler-temporal-palermo-pagina-2.html",
    PROD_ORIGINAL,
])
def test_b09_normalization_is_idempotent(url):
    once = normalize_search_url(url)
    assert normalize_search_url(once) == once


@pytest.mark.parametrize("url,expected", [
    ("http://www.zonaprop.com.ar/departamentos-alquiler-palermo.html", B + f"departamentos-alquiler-{FILTERS}-palermo.html"),
    ("zonaprop.com.ar/departamentos-alquiler-palermo.html", B + f"departamentos-alquiler-{FILTERS}-palermo.html"),
    ("  https://www.zonaprop.com.ar/departamentos-alquiler-palermo.html?foo=1 ", B + f"departamentos-alquiler-{FILTERS}-palermo.html?foo=1"),
])
def test_normalize_accepts_scheme_and_host_variants_and_keeps_query(url, expected):
    assert normalize_search_url(url) == expected


@pytest.mark.parametrize("url,valid", [
    ("https://www.zonaprop.com.ar/departamentos-alquiler-palermo.html", True),
    ("www.zonaprop.com.ar/departamentos-alquiler-palermo.html", True),
    ("zonaprop.com.ar/departamentos-alquiler-palermo.html", True),
    ("http://www.zonaprop.com.ar/departamentos-alquiler-palermo.html", True),
    ("https://zonaprop.com.ar/departamentos-alquiler-palermo.html", True),
    ("https://www.zonaprop.com.ar/emprendimientos-palermo.html", False),
    ("https://www.zonaprop.com.ar/propiedades/clasificado/alclapin-depto-60704169.html", False),
    ("https://www.zonaprop.com.ar/", False),
    ("https://www.argenprop.com/departamentos-alquiler-palermo", False),
    ("https://www.zonaprop.com.ar.evil.example/departamentos.html", False),
    ("hola", False),
])
def test_is_valid_search_url(url, valid):
    assert is_valid_search_url(url) is valid


def test_page_url_matches_the_scheme_seen_on_the_site():
    p1 = json.loads(fixture_text("zonaprop/caba-1dia-p1.json"))["requested_url"]
    p2 = json.loads(fixture_text("zonaprop/caba-1dia-p2.json"))["requested_url"]
    assert page_url(p1, 1) == p1
    assert page_url(p1, 2) == p2
    assert page_url(p2, 3) == p1.replace(".html", "-pagina-3.html")


@pytest.mark.parametrize("name,number", [("caba-1dia-p1", 1), ("caba-1dia-p2", 2), ("user-search-p2-past-end", 1)])
def test_page_number_of_the_final_url(name, number):
    assert page_number(json.loads(fixture_text(f"zonaprop/{name}.json"))["final_url"]) == number
