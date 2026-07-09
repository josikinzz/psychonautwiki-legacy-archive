#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "public"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

CDX_URL = "https://web.archive.org/cdx"
SOURCE_PREFIX = "https://psychonautwiki.org"
START_TIMESTAMP = "20160101000000"
END_TIMESTAMP = "20171231235959"
MAIN_PAGE = "https://psychonautwiki.org/wiki/Main_Page"
MAIN_PAGE_TIMESTAMP = "20160503015738"
USER_AGENT = "josiekins-psychonautwiki-archive/1.0"
CANONICAL_FIRST_SEGMENTS = {
    "cannabis": "cannabis",
}
ARCHIVE_HEAD_INJECTION = (
    '<base href="/">'
    '<meta name="robots" content="noindex">'
    '<style>'
    ':root{--josiekins-archive-banner-height:48px;--josiekins-archive-banner-gap:12px;'
    '--josiekins-archive-page-offset:calc(var(--josiekins-archive-banner-height) + '
    'var(--josiekins-archive-banner-gap));}'
    'body.mediawiki{padding-top:var(--josiekins-archive-page-offset)!important;}'
    'body.skin-vector #mw-head{top:var(--josiekins-archive-page-offset)!important;}'
    'body.skin-vector #mw-panel{top:calc(160px + var(--josiekins-archive-page-offset))!important;}'
    '.josiekins-archive-banner{box-sizing:border-box;min-height:var(--josiekins-archive-banner-height);'
    'position:absolute;top:0;left:0;right:0;z-index:10000;display:flex;align-items:center;'
    'gap:.45rem;flex-wrap:wrap;background:#141216;color:#f4eee5;'
    'font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
    'padding:12px 18px;border-bottom:1px solid #3a343d;'
    'box-shadow:0 1px 0 rgba(255,255,255,.06);}'
    '.josiekins-archive-banner strong{font-weight:650;color:#fff8ef;}'
    '.josiekins-archive-banner span{display:inline;}'
    '.josiekins-archive-banner a{color:#92d7ff;text-decoration-thickness:1px;text-underline-offset:3px;}'
    '.josiekins-archive-banner a:hover,.josiekins-archive-banner a:focus{color:#c4ebff;}'
    '.josiekins-archive-banner a:focus{outline:2px solid #c4ebff;outline-offset:3px;}'
    '@media(max-width:700px){:root{--josiekins-archive-banner-height:96px;'
    '--josiekins-archive-banner-gap:8px;}'
    '.josiekins-archive-banner{align-content:center;padding:10px 12px;}}'
    '</style>'
)
ARCHIVE_HEAD_PATTERN = re.compile(
    r'<base href="/"><meta name="robots" content="noindex"><style>[^<]*'
    r'\.josiekins-archive-banner[^<]*</style>',
    re.S,
)
ARCHIVE_BANNER_PATTERN = re.compile(
    r'<div class="josiekins-archive-banner">.*?'
    r'<a href="(?P<source>[^"]+)">(?:Internet Archive(?: captures)?)</a>.*?</div>',
    re.S,
)


