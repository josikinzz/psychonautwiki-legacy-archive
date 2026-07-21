#!/usr/bin/env python3
"""Rewrite archived PsychonautWiki pages to strip dead MediaWiki JS,
convert red links to inert spans, and wire up the shared client-side
search/random and mobile compatibility layers.

Usage:
    python3 scripts/enhance-pages.py [--dry-run] [--limit N]
    python3 scripts/enhance-pages.py --build-index

The HTML rewriting is done with targeted regexes on known, verified patterns
(see the archive's <script>/<link> shapes) rather than a DOM re-serializer,
so every byte of the file that isn't explicitly targeted is preserved as-is.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
MANIFEST_PATH = PUBLIC_DIR / "manifest.json"
SEARCH_INDEX_PATH = PUBLIC_DIR / "assets" / "search-index.json"

ARCHIVE_JS_TAG = '<script defer src="/assets/archive.js"></script>'
VIEWPORT_META_TAG = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />'
MOBILE_CSS_TAG = '<link rel="stylesheet" href="/assets/mobile.css" />'
RANDOM_LINK_ID = "archive-random-link"

# ---------------------------------------------------------------------------
# Regexes for the HTML rewrite pass
# ---------------------------------------------------------------------------

# <script async="" src="https://.../load.php?...&only=scripts&skin=vector"></script>
# Host varies (web.archive.org mirror, fastly CDN, etc.) - match on the
# load.php path regardless of host.
SCRIPT_LOAD_PHP_RE = re.compile(
    r'<script\b[^>]*\bsrc="[^"]*/load\.php\?[^"]*"[^>]*>\s*</script>\n?',
    re.IGNORECASE,
)

# Any <script ...>...</script> block, used to inspect inline (no-src) scripts
# for references to dead MediaWiki globals.
SCRIPT_BLOCK_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
SCRIPT_HAS_SRC_RE = re.compile(r'\bsrc\s*=', re.IGNORECASE)
INLINE_SCRIPT_TRIGGERS = (
    "mw.config",
    "RLQ",
    "mw.loader",
    "document.documentElement.className",
)

# <link> tags that only make sense against a live MediaWiki install.
LINK_REMOVE_RES = [
    re.compile(r'<link rel="EditURI"[^>]*/>\n?'),
    re.compile(r'<link rel="ExportRDF"[^>]*/>\n?'),
    re.compile(r'<link rel="search"[^>]*/>\n?'),
    re.compile(r'<link rel="alternate" type="application/atom\+xml"[^>]*/>\n?'),
]

META_RESOURCE_LOADER_RE = re.compile(r'<meta name="ResourceLoaderDynamicStyles"[^>]*/>\n?')

# Red links: <a ... href="....action=edit&(amp;)?redlink=1..." ...>TEXT</a>
REDLINK_RE = re.compile(
    r'<a\b[^>]*action=edit&(?:amp;)?redlink=1[^>]*>(.*?)</a>',
    re.DOTALL,
)

# Vector's namespace tabs require an anchor-shaped child for their historical
# positioning and background styles. Red-link conversion otherwise leaves the
# unavailable Discussion tab as a nested span, which renders above the tab.
BROKEN_TALK_TAB_RE = re.compile(
    r'(<li id="ca-talk"[^>]*>\s*<span>)'
    r'<span class="new" title="page not archived">(.*?)</span>'
    r'(</span>\s*</li>)',
    re.DOTALL,
)

# Sidebar "Random article" link, pointed at the web.archive.org mirror of
# Special:Random (which is not something a static archive can serve).
RANDOM_LINK_RE = re.compile(
    r'<a href="https://web\.archive\.org/web/\d+/https://psychonautwiki\.org/wiki/Special:Random">'
)

# Image-wrapping anchors that point at the wayback File: page while the <img>
# inside them is already vendored locally: retarget the click at the local
# image file itself. Anchors around still-remote images are left alone (the
# wayback File: page is the only copy that exists).
IMAGE_ANCHOR_RE = re.compile(
    r'<a href="https://web\.archive\.org/[^"]*"( class="image"[^>]*)>(\s*<img[^>]*?src="(/assets/[^"]*)")'
)

HEAD_CLOSE_RE = re.compile(r"</head>", re.IGNORECASE)


class Stats:
    def __init__(self) -> None:
        self.files_scanned = 0
        self.files_changed = 0
        self.files_skipped_empty = 0
        self.load_php_scripts_removed = 0
        self.inline_scripts_removed = 0
        self.links_removed = 0
        self.meta_removed = 0
        self.redlinks_converted = 0
        self.talk_tabs_repaired = 0
        self.search_hook_injected = 0
        self.viewport_meta_injected = 0
        self.mobile_css_injected = 0
        self.random_link_rewired = 0
        self.image_links_localized = 0


def _strip_load_php_scripts(text: str, stats: Stats) -> str:
    text, n = SCRIPT_LOAD_PHP_RE.subn("", text)
    stats.load_php_scripts_removed += n
    return text


def _strip_inline_mw_scripts(text: str, stats: Stats) -> str:
    def _replace(match: "re.Match[str]") -> str:
        attrs, content = match.group(1), match.group(2)
        if SCRIPT_HAS_SRC_RE.search(attrs):
            # External script (e.g. Raven, geoiplookup) - not our concern.
            return match.group(0)
        if any(trigger in content for trigger in INLINE_SCRIPT_TRIGGERS):
            stats.inline_scripts_removed += 1
            return ""
        return match.group(0)

    return SCRIPT_BLOCK_RE.sub(_replace, text)


def _strip_dead_links(text: str, stats: Stats) -> str:
    for pattern in LINK_REMOVE_RES:
        text, n = pattern.subn("", text)
        stats.links_removed += n
    text, n = META_RESOURCE_LOADER_RE.subn("", text)
    stats.meta_removed += n
    return text


def _convert_redlinks(text: str, stats: Stats) -> str:
    def _replace(match: "re.Match[str]") -> str:
        stats.redlinks_converted += 1
        return f'<span class="new" title="page not archived">{match.group(1)}</span>'

    return REDLINK_RE.sub(_replace, text)


def _repair_talk_tabs(text: str, stats: Stats) -> str:
    def _replace(match: "re.Match[str]") -> str:
        stats.talk_tabs_repaired += 1
        return (
            f'{match.group(1)}<a class="new" title="page not archived" '
            f'aria-disabled="true">{match.group(2)}</a>{match.group(3)}'
        )

    return BROKEN_TALK_TAB_RE.sub(_replace, text)


def _inject_search_hook(text: str, stats: Stats) -> str:
    if "/assets/archive.js" in text:
        return text
    new_text, n = HEAD_CLOSE_RE.subn(ARCHIVE_JS_TAG + "\n</head>", text, count=1)
    if n:
        stats.search_hook_injected += 1
        return new_text
    return text


def _inject_mobile_layer(text: str, stats: Stats) -> str:
    tags: list[str] = []
    if 'name="viewport"' not in text:
        tags.append(VIEWPORT_META_TAG)
        stats.viewport_meta_injected += 1
    if '/assets/mobile.css' not in text:
        tags.append(MOBILE_CSS_TAG)
        stats.mobile_css_injected += 1
    if not tags:
        return text

    injection = "\n".join(tags) + "\n"
    new_text, n = HEAD_CLOSE_RE.subn(injection + "</head>", text, count=1)
    if not n:
        stats.viewport_meta_injected -= VIEWPORT_META_TAG in tags
        stats.mobile_css_injected -= MOBILE_CSS_TAG in tags
        return text
    return new_text


def _rewire_random_link(text: str, stats: Stats) -> str:
    if f'id="{RANDOM_LINK_ID}"' in text:
        return text
    new_text, n = RANDOM_LINK_RE.subn(f'<a href="#" id="{RANDOM_LINK_ID}">', text, count=1)
    if n:
        stats.random_link_rewired += 1
    return new_text


def _localize_image_links(text: str, stats: Stats) -> str:
    def _replace(match: "re.Match[str]") -> str:
        stats.image_links_localized += 1
        return f'<a href="{match.group(3)}"{match.group(1)}>{match.group(2)}'

    return IMAGE_ANCHOR_RE.sub(_replace, text)


def enhance_html(text: str, stats: Stats) -> str:
    text = _strip_load_php_scripts(text, stats)
    text = _strip_inline_mw_scripts(text, stats)
    text = _strip_dead_links(text, stats)
    text = _convert_redlinks(text, stats)
    text = _repair_talk_tabs(text, stats)
    text = _inject_mobile_layer(text, stats)
    text = _inject_search_hook(text, stats)
    text = _rewire_random_link(text, stats)
    text = _localize_image_links(text, stats)
    return text


def iter_html_files() -> list[Path]:
    files = [PUBLIC_DIR / "index.html"]
    # rglob (not glob("*/index.html")) because a handful of pages nest one
    # level deeper, e.g. public/wiki/1P-LSD/Summary/index.html.
    files += sorted((PUBLIC_DIR / "wiki").rglob("index.html"))
    return [f for f in files if f.exists()]


def run_enhance(dry_run: bool, limit: int | None) -> Stats:
    stats = Stats()
    files = iter_html_files()
    if limit is not None:
        files = files[:limit]

    for path in files:
        stats.files_scanned += 1
        original = path.read_bytes().decode("utf-8")
        if not original.strip():
            stats.files_skipped_empty += 1
            continue

        updated = enhance_html(original, stats)
        if updated != original:
            stats.files_changed += 1
            rel = path.relative_to(ROOT)
            if dry_run:
                print(f"[dry-run] would change: {rel}")
            else:
                path.write_bytes(updated.encode("utf-8"))
                print(f"changed: {rel}")

    return stats


def print_summary(stats: Stats, dry_run: bool) -> None:
    verb = "would be changed" if dry_run else "changed"
    print("")
    print("=== enhance-pages summary ===")
    print(f"files scanned:            {stats.files_scanned}")
    print(f"files skipped (empty):    {stats.files_skipped_empty}")
    print(f"files {verb}:{' ' * max(1, 15 - len(verb))}{stats.files_changed}")
    print(f"load.php scripts removed: {stats.load_php_scripts_removed}")
    print(f"inline mw scripts removed:{stats.inline_scripts_removed}")
    print(f"dead <link> tags removed: {stats.links_removed}")
    print(f"ResourceLoaderDynamicStyles meta removed: {stats.meta_removed}")
    print(f"redlinks converted:       {stats.redlinks_converted}")
    print(f"search hook injected:     {stats.search_hook_injected}")
    print(f"viewport meta injected:   {stats.viewport_meta_injected}")
    print(f"mobile CSS injected:      {stats.mobile_css_injected}")
    print(f"random link rewired:      {stats.random_link_rewired}")
    print(f"image links localized:    {stats.image_links_localized}")


# ---------------------------------------------------------------------------
# search-index.json generator
# ---------------------------------------------------------------------------


def _title_from_path(path: str) -> str:
    if path == "/":
        return "Main Page"
    segment = path
    if segment.startswith("/wiki/"):
        segment = segment[len("/wiki/"):]
    segment = segment.strip("/")
    segment = urllib.parse.unquote(segment)
    segment = segment.replace("_", " ")
    return segment


def build_index() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])

    index: list[list[str]] = []
    for entry in entries:
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        index.append([_title_from_path(path), path])

    SEARCH_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEARCH_INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {len(index)} entries to {SEARCH_INDEX_PATH.relative_to(ROOT)}")
    return len(index)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing files")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N html files")
    parser.add_argument(
        "--build-index",
        action="store_true",
        help="build public/assets/search-index.json from manifest.json and exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if args.build_index:
        build_index()
        return 0

    stats = run_enhance(dry_run=args.dry_run, limit=args.limit)
    print_summary(stats, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
