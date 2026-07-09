#!/usr/bin/env python3
"""Rebuild Minerva (mobile) skinned PsychonautWiki archive pages as Vector
(desktop) skinned pages, so the whole archive shares identical chrome.

public/wiki/AL-LAD/index.html is used as the Vector chrome TEMPLATE. For each
Minerva page found under --root, this script:

  - detects the Minerva page's own title (from its <h1 id="section_0">),
    dbkey (from its inline `"wgPageName":"..."` mw.config blob), html
    lang/dir, archive-banner div (with the page's own capture URL), and
    main article content (from #mw-content-text if present, else the whole
    of #bodyContent) using a small balanced-tag scanner (see BalancedFinder
    below) rather than naive regex/string slicing, since not all ~26
    Minerva captures share the exact same markup shape (two different
    Minerva skin versions are present in this archive, see
    Preparation_of_changa vs. Serotonin/Melatonin for an example of the
    two shapes).
  - splices those per-page pieces into a fresh copy of the Vector template,
    replacing the template's own AL-LAD title/content/banner/body-class/
    html-lang, and rewriting incidental "AL-LAD" tokens that remain in the
    template chrome (nav tab hrefs, RDF link, etc.) to the new page's own
    title, best-effort.

The template's own <script> blocks (mw.config, mw.loader, RLQ, ...) are left
untouched -- a later pipeline step (scripts/enhance-pages.py) strips all of
that dead MediaWiki JS anyway, so there is no reason to rewrite it here.

Usage:
    python3 scripts/standardize-skin.py --out /tmp/skin-test
    python3 scripts/standardize-skin.py --in-place
    python3 scripts/standardize-skin.py --out /tmp/skin-test --limit 5
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "public"
DEFAULT_TEMPLATE = ROOT / "public" / "wiki" / "AL-LAD" / "index.html"

MINERVA_MARKER = "skins.minerva"

SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# Balanced-tag element finder
#
# We cannot rely on plain regex/string-splitting to find "the div with this
# id and its matching end tag" because these are hand-authored MediaWiki
# outputs of varying vintages with arbitrarily deep nesting inside. Instead
# we use html.parser.HTMLParser (which tokenizes real-world HTML leniently)
# and track *only* same-tag-name open/close depth after the target element
# is found. This is immune to unrelated mismatched tags elsewhere in the
# document (e.g. a stray unclosed <p>), since we never count anything but
# the target tag name once tracking begins.
# ---------------------------------------------------------------------------
class BalancedFinder(HTMLParser):
    def __init__(self, source: str, predicate):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.predicate = predicate
        self._line_offsets = [0]
        for i, ch in enumerate(source):
            if ch == "\n":
                self._line_offsets.append(i + 1)
        self.target_tag = None
        self.depth = 0
        self._outer_start = None
        self._inner_start = None
        self.result = None  # dict(outer_start, outer_end, inner_start, inner_end)

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if self.result is not None:
            return
        start = self._offset()
        if self.target_tag is None:
            if self.predicate(tag, dict(attrs)):
                raw = self.get_starttag_text() or ""
                self.target_tag = tag
                self.depth = 1
                self._outer_start = start
                self._inner_start = start + len(raw)
            return
        if tag == self.target_tag:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        # Self-closing tag, e.g. <div ... />. Treat as a leaf: if it's our
        # target, it has empty inner content; otherwise it never affects
        # depth (open+close cancel out), so no bookkeeping needed here.
        if self.result is not None or self.target_tag is not None:
            return
        if self.predicate(tag, dict(attrs)):
            start = self._offset()
            raw = self.get_starttag_text() or ""
            end = start + len(raw)
            self.result = {
                "outer_start": start,
                "outer_end": end,
                "inner_start": end,
                "inner_end": end,
            }

    def handle_endtag(self, tag):
        if self.result is not None or self.target_tag is None:
            return
        if tag != self.target_tag:
            return
        self.depth -= 1
        if self.depth != 0:
            return
        pos = self._offset()
        gt = self.source.find(">", pos)
        if gt == -1:
            gt = pos + len(tag) + 2  # best-effort fallback
        outer_end = gt + 1
        self.result = {
            "outer_start": self._outer_start,
            "outer_end": outer_end,
            "inner_start": self._inner_start,
            "inner_end": pos,
        }


def find_element(source: str, predicate):
    """Returns dict(outer_start, outer_end, inner_start, inner_end) for the
    first element matching predicate(tag, attrs_dict), or None if not found
    or never closed."""
    parser = BalancedFinder(source, predicate)
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        pass
    return parser.result


def outer_html(source: str, el: dict) -> str:
    return source[el["outer_start"]:el["outer_end"]]


def inner_html(source: str, el: dict) -> str:
    return source[el["inner_start"]:el["inner_end"]]


def replace_element(source: str, el: dict, replacement: str) -> str:
    return source[:el["outer_start"]] + replacement + source[el["outer_end"]:]


def replace_inner(source: str, el: dict, replacement: str) -> str:
    return source[:el["inner_start"]] + replacement + source[el["inner_end"]:]


def has_id(attrs: dict, value: str) -> bool:
    return attrs.get("id") == value


def has_class(attrs: dict, value: str) -> bool:
    classes = (attrs.get("class") or "").split()
    return value in classes


# ---------------------------------------------------------------------------
# Per-page data extraction (from a Minerva source page)
# ---------------------------------------------------------------------------
class ExtractionError(Exception):
    pass


class MinervaPage:
    def __init__(self, path: Path, html_text: str):
        self.path = path
        self.html_text = html_text

    def _json_string(self, key: str) -> str | None:
        m = re.search(r'"%s"\s*:\s*"((?:\\.|[^"\\])*)"' % re.escape(key), self.html_text)
        if not m:
            return None
        try:
            return json.loads('"' + m.group(1) + '"')
        except (json.JSONDecodeError, ValueError):
            return m.group(1)

    def dbkey(self) -> str:
        """The MediaWiki dbkey (underscored, unencoded) for this page, used
        for the Vector body class token and for building self-referential
        URLs. Prefers the canonical `"wgPageName":"..."` from the inline
        mw.config blob (matches how the rest of this archive's Vector pages
        already derive their own page-<dbkey> class, including cases where
        it differs from the on-disk folder name after a MediaWiki title
        redirect/normalization). Some captures in this archive have already
        had their mw.config script stripped by a later pipeline pass (or
        simply never captured one), so this falls back to the page's own
        archive-banner capture URL (always present, see banner_div()) and
        finally to the <h1> title text."""
        val = self._json_string("wgPageName")
        if val:
            return val
        m = re.search(
            r"https://web\.archive\.org/web/\d+id_/https://psychonautwiki\.org/wiki/([^\"<]+)",
            self.html_text,
        )
        if m:
            from urllib.parse import unquote

            return unquote(m.group(1))
        return self.h1_title_text().replace(" ", "_")

    def html_lang_dir(self) -> tuple[str, str]:
        m = re.search(r"<html\b[^>]*>", self.html_text, re.IGNORECASE)
        if not m:
            return "en", "ltr"
        tag = m.group(0)
        lang_m = re.search(r'lang="([^"]*)"', tag)
        dir_m = re.search(r'dir="([^"]*)"', tag)
        lang = lang_m.group(1) if lang_m else "en"
        dir_ = dir_m.group(1) if dir_m else "ltr"
        return lang, dir_

    def title_tag(self) -> str:
        m = re.search(r"<title>.*?</title>", self.html_text, re.IGNORECASE | re.DOTALL)
        if not m:
            raise ExtractionError("no <title> tag found")
        return m.group(0)

    def h1_title_text(self) -> str:
        el = find_element(
            self.html_text,
            lambda tag, attrs: tag == "h1" and has_id(attrs, "section_0"),
        )
        if el is None:
            # Not a Minerva capture (no id="section_0" heading) -- fall back
            # to the Vector shape's own <h1 class="firstheading">, used by
            # e.g. the --vector-pages rechrome path where the *source* page
            # is already Vector-skinned (just foreign-language chrome / a
            # missing local CSS bundle) rather than Minerva.
            el = find_element(
                self.html_text,
                lambda tag, attrs: tag == "h1" and has_class(attrs, "firstheading"),
            )
        if el is None:
            raise ExtractionError(
                'no <h1 id="section_0"> or <h1 class="firstheading"> found '
                "(unrecognized heading markup)"
            )
        raw = inner_html(self.html_text, el)
        text = re.sub(r"<[^>]+>", "", raw).strip()
        return html.unescape(text)

    def banner_div(self) -> str:
        el = find_element(
            self.html_text,
            lambda tag, attrs: tag == "div" and has_class(attrs, "josiekins-archive-banner"),
        )
        if el is None:
            raise ExtractionError("no josiekins-archive-banner div found")
        return outer_html(self.html_text, el)

    def catlinks_div(self) -> str | None:
        el = find_element(
            self.html_text,
            lambda tag, attrs: tag == "div" and has_id(attrs, "catlinks"),
        )
        if el is None:
            return None
        return outer_html(self.html_text, el)

    def article_content(self) -> str:
        el = find_element(
            self.html_text,
            lambda tag, attrs: tag == "div" and has_id(attrs, "mw-content-text"),
        )
        if el is not None:
            return inner_html(self.html_text, el)
        el = find_element(
            self.html_text,
            lambda tag, attrs: tag == "div" and has_id(attrs, "bodyContent"),
        )
        if el is not None:
            return inner_html(self.html_text, el)
        raise ExtractionError(
            "no #mw-content-text or #bodyContent container found "
            "(unrecognized Minerva content markup)"
        )


# ---------------------------------------------------------------------------
# Template transformation
# ---------------------------------------------------------------------------
def rewrite_chrome_tokens(template_html: str, old_dbkey: str, new_dbkey: str, new_display_title: str) -> str:
    """Best-effort rewrite of leftover template-specific "AL-LAD" tokens in
    the chrome (nav tab hrefs, RDF link, etc.) to the new page. Only touches
    text outside <script> blocks, so the (soon-to-be-discarded) mw.config
    JSON blobs are left alone. Links that can't be sensibly rewritten (e.g.
    Special:Browse/AL-2DLAD, an SMW hyphen-escaped id) simply don't contain
    the literal old_dbkey substring and are left untouched, per spec.

    `safe="/"` so a dbkey containing a real path separator (e.g. the
    subpage "Kratom_resin/extraction_tek") round-trips into path-style
    template hrefs (href="/wiki/AL-LAD/" etc.) as a real "/" rather than an
    encoded "%2F" -- matching how this archive's other, already-converted
    subpages (e.g. 1P-LSD/Summary) link to themselves. This is a no-op for
    every plain (slash-free) dbkey, i.e. every page this script has
    previously converted."""
    new_url_token = quote(new_dbkey, safe="/")
    display_attr = html.escape(new_display_title, quote=True)

    def transform_non_script(chunk: str) -> str:
        chunk = chunk.replace('title="%s"' % old_dbkey, 'title="%s"' % display_attr)
        chunk = chunk.replace(old_dbkey, new_url_token)
        return chunk

    parts = SCRIPT_BLOCK_RE.split(template_html)
    scripts = SCRIPT_BLOCK_RE.findall(template_html)
    out = []
    for i, chunk in enumerate(parts):
        out.append(transform_non_script(chunk))
        if i < len(scripts):
            out.append(scripts[i])
    return "".join(out)


def build_page(
    template_path: Path,
    template_html: str,
    minerva: MinervaPage,
    force_lang_dir: tuple[str, str] | None = None,
) -> str:
    old_dbkey = MinervaPage(template_path, template_html).dbkey()
    new_dbkey = minerva.dbkey()
    display_title = minerva.h1_title_text()
    # force_lang_dir lets callers (e.g. --vector-pages) override a source
    # page's own <html lang="..."> instead of copying it verbatim -- used
    # when the source is a foreign-language chrome capture (lang="cs" /
    # "pl" / "id" / "zh-CN") that must come out as English lang="en-GB"
    # regardless of what the source page's own <html> tag says.
    lang, dir_ = force_lang_dir if force_lang_dir is not None else minerva.html_lang_dir()
    title_tag = minerva.title_tag()
    banner = minerva.banner_div()
    content = minerva.article_content()
    minerva_catlinks = minerva.catlinks_div()

    out = rewrite_chrome_tokens(template_html, old_dbkey, new_dbkey, display_title)

    # <html lang="..." dir="..." class="client-nojs">
    # (repl is a callable so % / backslash chars in lang/dir can never be
    # misread as regex backreferences)
    out, n = re.subn(
        r'<html lang="[^"]*" dir="[^"]*" class="client-nojs">',
        lambda _m: '<html lang="%s" dir="%s" class="client-nojs">' % (lang, dir_),
        out,
        count=1,
    )
    if n != 1:
        raise ExtractionError("template <html> tag shape changed unexpectedly")

    # <title>...</title>
    out, n = re.subn(r"<title>.*?</title>", lambda _m: title_tag, out, count=1, flags=re.IGNORECASE | re.DOTALL)
    if n != 1:
        raise ExtractionError("template <title> tag shape changed unexpectedly")

    # <h1 class="firstheading" dir="auto">AL-LAD</h1>
    escaped_title = html.escape(display_title)
    out, n = re.subn(
        r'(<h1 class="firstheading" dir="auto">)[^<]*(</h1>)',
        lambda m: m.group(1) + escaped_title + m.group(2),
        out,
        count=1,
    )
    if n != 1:
        raise ExtractionError('template h1.firstheading shape changed unexpectedly')

    # <body class="...">
    # MediaWiki's Sanitizer::escapeClass turns "/" into "_" for the
    # page-<dbkey> body class (confirmed against this archive's own already
    # -converted subpages, e.g. page-1P-LSD_Summary for the real page
    # "1P-LSD/Summary") even though the real dbkey -- used in hrefs, the
    # <title>, and <h1> -- keeps the "/". Sanitize only for this one class
    # token; a no-op for every slash-free dbkey.
    ui_dir = "rtl" if dir_ == "rtl" else "ltr"
    body_dbkey = new_dbkey.replace("/", "_")
    new_body_class = "mediawiki %s sitedir-ltr ns-0 ns-subject page-%s skin-vector action-view" % (
        ui_dir,
        body_dbkey,
    )
    out, n = re.subn(
        r'(<body class=")[^"]*(")',
        lambda m: m.group(1) + new_body_class + m.group(2),
        out,
        count=1,
    )
    if n != 1:
        raise ExtractionError("template <body class=...> shape changed unexpectedly")

    # banner div (do this after the body-class subn above, which is
    # anchored on <body class="...">, distinct from the banner markup).
    banner_el = find_element(
        out, lambda tag, attrs: tag == "div" and has_class(attrs, "josiekins-archive-banner")
    )
    if banner_el is None:
        raise ExtractionError("template banner div not found")
    out = replace_element(out, banner_el, banner)

    # main content: swap the inner html of #mw-content-text
    content_el = find_element(out, lambda tag, attrs: tag == "div" and has_id(attrs, "mw-content-text"))
    if content_el is None:
        raise ExtractionError("template #mw-content-text not found")
    out = replace_inner(out, content_el, content)

    # catlinks: carry the Minerva page's own catlinks verbatim if it has
    # one, otherwise drop the template's (AL-LAD-specific) catlinks div.
    catlinks_el = find_element(out, lambda tag, attrs: tag == "div" and has_id(attrs, "catlinks"))
    if catlinks_el is not None:
        if minerva_catlinks is not None:
            out = replace_element(out, catlinks_el, minerva_catlinks)
        else:
            out = out[: catlinks_el["outer_start"]] + out[catlinks_el["outer_end"] :]

    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def find_minerva_pages(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("index.html")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if MINERVA_MARKER in text:
            found.append(path)
    return found


def rechrome_vector_pages(root: Path, template_path: Path, template_html: str, page_names: list[str]) -> int:
    """--vector-pages mode: rebuild already-Vector-shaped pages that carry
    foreign-language chrome (lang="cs"/"pl"/"id"/"zh-CN" on <html>) and/or
    lack the standard local CSS bundle, onto the current AL-LAD template --
    same splice as the Minerva path (title/h1/banner/body-class/content),
    but forcing English lang="en-GB" chrome instead of copying the source
    page's own (wrong) <html lang>. See MinervaPage.h1_title_text's Vector
    fallback for how the source page's own title is located."""
    converted = 0
    failures: list[tuple[str, str]] = []

    for name in page_names:
        path = root / "wiki" / name / "index.html"
        try:
            if not path.is_file():
                raise ExtractionError("no such file: %s" % path)
            source_html = path.read_text(encoding="utf-8")
            source = MinervaPage(path, source_html)
            result_html = build_page(template_path, template_html, source, force_lang_dir=("en-GB", "ltr"))
        except ExtractionError as e:
            failures.append((name, str(e)))
            continue
        except Exception as e:  # defensive: never write a half-built file
            failures.append((name, "unexpected error: %r" % (e,)))
            continue

        path.write_text(result_html, encoding="utf-8")
        converted += 1
        print("  OK   %s" % name)

    for name, reason in failures:
        print("  FAIL %s: %s" % (name, reason))

    print("Vector-pages requested: %d" % len(page_names))
    print("Converted: %d" % converted)
    print("Failed: %d" % len(failures))
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Root dir to scan for Minerva pages (default: public/)")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Vector template page (default: public/wiki/AL-LAD/index.html)")
    parser.add_argument("--out", default=None, help="Write converted pages under this dir (mirrors <root> layout) instead of editing in place")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the Minerva pages in --root directly")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N detected pages")
    parser.add_argument(
        "--vector-pages",
        nargs="+",
        default=None,
        metavar="PAGE",
        help=(
            "Instead of scanning for Minerva pages, rebuild these already-Vector-"
            "shaped page(s) (given as their public/wiki/ dbkey, e.g. NM-2-AI or "
            "Kratom_resin/extraction_tek) from the current AL-LAD template, "
            "forcing English lang=\"en-GB\" chrome. Always writes in place."
        ),
    )
    return parser.parse_args()


