#!/usr/bin/env python3
"""Convert vendored PNG/JPG/JPEG assets under public/assets/ to WebP wherever
that yields a smaller file, then rewrite every reference to the converted
files across the archive.

Scope, deliberately narrow per the archive's house style:
  - Only *.png / *.jpg / *.jpeg (case-insensitive) under public/assets/ are
    considered. .gif, .svg, .ico, and everything else is left untouched.
  - Images are opened by content (Pillow sniffs the real format), not by
    file extension -- a handful of archived files are mislabeled (e.g. a
    ".png" that is actually a JPEG), and this must still work correctly.
  - Both a lossy (quality=85, method=6) and, for content-detected PNGs, a
    lossless encoding are produced; the smaller of the two is kept.
  - The WebP is adopted only if it is strictly smaller than the original
    file. Otherwise the WebP is discarded and the original is left
    untouched (no reference changes for that file).
  - For every adopted conversion the original file is deleted and every
    root-relative reference to its old path (e.g. /assets/thumbs/foo.png)
    is rewritten to the new .webp path across public/**/index.html,
    public/404.html, and public/assets/css/*.css.

Usage:
    python3 scripts/convert-webp.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
ASSETS_DIR = PUBLIC_DIR / "assets"
CSS_DIR = ASSETS_DIR / "css"

CANDIDATE_EXTS = (".png", ".jpg", ".jpeg")

LOSSY_QUALITY = 85
LOSSLESS_QUALITY = 100  # compression effort when lossless=True, not visual quality
WEBP_METHOD = 6


@dataclass
class Stats:
    examined: int = 0
    converted: int = 0
    kept_original: int = 0
    errors: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    error_details: list[tuple[Path, str]] = field(default_factory=list)


def find_candidates() -> list[Path]:
    files = [
        p
        for p in ASSETS_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in CANDIDATE_EXTS
    ]
    return sorted(files)


def _normalize_for_webp(im: Image.Image) -> Image.Image:
    """Return a Pillow image in a mode WEBP can save, preserving alpha."""
    mode = im.mode
    if mode == "P":
        return im.convert("RGBA") if "transparency" in im.info else im.convert("RGB")
    if mode == "LA":
        return im.convert("RGBA")
    if mode == "1":
        return im.convert("L")
    if mode == "CMYK":
        return im.convert("RGB")
    if mode in ("RGB", "RGBA", "L"):
        return im
    # Anything else unexpected: fall back to RGBA if it carries alpha info,
    # otherwise RGB.
    return im.convert("RGBA") if "A" in mode else im.convert("RGB")


def _encode(img: Image.Image, *, lossless: bool) -> bytes:
    buf = io.BytesIO()
    kwargs = {"format": "WEBP", "method": WEBP_METHOD}
    if lossless:
        kwargs["lossless"] = True
        kwargs["quality"] = LOSSLESS_QUALITY
    else:
        kwargs["quality"] = LOSSY_QUALITY
    img.save(buf, **kwargs)
    return buf.getvalue()


def convert_one(path: Path) -> tuple[Optional[bytes], int, Optional[str]]:
    """Try to encode `path` to WebP.

    Returns (best_webp_bytes_or_None, original_size, error_or_None).
    best_webp_bytes is None only on error; the caller decides whether to
    adopt it based on size.
    """
    orig_size = path.stat().st_size
    try:
        with Image.open(path) as im:
            im.load()
            detected_format = im.format
            work = _normalize_for_webp(im)

            variants: list[bytes] = []
            variants.append(_encode(work, lossless=False))
            if detected_format == "PNG":
                variants.append(_encode(work, lossless=True))

            best = min(variants, key=len)
            return best, orig_size, None
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return None, orig_size, str(exc)


def root_relative(path: Path) -> str:
    return "/" + path.relative_to(PUBLIC_DIR).as_posix()


def process_assets(files: list[Path], stats: Stats, dry_run: bool) -> dict[str, str]:
    """Convert candidates in place (unless dry_run). Returns mapping of
    old root-relative path -> new root-relative path for adopted conversions."""
    mapping: dict[str, str] = {}
    for path in files:
        stats.examined += 1
        best, orig_size, error = convert_one(path)
        if error is not None:
            stats.errors += 1
            stats.error_details.append((path, error))
            continue

        assert best is not None
        webp_path = path.with_suffix(".webp")

        if len(best) < orig_size:
            stats.converted += 1
            stats.bytes_before += orig_size
            stats.bytes_after += len(best)
            old_rel = root_relative(path)
            new_rel = root_relative(webp_path)
            mapping[old_rel] = new_rel
            # Some pages reference assets by percent-encoded paths (Greek
            # letters, parentheses, commas in thumb names) while the files on
            # disk carry the decoded names - map the encoded spelling too so
            # those references are rewritten as well.
            old_quoted = urllib.parse.quote(old_rel, safe="/")
            if old_quoted != old_rel:
                mapping[old_quoted] = urllib.parse.quote(new_rel, safe="/")
            if not dry_run:
                webp_path.write_bytes(best)
                path.unlink()
        else:
            stats.kept_original += 1
            stats.bytes_before += orig_size
            stats.bytes_after += orig_size
            # In case a stray .webp got left behind by an interrupted run,
            # make sure it doesn't linger unreferenced.
            if webp_path.exists() and not dry_run:
                webp_path.unlink()

    return mapping


def rewrite_references(mapping: dict[str, str], dry_run: bool) -> tuple[int, int, int]:
    """Rewrite every mapped old path to its new path across HTML and CSS.

    Returns (html_files_rewritten, css_files_rewritten, total_replacements).
    """
    if not mapping:
        return 0, 0, 0

    html_files = sorted(PUBLIC_DIR.glob("**/index.html")) + [
        p for p in [PUBLIC_DIR / "404.html"] if p.exists()
    ]
    css_files = sorted(CSS_DIR.glob("*.css")) if CSS_DIR.is_dir() else []

    html_rewritten = 0
    css_rewritten = 0
    total_replacements = 0

    for path in html_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        original_text = text
        file_replacements = 0
        for old, new in mapping.items():
            if old in text:
                count = text.count(old)
                text = text.replace(old, new)
                file_replacements += count
        if text != original_text:
            html_rewritten += 1
            total_replacements += file_replacements
            if not dry_run:
                path.write_text(text, encoding="utf-8")

    for path in css_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        original_text = text
        file_replacements = 0
        for old, new in mapping.items():
            if old in text:
                count = text.count(old)
                text = text.replace(old, new)
                file_replacements += count
        if text != original_text:
            css_rewritten += 1
            total_replacements += file_replacements
            if not dry_run:
                path.write_text(text, encoding="utf-8")

    return html_rewritten, css_rewritten, total_replacements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report conversions/savings without writing anything")
    parser.add_argument("--limit", type=int, default=None, help="only examine the first N candidate files")
    args = parser.parse_args()

    files = find_candidates()
    if args.limit is not None:
        files = files[: args.limit]

    stats = Stats()
    mapping = process_assets(files, stats, dry_run=args.dry_run)
    html_rewritten, css_rewritten, references_replaced = rewrite_references(mapping, dry_run=args.dry_run)

    saved_pct = 0.0
    if stats.bytes_before:
        saved_pct = (1 - (stats.bytes_after / stats.bytes_before)) * 100

    mode_label = "DRY RUN" if args.dry_run else "convert-webp summary"
    print(mode_label, file=sys.stderr)
    print(f"  files examined:          {stats.examined}", file=sys.stderr)
    print(f"  converted + adopted:     {stats.converted}", file=sys.stderr)
    print(f"  kept original (not smaller): {stats.kept_original}", file=sys.stderr)
    print(f"  errors:                  {stats.errors}", file=sys.stderr)
    print(
        f"  bytes before/after:      {stats.bytes_before:,} / {stats.bytes_after:,} "
        f"({saved_pct:.1f}% saved)",
        file=sys.stderr,
    )
    print(f"  html files rewritten:    {html_rewritten}", file=sys.stderr)
    print(f"  css files rewritten:     {css_rewritten}", file=sys.stderr)
    print(f"  references replaced:     {references_replaced}", file=sys.stderr)

    if stats.error_details:
        print(f"  errors ({len(stats.error_details)}):", file=sys.stderr)
        for path, reason in stats.error_details:
            print(f"    {root_relative(path)}  ({reason})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
