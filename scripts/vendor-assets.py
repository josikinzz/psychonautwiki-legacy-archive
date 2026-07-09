#!/usr/bin/env python3
"""Vendor remote psychonautwiki.org assets (CSS, images, thumbnails, favicon)
referenced from the static archive in public/ into public/assets/, then rewrite
the HTML to point at the local copies.

Scope, deliberately narrow per the archive's house style:
  - <link href>  -> vendored if it points at a load.php CSS bundle, thumb.php,
    /w/images/, /w/resources/, /w/extensions/, /w/skins/, or favicon.ico.
  - <img src>    -> same asset rules as <link href>.
  - <img srcset> -> never vendored (these were emitted pointing directly at the
    live psychonautwiki.org host, see mirror-psychonautwiki-archive.py); the
    attribute is deleted outright.
  - <script src> -> never touched. load.php JS bundles are intentionally left
    alone (another pass strips <script> tags entirely).
  - <a href>     -> never touched.

CSS bundles are downloaded once (deduped by their sha1'd query string) and then
post-processed: every url()/@import target that resolves to psychonautwiki.org
(root-relative paths like /PWlogoblink2.gif, absolute /w/... paths, and
protocol-relative external hosts like upload.wikimedia.org are all handled
correctly) is itself downloaded into public/assets/w/... and the url() is
rewritten to the local root-relative path.

Usage:
    python3 scripts/vendor-assets.py [--limit N] [--download-only] [--rewrite-only]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
ASSETS_DIR = PUBLIC_DIR / "assets"

WAYBACK_TIMESTAMP = "20171231235959"
USER_AGENT = "josiekins-psychonautwiki-archive-vendor/1.0 (+static asset mirror)"
REQUEST_DELAY = 1.5
TIMEOUT = 30
RETRIES = 3

ASSET_HOSTS = {"psychonautwiki.org", "www.psychonautwiki.org"}

MIRROR_PREFIXES = ("/w/images/", "/w/resources/", "/w/extensions/", "/w/skins/")

# A URL as it appears wayback-wrapped and HTML-escaped in the mirrored pages, e.g.
# https://web.archive.org/web/20171231235959/https://psychonautwiki.org/w/thumb.php?f=X&amp;width=20
WRAPPED_RE = re.compile(
    r"https://web\.archive\.org/web/\d+/(https://psychonautwiki\.org/[^\"'<>\s]*)"
)
# A bare (non-wayback-wrapped) reference straight to psychonautwiki.org, as seen
# in <img srcset> and the rare stray leftover.
BARE_RE = re.compile(r"https://psychonautwiki\.org/[^\"'<>\s]*")
# Used only during the scan phase to classify a single attribute value.
CANDIDATE_RE = re.compile(r"^https://web\.archive\.org/web/\d+/(https://psychonautwiki\.org/.*)$")

TAG_RE = re.compile(r"<(link|img)\b([^>]*)>", re.IGNORECASE)
HREF_RE = re.compile(r'\bhref\s*=\s*"([^"]*)"', re.IGNORECASE)
SRC_RE = re.compile(r'\bsrc\s*=\s*"([^"]*)"', re.IGNORECASE)
IMG_SRCSET_RE = re.compile(r'(<img\b[^>]*?)\s+srcset\s*=\s*"[^"]*"([^>]*>)', re.IGNORECASE)

CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^'\")]*)\1\s*\)", re.IGNORECASE)
CSS_IMPORT_RE = re.compile(r'@import\s+(?:url\(\s*)?["\']?([^"\');]+)["\']?\)?\s*;', re.IGNORECASE)

CSS_RESOLVE_BASE = "https://psychonautwiki.org/w/load.php"


# --------------------------------------------------------------------------- #
# Networking
# --------------------------------------------------------------------------- #

_last_request_at = 0.0


def _polite_wait() -> None:
    global _last_request_at
    now = time.monotonic()
    remaining = REQUEST_DELAY - (now - _last_request_at)
    if remaining > 0:
        time.sleep(remaining)
    _last_request_at = time.monotonic()


def fetch_bytes(url: str) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        _polite_wait()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - we want to retry on anything
            last_exc = exc
            if attempt < RETRIES:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(str(last_exc))


def wayback_raw_url(original: str) -> str:
    return f"https://web.archive.org/web/{WAYBACK_TIMESTAMP}id_/{original}"


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #


def sanitize_segment(name: str) -> str:
    name = name.replace("/", "_").replace("\\", "_")
    name = re.sub(r'[:*?"<>|\x00-\x1f]', "_", name)
    return name or "_"


def _host_ok(parsed: urllib.parse.SplitResult) -> bool:
    return (parsed.hostname or "").lower() in ASSET_HOSTS


def _css_bundle_asset(query: str) -> Optional[tuple[str, Path, str]]:
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    only = (params.get("only") or [""])[0]
    if only != "styles":
        return None
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]
    return "css", ASSETS_DIR / "css" / f"{digest}.css", f"/assets/css/{digest}.css"


def _thumb_asset(query: str) -> Optional[tuple[str, Path, str]]:
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    f_name = (params.get("f") or [None])[0]
    width = (params.get("width") or [None])[0]
    if not f_name or not width:
        return None
    filename = sanitize_segment(f"{width}px-{f_name}")
    return "thumb", ASSETS_DIR / "thumbs" / filename, f"/assets/thumbs/{urllib.parse.quote(filename)}"


def _mirror_asset(path: str) -> Optional[tuple[str, Path, str]]:
    rel = path[len("/w/"):] if path.startswith("/w/") else path.lstrip("/")
    segments = [sanitize_segment(urllib.parse.unquote(seg)) for seg in rel.split("/") if seg]
    if not segments:
        return None
    fs_path = ASSETS_DIR / "w"
    for seg in segments:
        fs_path = fs_path / seg
    url_path = "/assets/w/" + "/".join(urllib.parse.quote(seg) for seg in segments)
    return "mirror", fs_path, url_path


def classify_html_asset(url: str) -> Optional[tuple[str, Path, str]]:
    """Strict classifier used for <link href>/<img src> found directly in HTML.
    Deliberately narrow so dynamic endpoints (index.php, api.php,
    opensearch_desc.php, ExportRDF, ...) are never vendored."""
    parsed = urllib.parse.urlsplit(url)
    if not _host_ok(parsed):
        return None
    path = parsed.path
    if path == "/favicon.ico":
        return "favicon", ASSETS_DIR / "favicon.ico", "/assets/favicon.ico"
    if path == "/w/load.php":
        return _css_bundle_asset(parsed.query)
    if path == "/w/thumb.php":
        return _thumb_asset(parsed.query)
    if path.startswith(MIRROR_PREFIXES):
        return _mirror_asset(path)
    return None


def classify_css_target(url: str) -> Optional[tuple[str, Path, str]]:
    """Permissive classifier used for url()/@import targets found inside
    vendored CSS. CSS is a much more constrained context than arbitrary HTML,
    so any same-host path (including domain-root files like the site logo,
    /PWlogoblink2.gif) is mirrored. Non-psychonautwiki.org hosts (e.g.
    upload.wikimedia.org icons pulled in by SemanticMediaWiki) are left alone."""
    parsed = urllib.parse.urlsplit(url)
    if not _host_ok(parsed):
        return None
    path = parsed.path
    if not path or path == "/":
        return None
    if path == "/favicon.ico":
        return "favicon", ASSETS_DIR / "favicon.ico", "/assets/favicon.ico"
    if path == "/w/load.php":
        return _css_bundle_asset(parsed.query)
    if path == "/w/thumb.php":
        return _thumb_asset(parsed.query)
    return _mirror_asset(path)


def extract_candidate(escaped_value: str) -> Optional[str]:
    """Given a raw (still HTML-escaped) attribute value, return the
    unescaped psychonautwiki.org URL it points at, or None."""
    match = CANDIDATE_RE.match(escaped_value)
    if match:
        return html.unescape(match.group(1))
    if escaped_value.startswith("https://psychonautwiki.org/"):
        return html.unescape(escaped_value)
    return None


# --------------------------------------------------------------------------- #
# Asset bookkeeping
# --------------------------------------------------------------------------- #


class Asset:
    __slots__ = ("original", "category", "fs_path", "url_path", "success")

    def __init__(self, original: str, category: str, fs_path: Path, url_path: str) -> None:
        self.original = original
        self.category = category
        self.fs_path = fs_path
        self.url_path = url_path
        self.success: Optional[bool] = None


class Context:
    def __init__(self) -> None:
        self.stats: dict[str, int] = defaultdict(int)
        self.failures: list[tuple[str, str]] = []
        self.by_original: dict[str, Asset] = {}
        self.by_fs_path: dict[Path, Asset] = {}


def ensure_asset(original: str, category: str, fs_path: Path, url_path: str, ctx: Context) -> Asset:
    asset = ctx.by_original.get(original)
    if asset is not None:
        return asset
    asset = ctx.by_fs_path.get(fs_path)
    if asset is not None:
        ctx.by_original[original] = asset
        return asset
    asset = Asset(original, category, fs_path, url_path)
    ctx.by_original[original] = asset
    ctx.by_fs_path[fs_path] = asset
    ctx.stats["assets_found"] += 1
    return asset


def download_asset(original_url: str, fs_path: Path, ctx: Context) -> bool:
    if fs_path.exists() and fs_path.stat().st_size > 0:
        ctx.stats["cached"] += 1
        return True
    try:
        data = fetch_bytes(wayback_raw_url(original_url))
    except Exception as exc:  # noqa: BLE001
        ctx.failures.append((original_url, str(exc)))
        ctx.stats["failed"] += 1
        return False
    fs_path.parent.mkdir(parents=True, exist_ok=True)
    fs_path.write_bytes(data)
    ctx.stats["downloaded"] += 1
    return True


def vendor(asset: Asset, ctx: Context) -> bool:
    """Ensure asset is on disk; recurse into embedded CSS assets if needed."""
    if asset.success is not None:
        return asset.success
    asset.success = False  # placeholder guards against pathological @import cycles
    ok = download_asset(asset.original, asset.fs_path, ctx)
    if ok and asset.category == "css":
        process_css(asset.fs_path, ctx)
    asset.success = ok
    return ok


def _css_skip(target: str) -> bool:
    target = target.strip()
    return not target or target.startswith(("data:", "#", "javascript:"))


def process_css(fs_path: Path, ctx: Context) -> None:
    try:
        text = fs_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return
    original_text = text

    def resolve(target: str) -> Optional[tuple[Asset, str]]:
        absolute = urllib.parse.urljoin(CSS_RESOLVE_BASE, target)
        classified = classify_css_target(absolute)
        if classified is None:
            return None
        category, asset_fs, asset_url = classified
        asset = ensure_asset(absolute, category, asset_fs, asset_url, ctx)
        return asset, asset_url

    def repl_import(match: re.Match) -> str:
        target = match.group(1).strip().strip("'\"")
        if _css_skip(target):
            return match.group(0)
        resolved = resolve(target)
        if resolved is None:
            return match.group(0)
        asset, asset_url = resolved
        if vendor(asset, ctx):
            ctx.stats["css_import_rewrites"] += 1
            return f"@import url({asset_url});"
        return match.group(0)

    text = CSS_IMPORT_RE.sub(repl_import, text)

    def repl_url(match: re.Match) -> str:
        target = match.group(2).strip()
        if _css_skip(target):
            return match.group(0)
        resolved = resolve(target)
        if resolved is None:
            return match.group(0)
        asset, asset_url = resolved
        if vendor(asset, ctx):
            ctx.stats["css_url_rewrites"] += 1
            return f"url({asset_url})"
        return match.group(0)

    text = CSS_URL_RE.sub(repl_url, text)

    ctx.stats["css_processed"] += 1
    if text != original_text:
        fs_path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# HTML scan + rewrite
# --------------------------------------------------------------------------- #


def scan_html_file(path: Path, ctx: Context) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for tag_match in TAG_RE.finditer(text):
        tag = tag_match.group(1).lower()
        attrs_text = tag_match.group(2)
        attr_re = HREF_RE if tag == "link" else SRC_RE
        for value_match in attr_re.finditer(attrs_text):
            real_url = extract_candidate(value_match.group(1))
            if real_url is None:
                continue
            classified = classify_html_asset(real_url)
            if classified is None:
                continue
            category, fs_path, url_path = classified
            ensure_asset(real_url, category, fs_path, url_path, ctx)


def rewrite_html_file(path: Path, ctx: Context) -> tuple[int, int]:
    """Returns (references_replaced, srcset_attrs_removed) for this file. Writes
    the file back only if something actually changed."""
    text = path.read_text(encoding="utf-8", errors="replace")
    original_text = text
    replaced = 0
    srcset_removed = 0

    text, srcset_removed = IMG_SRCSET_RE.subn(r"\1\2", text)

    def repl_wrapped(match: re.Match) -> str:
        nonlocal replaced
        real_url = html.unescape(match.group(1))
        asset = ctx.by_original.get(real_url)
        if asset is not None and asset.success:
            replaced += 1
            return asset.url_path
        return match.group(0)

    text = WRAPPED_RE.sub(repl_wrapped, text)

    def repl_bare(match: re.Match) -> str:
        nonlocal replaced
        real_url = html.unescape(match.group(0))
        asset = ctx.by_original.get(real_url)
        if asset is not None and asset.success:
            replaced += 1
            return asset.url_path
        return match.group(0)

    text = BARE_RE.sub(repl_bare, text)

    if text != original_text:
        path.write_text(text, encoding="utf-8")
    return replaced, srcset_removed


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="only process the first N HTML files")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true", help="fetch/vendor assets, skip rewriting HTML")
    mode.add_argument("--rewrite-only", action="store_true", help="rewrite HTML using assets already on disk, no network")
    args = parser.parse_args()

    do_download = not args.rewrite_only
    do_rewrite = not args.download_only

    html_files = sorted(PUBLIC_DIR.glob("**/index.html"), key=lambda p: str(p))
    if args.limit is not None:
        html_files = html_files[: args.limit]

    ctx = Context()

    for path in html_files:
        scan_html_file(path, ctx)

    if do_download:
        for asset in sorted(ctx.by_original.values(), key=lambda a: a.original):
            vendor(asset, ctx)
    else:
        for asset in ctx.by_original.values():
            asset.success = asset.fs_path.exists() and asset.fs_path.stat().st_size > 0

    files_rewritten = 0
    references_replaced = 0
    srcset_removed = 0
    if do_rewrite:
        for path in html_files:
            replaced, removed = rewrite_html_file(path, ctx)
            if replaced or removed:
                files_rewritten += 1
            references_replaced += replaced
            srcset_removed += removed

    print("vendor-assets summary", file=sys.stderr)
    print(f"  html files scanned:      {len(html_files)}", file=sys.stderr)
    print(f"  unique assets found:     {ctx.stats['assets_found']}", file=sys.stderr)
    print(f"  downloaded:              {ctx.stats['downloaded']}", file=sys.stderr)
    print(f"  cached (already local):  {ctx.stats['cached']}", file=sys.stderr)
    print(f"  failed:                  {ctx.stats['failed']}", file=sys.stderr)
    print(f"  css files processed:     {ctx.stats['css_processed']}", file=sys.stderr)
    print(f"  css url() rewrites:      {ctx.stats['css_url_rewrites']}", file=sys.stderr)
    print(f"  css @import rewrites:    {ctx.stats['css_import_rewrites']}", file=sys.stderr)
    print(f"  html files rewritten:    {files_rewritten}", file=sys.stderr)
    print(f"  references replaced:     {references_replaced}", file=sys.stderr)
    print(f"  srcset attrs removed:    {srcset_removed}", file=sys.stderr)
    if ctx.failures:
        print(f"  failed URLs ({len(ctx.failures)}):", file=sys.stderr)
        for url, reason in ctx.failures:
            print(f"    {url}  ({reason})", file=sys.stderr)


if __name__ == "__main__":
    main()
