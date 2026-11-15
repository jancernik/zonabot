"""Zonaprop search URLs: validation, normalization and pagination."""
import re

SITE = "https://www.zonaprop.com.ar"
DAY_FILTER = "publicado-hace-menos-de-1-dia"
NEWEST_FIRST = "orden-publicado-descendente"

_HOST = re.compile(r"^(?:https?://)?(?:www\.)?zonaprop\.com\.ar/", re.IGNORECASE)
_OPERATION = re.compile(r"(?:^|-)(alquiler-temporal|temporal|alquiler|venta)(?=-|$)")
_DATE_FILTER = re.compile(r"-publicado-hace-(?:menos|mas)-de-\d+-[a-z]+")
_SORT = re.compile(r"-orden-[a-z]+-(?:ascendente|descendente)")
_PAGE = re.compile(r"-pagina-(\d+)")


def is_valid_search_url(text):
    text = text.strip()
    if not _HOST.match(text):
        return False
    path = _HOST.sub("", text, count=1)
    return bool(path) and "emprendimientos" not in path and not path.startswith("propiedades/")


def _split(url):
    path, _, query = _HOST.sub("", url.strip(), count=1).partition("?")
    return path.strip("/").removesuffix(".html"), query


def _join(slug, query):
    return f"{SITE}/{slug}.html" + (f"?{query}" if query else "")


def normalize_search_url(url):
    """Force "published in the last day, newest first" and drop any page number.

    The filters go right after the operation token, the form the bot has used in production;
    Zonaprop redirects it to its canonical slug order.
    """
    slug, query = _split(url)
    for pattern in (_DATE_FILTER, _SORT, _PAGE):
        slug = pattern.sub("", slug)
    filters = f"{DAY_FILTER}-{NEWEST_FIRST}"
    match = _OPERATION.search(slug)
    if match:
        slug = f"{slug[:match.end()]}-{filters}{slug[match.end():]}"
    else:
        slug = f"{slug}-{filters}"
    return _join(slug, query)


def page_url(url, number):
    slug, query = _split(url)
    slug = _PAGE.sub("", slug)
    if number > 1:
        slug = f"{slug}-pagina-{number}"
    return _join(slug, query)


def page_number(url):
    match = _PAGE.search(_split(url)[0])
    return int(match.group(1)) if match else 1
