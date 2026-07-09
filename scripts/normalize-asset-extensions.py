#!/usr/bin/env python3
"""Correct local asset filename extensions from their actual byte signatures.

Wayback's thumbnail endpoint can render an SVG source as PNG while retaining
the source filename in its URL.  Static servers use the filename extension to
choose a MIME type, so a PNG saved as ``example.svg`` is served as SVG and
fails to display.  This post-processing step renames such files and updates
every local HTML/CSS reference.  It is idempotent.
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
ASSETS = PUBLIC / "assets"
MAGIC_EXTENSIONS = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"RIFF", ".webp"),
)


def detected_extension(path: Path) -> str | None:
    header = path.read_bytes()[:12]
    for magic, extension in MAGIC_EXTENSIONS:
        if header.startswith(magic):
            return extension
    return None


def find_renames(limit: int | None) -> dict[str, str]:
    mappings: dict[str, str] = {}
    for path in sorted(ASSETS.rglob("*.svg")):
        if not path.is_file():
            continue
        extension = detected_extension(path)
        if extension is None:
            continue
        destination = path.with_suffix(extension)
        if destination.exists():
            raise RuntimeError(f"cannot rename {path}: {destination} already exists")
        old = "/" + path.relative_to(PUBLIC).as_posix()
        new = "/" + destination.relative_to(PUBLIC).as_posix()
        mappings[old] = new
        if limit is not None and len(mappings) >= limit:
            break
    return mappings


def rewrite_references(mappings: dict[str, str], dry_run: bool) -> int:
    files_changed = 0
    replacements = dict(mappings)
    replacements.update({
        urllib.parse.quote(old, safe="/%"): urllib.parse.quote(new, safe="/%")
        for old, new in mappings.items()
    })
    for path in sorted((*PUBLIC.rglob("*.html"), *PUBLIC.rglob("*.css"))):
        text = path.read_bytes().decode("utf-8", errors="replace")
        updated = text
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated != text:
            files_changed += 1
            if not dry_run:
                path.write_bytes(updated.encode("utf-8"))
    return files_changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing them")
    parser.add_argument("--limit", type=int, default=None, help="only normalize the first N assets")
    args = parser.parse_args()

    mappings = find_renames(args.limit)
    files_changed = rewrite_references(mappings, args.dry_run)
    if not args.dry_run:
        for old, new in mappings.items():
            (PUBLIC / old.lstrip("/")).rename(PUBLIC / new.lstrip("/"))

    mode = "would normalize" if args.dry_run else "normalized"
    print(f"asset-extension normalization {mode}: {len(mappings)} assets, {files_changed} reference files")
    for old, new in mappings.items():
        print(f"  {old} -> {new}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"asset-extension normalization failed: {error}", file=sys.stderr)
        raise SystemExit(1)
