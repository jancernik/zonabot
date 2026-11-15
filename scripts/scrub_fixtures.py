"""Strip captured Zonaprop pages down to what the parser and tests read.

Drops scripts, styles, images and every attribute the parser does not use, replaces all text
with "x" (the result count in <title> and the "no results" heading stay) and shortens listing
links to their id. `--replace OLD=NEW` also swaps text in URLs, for searches that should not be
committed as typed. Scrubbing twice gives the same result.

    venv/bin/python scripts/scrub_fixtures.py tests/fixtures/zonaprop --replace palermo=barrio-uno
"""
import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zonabot.listings import NO_RESULTS_SELECTOR  # noqa: E402

DROP_TAGS = ("script", "style", "noscript", "iframe", "link", "meta", "img", "picture", "source", "svg", "video")
KEEP_ATTRS = {"class", "data-qa", "data-id", "data-posting-type", "data-to-posting"}
LISTING_PATH = re.compile(r"(/propiedades/[a-z]+/[a-z]+)-[a-z0-9-]*?-?(\d+)\.html")
LEADING_COUNT = re.compile(r"\s*\d[\d.]*")


def parse_replacements(pairs):
    replacements = []
    for pair in pairs or ():
        old, sep, new = pair.partition("=")
        if not sep or not old:
            raise ValueError(f"expected OLD=NEW, got {pair!r}")
        replacements.append((old, new))
    return replacements


def scrub_text(text, replacements=()):
    text = LISTING_PATH.sub(r"\1-\2.html", text)
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def scrub_title(title):
    count = LEADING_COUNT.match(title or "")
    return f"{count.group(0).strip()} resultados - Zonaprop" if count else "Zonaprop"


def scrub_page(html, replacements=()):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    soup.smooth()
    kept ={id(tag) for tag in soup.select(NO_RESULTS_SELECTOR)}
    for node in soup.find_all(string=True):
        if isinstance(node, Comment):
            node.extract()
        elif type(node) is NavigableString and node.strip():
            if node.parent.name == "title":
                node.replace_with(scrub_title(node))
            elif not any(id(parent) in kept for parent in node.parents):
                node.replace_with("x")
    for tag in soup.find_all(True):
        paging = str(tag.get("data-qa", "")).startswith("PAGING")
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in KEEP_ATTRS or (paging and k == "href")}
    return scrub_text(str(soup), replacements)


def scrub_meta(meta, replacements=()):
    meta = dict(meta)
    for key in ("requested_url", "final_url", "canonical"):
        if meta.get(key):
            meta[key] = scrub_text(meta[key], replacements)
    meta["title"] = scrub_title(meta.get("title"))
    meta["legacy_links"] = [scrub_text(link, replacements) for link in meta.get("legacy_links", [])]
    return meta


def write_meta(path, meta):
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--replace", action="append", metavar="OLD=NEW")
    args = parser.parse_args(argv)
    try:
        replacements = parse_replacements(args.replace)
    except ValueError as exc:
        parser.error(str(exc))
    for page in sorted(args.directory.glob("*.html")):
        page.write_text(scrub_page(page.read_text(encoding="utf-8"), replacements), encoding="utf-8")
        meta = page.with_suffix(".json")
        if meta.exists():
            write_meta(meta, scrub_meta(json.loads(meta.read_text(encoding="utf-8")), replacements))
        print(f"scrubbed {page.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
