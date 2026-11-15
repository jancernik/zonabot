"""Synthetic Zonaprop pages shaped like the captured fixtures, plus fixture loaders."""
import re
import uuid

from fakes import fixture_text

CARD_CLASS = "postingCardLayout-module__posting-card-layout"


def card_html(listing_id, pos=1, search_id=None, tracking=True):
    href = f"/propiedades/clasificado/alclapin-departamento-{listing_id}.html"
    if tracking:
        href += f"?n_src=Listado&amp;n_pg=1&amp;n_pos={pos}&amp;n_search_id={search_id or uuid.uuid4()}"
    return (
        f'<div class="{CARD_CLASS}" data-qa="posting PROPERTY" data-id="{listing_id}" '
        f'data-posting-type="PROPERTY" data-to-posting="{href}"><h3>Depto {listing_id}</h3></div>'
    )


def results_page(ids, suggested=(), tracking=True, total=None, has_next=False):
    sid = uuid.uuid4()
    total = len(ids) if total is None else total
    cards = "".join(card_html(i, pos, sid, tracking) for pos, i in enumerate(ids, 1))
    thin = "".join(card_html(i, pos, sid, tracking) for pos, i in enumerate(suggested, 1))
    paging = '<a data-qa="PAGING_NEXT" class="paging-module__page-arrow" href=""></a>' if has_next else ""
    return (
        f"<html><head><title>{total} Departamentos en alquiler - Zonaprop</title></head><body>"
        f"<h1>{total} Departamentos en alquiler</h1><div class=\"postingsList-module__postings-container\">{cards}</div>"
        f'<div class="thin-postings-container">{thin}</div>'
        f'<div class="paging-module__container-paging">{paging}</div></body></html>'
    )


def empty_page(suggested=(101, 102)):
    thin = "".join(card_html(i) for i in suggested)
    return (
        "<html><head><title> Departamentos en alquiler - Zonaprop</title></head><body>"
        '<div class="postingsList-module__placeholder-postings-no-results">'
        '<h4 class="postingsNoResults-module__title">En este momento no hay propiedades como la que buscás</h4></div>'
        f'<div class="thin-postings-container">{thin}</div></body></html>'
    )


def challenge_page():
    return (
        "<html><head><title>Just a moment...</title></head><body>"
        "<h2>Verifying you are human. This may take a few seconds.</h2></body></html>"
    )


def real_page(name):
    """A captured fixture with a fresh n_search_id, as every real page load has."""
    return re.sub(r"n_search_id=[0-9a-f-]+", f"n_search_id={uuid.uuid4()}", fixture_text(f"zonaprop/{name}.html"))
