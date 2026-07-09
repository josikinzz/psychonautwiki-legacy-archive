#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = ROOT / "public"
MANIFEST_PATH = ARCHIVE_DIR / "manifest.json"
END_TIMESTAMP = "20171231235959"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def local_path_to_file(path: str) -> Path:
    if path == "/":
        return ARCHIVE_DIR / "index.html"
    return ARCHIVE_DIR / path.strip("/") / "index.html"


def check_manifest() -> list[str]:
    errors: list[str] = []
    if not MANIFEST_PATH.exists():
        return [f"missing manifest: {MANIFEST_PATH}"]

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    if manifest.get("to") != END_TIMESTAMP:
        errors.append(f"manifest cutoff is {manifest.get('to')}, expected {END_TIMESTAMP}")
    if manifest.get("pages") != len(entries):
        errors.append(f"manifest pages={manifest.get('pages')} but entries={len(entries)}")

    seen_paths: set[str] = set()
    for entry in entries:
        path = entry.get("path")
        timestamp = entry.get("timestamp", "")
        if not isinstance(path, str):
            errors.append(f"entry missing string path: {entry!r}")
            continue
        if path in seen_paths:
            errors.append(f"duplicate manifest path: {path}")
        seen_paths.add(path)
        if timestamp > END_TIMESTAMP:
            errors.append(f"{path} uses post-cutoff timestamp {timestamp}")
        if not local_path_to_file(path).exists():
            errors.append(f"{path} is in manifest but has no index.html")

    html_files = {file for file in ARCHIVE_DIR.glob("**/index.html")}
    manifest_files = {local_path_to_file(path) for path in seen_paths}
    extra_files = sorted(html_files - manifest_files)
    if extra_files:
        errors.append(f"{len(extra_files)} html page files are not in manifest")
        errors.extend(f"extra html file: {file.relative_to(ARCHIVE_DIR)}" for file in extra_files[:20])

    return errors


def check_local_links() -> list[str]:
    errors: list[str] = []
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    local_paths = {entry["path"] for entry in manifest["entries"]}

    for file_path in ARCHIVE_DIR.glob("**/index.html"):
        parser = LinkParser()
        parser.feed(file_path.read_text(encoding="utf-8", errors="replace"))
        source = file_path.relative_to(ARCHIVE_DIR)
        for href in parser.hrefs:
            parsed = urllib.parse.urlparse(href)
            if parsed.scheme or parsed.netloc:
                continue
            if not parsed.path.startswith("/wiki/"):
                continue
            if parsed.path not in local_paths:
                errors.append(f"{source}: local href points at missing page: {href}")

    return errors


def main() -> int:
    errors = check_manifest()
    if not errors:
        errors.extend(check_local_links())

    if errors:
        print("PsychonautWiki archive link check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(
        f"PsychonautWiki archive link check OK: {manifest['pages']} pages, cutoff {manifest['to']}, no broken local wiki hrefs.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