def fetch_bytes(url: str, retries: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def cdx_url(limit: int | None) -> str:
    params = {
        "url": "psychonautwiki.org/wiki/*",
        "from": START_TIMESTAMP[:4],
        "to": END_TIMESTAMP[:4],
        "output": "json",
        "fl": "timestamp,original,statuscode,mimetype,digest",
        "filter": ["statuscode:200", "mimetype:text/html"],
        "collapse": "urlkey",
    }
    query = urllib.parse.urlencode(params, doseq=True)
    if limit is not None:
        query += f"&limit={limit}"
    return f"{CDX_URL}?{query}"


def load_cdx(limit: int | None) -> list[dict[str, str]]:
    payload = fetch_bytes(cdx_url(limit))
    rows = json.loads(payload)
    if not rows:
        return []
    header = rows[0]
    captures = [dict(zip(header, row)) for row in rows[1:]]
    return [
        capture
        for capture in captures
        if START_TIMESTAMP <= capture["timestamp"] <= END_TIMESTAMP
        and is_article_url(capture["original"])
    ]


def is_article_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in {"psychonautwiki.org", "www.psychonautwiki.org"}:
        return False
    if not parsed.path.startswith("/wiki/"):
        return False
    title = parsed.path.removeprefix("/wiki/").strip("/")
    if not title or ":" in urllib.parse.unquote(title):
        return False
    return True


def local_path_for_url(url: str) -> str | None:
    if not is_article_url(url):
        return None
    parsed = urllib.parse.urlparse(url)
    title = urllib.parse.unquote(parsed.path.removeprefix("/wiki/").strip("/")).replace(" ", "_")
    if not title:
        return None
    if "/" in title:
        first, rest = title.split("/", 1)
        canonical_first = CANONICAL_FIRST_SEGMENTS.get(first.casefold())
        if canonical_first:
            title = f"{canonical_first}/{rest}"
    quoted = urllib.parse.quote(title, safe="(),-._~/")
    if title == "Main_Page":
        return "/"
    return f"/wiki/{quoted}/"


def archive_raw_url(timestamp: str, original: str) -> str:
    return f"https://web.archive.org/web/{timestamp}id_/{original}"


def attr_quote(value: str) -> str:
    return html.escape(value, quote=True)


def archive_banner_markup(source: str) -> str:
    return (
        '<div class="josiekins-archive-banner">'
        "<span><strong>PsychonautWiki static archive.</strong></span> "
        '<span>Pages scraped from '
        f'<a href="{attr_quote(source)}">Internet Archive captures</a> no later than 2017.</span>'
        "</div>"
    )


def attrs_to_text(attrs: list[tuple[str, str | None]]) -> str:
    if not attrs:
        return ""
    pieces = []
    for name, value in attrs:
        if value is None:
            pieces.append(name)
        else:
            pieces.append(f'{name}="{attr_quote(value)}"')
    return " " + " ".join(pieces)


def remove_wayback_attrs(attrs: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    return [
        (name, value)
        for name, value in attrs
        if not name.startswith("data-") or not name.startswith("data-wayback")
    ]


def rewrite_url(value: str, page_original: str) -> str:
    if value.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return value

    absolute = urllib.parse.urljoin(page_original, value)
    local = local_path_for_url(absolute)
    if local:
        parsed = urllib.parse.urlparse(value)
        suffix = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"{local}{suffix}"

    parsed = urllib.parse.urlparse(absolute)
    if parsed.netloc.endswith("psychonautwiki.org"):
        return f"https://web.archive.org/web/{END_TIMESTAMP}/{absolute}"
    return absolute


class Rewriter(HTMLParser):
    def __init__(self, page_original: str, page_timestamp: str) -> None:
        super().__init__(convert_charrefs=False)
        self.page_original = page_original
        self.page_timestamp = page_timestamp
        self.out: list[str] = []
        self.injected_head = False

    def handle_decl(self, decl: str) -> None:
        self.out.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.out.append(f"<?{data}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.out.append(self.render_starttag(tag, attrs, closed=False))
        if tag.lower() == "head" and not self.injected_head:
            self.injected_head = True
            self.out.append(ARCHIVE_HEAD_INJECTION)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.out.append(self.render_starttag(tag, attrs, closed=True))

    def render_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        closed: bool,
    ) -> str:
        rewritten: list[tuple[str, str | None]] = []
        for name, value in remove_wayback_attrs(attrs):
            lower = name.lower()
            if value is not None and lower in {"href", "src", "action"}:
                rewritten.append((name, rewrite_url(value, self.page_original)))
            elif value is not None and lower == "srcset":
                rewritten.append((name, rewrite_srcset(value)))
            else:
                rewritten.append((name, value))
        slash = " /" if closed else ""
        return f"<{tag}{attrs_to_text(rewritten)}{slash}>"

    def handle_endtag(self, tag: str) -> None:
        self.out.append(f"</{tag}>")
        if tag.lower() == "body":
            source = archive_raw_url(self.page_timestamp, self.page_original)
            self.out.insert(
                self.find_body_insert_index(),
                archive_banner_markup(source),
            )

    def find_body_insert_index(self) -> int:
        for index, piece in enumerate(self.out):
            if piece.lower().startswith("<body"):
                return index + 1
        return 0

    def handle_data(self, data: str) -> None:
        self.out.append(data)

    def handle_entityref(self, name: str) -> None:
        self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if "WAYBACK" not in data.upper():
            self.out.append(f"<!--{data}-->")

    def output(self) -> str:
        return "".join(self.out)


def rewrite_srcset(value: str) -> str:
    parts = []
    for candidate in value.split(","):
        bits = candidate.strip().split()
        if not bits:
            continue
        bits[0] = urllib.parse.urljoin(SOURCE_PREFIX, bits[0])
        parts.append(" ".join(bits))
    return ", ".join(parts)


def destination_for(local_path: str) -> Path:
    if local_path == "/":
        return OUTPUT_DIR / "index.html"
    return OUTPUT_DIR / local_path.strip("/") / "index.html"


def rewrite_leftover_relative_links(markup: str) -> str:
    def replace_attr(match: re.Match[str]) -> str:
        attr = match.group("attr")
        quote = match.group("quote")
        value = html.unescape(match.group("value"))
        rewritten = rewrite_url(value, SOURCE_PREFIX)
        return f"{attr}={quote}{attr_quote(rewritten)}{quote}"

    return re.sub(
        r'(?P<attr>\b(?:href|src|action))=(?P<quote>["\'])(?P<value>/wiki/[^"\']+)(?P=quote)',
        replace_attr,
        markup,
    )


def mirror_capture(capture: dict[str, str], force: bool) -> dict[str, Any]:
    local_path = local_path_for_url(capture["original"])
    if local_path is None:
        raise ValueError(f"cannot mirror non-wiki URL: {capture['original']}")

    destination = destination_for(local_path)
    source = archive_raw_url(capture["timestamp"], capture["original"])
    if destination.exists() and not force:
        return {
            "original": capture["original"],
            "timestamp": capture["timestamp"],
            "path": local_path,
            "source": source,
            "cached": True,
        }

    payload = fetch_bytes(source).decode("utf-8", errors="replace")
    rewriter = Rewriter(capture["original"], capture["timestamp"])
    rewriter.feed(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rewrite_leftover_relative_links(rewriter.output()), encoding="utf-8")
    return {
        "original": capture["original"],
        "timestamp": capture["timestamp"],
        "path": local_path,
        "source": source,
        "cached": False,
    }


def write_manifest(entries: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "productArea": "Standalone Archive",
                "archive": "PsychonautWiki 2016 static archive",
                "source": "Internet Archive CDX",
                "from": START_TIMESTAMP,
                "to": END_TIMESTAMP,
                "pages": len(entries),
                "entries": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def normalized_title_from_path(path: str) -> str:
    title = path.removeprefix("/wiki/").strip("/")
    return urllib.parse.unquote(title).replace(" ", "_").casefold()


def archive_url_from_local_path(path: str) -> str:
    title = urllib.parse.unquote(path.removeprefix("/wiki/").strip("/"))
    encoded_title = urllib.parse.quote(title, safe="(),-._~/")
    return f"https://web.archive.org/web/{END_TIMESTAMP}/https://psychonautwiki.org/wiki/{encoded_title}"


def build_canonical_path_map(entries: list[dict[str, Any]]) -> dict[str, str]:
    by_normalized: dict[str, set[str]] = {}
    for entry in entries:
        path = entry["path"]
        if path == "/":
            continue
        by_normalized.setdefault(normalized_title_from_path(path), set()).add(path)

    return {
        normalized: next(iter(paths))
        for normalized, paths in by_normalized.items()
        if len(paths) == 1
    }


def repair_local_wiki_links(entries: list[dict[str, Any]]) -> None:
    exact_paths = {entry["path"] for entry in entries}
    canonical_paths = build_canonical_path_map(entries)
    link_pattern = re.compile(
        r'(?P<attr>\bhref)=(?P<quote>["\'])(?P<value>/wiki/[^"\']+)(?P=quote)',
    )

    def repair_href(value: str) -> str:
        parsed = urllib.parse.urlparse(html.unescape(value))
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        if parsed.path in exact_paths:
            return f"{parsed.path}{fragment}"

        canonical_path = canonical_paths.get(normalized_title_from_path(parsed.path))
        if canonical_path:
            return f"{canonical_path}{fragment}"

        return f"{archive_url_from_local_path(parsed.path)}{fragment}"

    def replace_attr(match: re.Match[str]) -> str:
        attr = match.group("attr")
        quote = match.group("quote")
        value = repair_href(match.group("value"))
        return f"{attr}={quote}{attr_quote(value)}{quote}"

    for file_path in OUTPUT_DIR.glob("**/index.html"):
        markup = file_path.read_text(encoding="utf-8", errors="replace")
        repaired = link_pattern.sub(replace_attr, markup)
        if repaired != markup:
            file_path.write_text(repaired, encoding="utf-8")


def refresh_archive_banner_chrome() -> None:
    def replace_banner(match: re.Match[str]) -> str:
        return archive_banner_markup(html.unescape(match.group("source")))

    for file_path in OUTPUT_DIR.glob("**/index.html"):
        markup = file_path.read_text(encoding="utf-8", errors="replace")
        refreshed = ARCHIVE_HEAD_PATTERN.sub(ARCHIVE_HEAD_INJECTION, markup, count=1)
        refreshed = ARCHIVE_BANNER_PATTERN.sub(replace_banner, refreshed, count=1)
        if refreshed != markup:
            file_path.write_text(refreshed, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    captures = load_cdx(args.limit)
    captures = [item for item in captures if item["original"] != MAIN_PAGE]
    captures.insert(
        0,
        {
            "timestamp": MAIN_PAGE_TIMESTAMP,
            "original": MAIN_PAGE,
            "statuscode": "200",
            "mimetype": "text/html",
            "digest": "",
        },
    )

    entries: list[dict[str, Any]] = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_capture = {
            executor.submit(mirror_capture, capture, args.force): capture
            for capture in captures
        }
        for future in concurrent.futures.as_completed(future_to_capture):
            completed += 1
            try:
                entries.append(future.result())
            except (RuntimeError, urllib.error.URLError) as exc:
                print(f"warning: {exc}", file=sys.stderr)
            if completed % 25 == 0:
                print(f"mirrored {completed}/{len(captures)} pages", file=sys.stderr)

    entries.sort(key=lambda entry: entry["path"])

    refresh_archive_banner_chrome()
    repair_local_wiki_links(entries)
    write_manifest(entries)
    print(f"mirrored {len(entries)} pages into {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