def convert_minerva_pages(
    root: Path,
    template_path: Path,
    template_html: str,
    *,
    in_place: bool,
    out: str | None,
    limit: int | None,
) -> int:
    pages = find_minerva_pages(root)
    detected = len(pages)
    if limit is not None:
        pages = pages[:limit]

    out_root = Path(out).resolve() if out else None
    converted = 0
    failures: list[tuple[Path, str]] = []

    for path in pages:
        try:
            minerva_html = path.read_text(encoding="utf-8")
            minerva = MinervaPage(path, minerva_html)
            result_html = build_page(template_path, template_html, minerva)
        except ExtractionError as e:
            failures.append((path, str(e)))
            continue
        except Exception as e:  # defensive: never write a half-built file
            failures.append((path, "unexpected error: %r" % (e,)))
            continue

        if in_place:
            dest = path
        else:
            rel = path.relative_to(root)
            dest = out_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(result_html, encoding="utf-8")
        converted += 1

    print("Minerva pages detected: %d" % detected)
    if limit is not None:
        print("Processed (--limit %d): %d" % (limit, len(pages)))
    print("Converted: %d" % converted)
    print("Failed: %d" % len(failures))
    for path, reason in failures:
        rel = path.relative_to(root) if root in path.parents or path == root else path
        print("  FAIL %s: %s" % (rel, reason))

    return 1 if failures else 0


def main() -> int:
    args = parse_args()

    root = Path(args.root).resolve()
    template_path = Path(args.template).resolve()

    if not template_path.is_file():
        print("error: template not found: %s" % template_path, file=sys.stderr)
        return 2
    template_html = template_path.read_text(encoding="utf-8")

    if args.vector_pages is not None:
        if args.out or args.in_place:
            print("error: --vector-pages is exclusive with --out/--in-place (always writes in place)", file=sys.stderr)
            return 2
        return rechrome_vector_pages(root, template_path, template_html, args.vector_pages)

    if not args.in_place and not args.out:
        print("error: specify --out DIR or --in-place", file=sys.stderr)
        return 2
    if args.in_place and args.out:
        print("error: --out and --in-place are mutually exclusive", file=sys.stderr)
        return 2

    return convert_minerva_pages(
        root,
        template_path,
        template_html,
        in_place=args.in_place,
        out=args.out,
        limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
