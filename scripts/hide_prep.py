#!/usr/bin/env python3
"""Keep preparation originals in git, outside the deployed static output."""
from pathlib import Path
from urllib.parse import unquote, urlsplit, urljoin
import argparse
import html
import json
import re
import shutil

HERE = Path(__file__).resolve()
# Resolve by configuration, so a cloned repository may have any directory name.
PW = (HERE.parent.parent / 'hide-prep-config.json').is_file()
ROOT = HERE.parents[1] if PW else HERE.parents[2]
DIST = ROOT / ('public' if PW else 'archive/dist')
HIDDEN = ROOT / 'hidden'
CFG = json.loads((ROOT / ('hide-prep-config.json' if PW else 'archive/archive-config.json')).read_text())
ROUTES = CFG['hiddenRoutes' if PW else 'hiddenPostRoutes']
PROTECTED = {'/archive-about/', '/wiki/User:Josikins/'} if PW else set()
POST_IDS = {r.split('/')[2] for r in ROUTES} if not PW else set()

def identity(value):
    value = html.unescape(value)
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value: break
        value = decoded
    path = urlsplit(value).path
    # Original-origin and Wayback source links must not bypass the policy.
    for prefix in ('/wiki/', '/post/', '/archive-query/'):
        if prefix in path: path = path[path.index(prefix):]; break
    if path.endswith('/index.html'): path = path[:-10]
    return '/' + path.strip('/').casefold() + '/'

IDENTITIES = {identity(r) for r in ROUTES}
def is_hidden(url, base='/'):
    path = identity(urljoin(base, html.unescape(url)))
    return path in IDENTITIES or bool(POST_IDS and re.match(r'/post/(' + '|'.join(POST_IDS) + r')(?:/|$)', path))

def plain(text):
    return html.unescape(re.sub(r'<[^>]+>', ' ', text)).lower()

DIV = re.compile(r'</?div\b[^>]*>', re.I)
def div_end(text, start):
    depth = 0
    for m in DIV.finditer(text, start):
        depth += -1 if m.group().lower().startswith('</') else 1
        if depth == 0: return m.end()
    raise ValueError('Unbalanced archive div at ' + str(start))

POST = re.compile(r'''<div\b(?=[^>]*\bclass=["'][^"']*\bpost\b)[^>]*>''', re.I)
METADATA = re.compile(r'''<div\b(?=[^>]*\bclass=["'][^"']*\bdate_and_notes\b)[^>]*>''', re.I)
URL_ATTR = re.compile(r'''\s(?:href|action|src|data-archive-original)\s*=\s*(["'])(.*?)\1''', re.I | re.S)
TAG = re.compile(r'<[a-z][^>]*>', re.I)

def redact(text, route='/'):
    if not PW:
        # Remove entire reproduced articles from every pagination/tag/archive page.
        for m in reversed(list(POST.finditer(text))):
            end = div_end(text, m.start())
            post = text[m.start():end]
            metadata = METADATA.search(post)
            if metadata:
                block = post[metadata.start():div_end(post, metadata.start())]
                if any(is_hidden(a.group(2)) for a in URL_ATTR.finditer(block)):
                    text = text[:m.start()] + text[end:]
    if PW:
        sections = CFG.get('redactions', {}).get(route, {}).get('sections', [])
        for label in sections:
            headings = list(re.finditer(r'<h([2-6])\b[^>]*>.*?</h\1>', text, re.I | re.S))
            for i, m in reversed(list(enumerate(headings))):
                if plain(m.group()).strip() != label.lower(): continue
                end = next((n.start() for n in headings[i+1:] if int(n.group(1)) <= int(m.group(1))), None)
                if end is None: raise ValueError('Missing section boundary for ' + route)
                text = text[:m.start()] + text[end:]
    markers = CFG.get('paragraphMarkers' if PW else 'preparationParagraphMarkers', [])
    def paragraph(m):
        return '' if any(marker in plain(m.group()) for marker in markers) else m.group()
    text = re.sub(r'[ \t]*<p\b[^>]*>.*?</p>[ \t]*', paragraph, text, flags=re.I | re.S)
    # A PW image caption includes an actual crack-making procedure.
    if PW:
        captions = list(re.finditer(r'''<div\b(?=[^>]*\bclass=["']thumbcaption["'])[^>]*>''', text, re.I))
        for m in reversed(captions):
            end = div_end(text, m.start())
            if any(marker in plain(text[m.start():end]) for marker in markers):
                text = text[:m.start()] + text[end:]
    return text

def sanitize(text, route='/'):
    text = redact(text, route)
    def tag(m):
        value = m.group()
        return URL_ATTR.sub(lambda a: '' if is_hidden(a.group(2), '/' if PW else route) else a.group(), value)
    text = TAG.sub(tag, text)
    def refresh(m):
        urls = re.findall(r"url\s*=\s*([^\"'<>]+)", html.unescape(m.group()), re.I)
        return '' if any(is_hidden(u.strip(), route) for u in urls) else m.group()
    text = re.sub(r'<meta\b[^>]*http-equiv=["\']refresh["\'][^>]*>', refresh, text, flags=re.I)
    for section in CFG.get('redactions', {}).get(route, {}).get('sections', []):
        text = re.sub(r"\s+href=([\"'])#" + re.escape(section) + r"\1", '', text, flags=re.I)
    return text

def filter_json(value):
    if isinstance(value, str): return None if is_hidden(value) else value
    if isinstance(value, list):
        if any(isinstance(v,str) and is_hidden(v) for v in value): return None
        return [filtered for v in value if (filtered := filter_json(v)) is not None]
    if isinstance(value, dict):
        if any(isinstance(v,str) and is_hidden(v) for v in value.values()): return None
        return {k:filtered for k,v in value.items() if (filtered := filter_json(v)) is not None}
    return value

def apply():
    moved = changed = 0
    for route in ROUTES:
        source = DIST / route.strip('/') / 'index.html'
        target = HIDDEN / 'pages' / route.strip('/') / 'index.html'
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists(): shutil.copy2(source, target)
            source.unlink(); moved += 1
    for page in DIST.rglob('*.html'):
        route = '/' + page.parent.relative_to(DIST).as_posix().strip('./') + '/'
        if route == '//': route = '/'
        if route in PROTECTED: continue
        before = page.read_text(errors='replace')
        redacted = redact(before, route)
        if redacted != before:
            original = HIDDEN / 'originals' / page.relative_to(DIST)
            original.parent.mkdir(parents=True, exist_ok=True)
            if not original.exists(): shutil.copy2(page, original)
        after = sanitize(before, route)
        if after != before: page.write_text(after); changed += 1
    for file in DIST.rglob('*.json'):
        before = json.loads(file.read_text())
        after = filter_json(before)
        if before != after:
            compact = len(file.read_text().splitlines()) <= 1
            file.write_text(json.dumps(after, ensure_ascii=False, indent=None if compact else 2)+'\n')
    print(f'hiding: {moved} pages removed from output; {changed} public HTML files sanitized')

def check(require_originals=True):
    errors = []; pages = links = 0
    for route in ROUTES:
        if (DIST / route.strip('/') / 'index.html').exists(): errors.append('public hidden route: '+route)
        if require_originals and not (HIDDEN / 'pages' / route.strip('/') / 'index.html').is_file():
            errors.append('missing original: '+route)
    for page in DIST.rglob('*.html'):
        pages += 1
        route = '/' + page.parent.relative_to(DIST).as_posix() + '/'
        text = page.read_text(errors='replace')
        for attr in URL_ATTR.finditer(text):
            links += 1
            if is_hidden(attr.group(2), '/' if PW else route): errors.append(f'hidden link: {page.relative_to(DIST)} -> {attr.group(2)}')
        if redact(text, route) != text: errors.append('preparation content remains: '+str(page.relative_to(DIST)))
    for file in DIST.rglob('*.json'):
        value = json.loads(file.read_text())
        if filter_json(value) != value: errors.append('hidden JSON route: '+str(file.relative_to(DIST)))
    if errors: raise SystemExit('\n'.join(errors))
    print(f'hiding check: PASS — {len(ROUTES)} absent routes, {pages} HTML pages, {links} URL attributes, zero hidden links')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--build', action='store_true',
                        help='Check publication safety without requiring originals excluded by .vercelignore')
    args = parser.parse_args()
    if not args.check: apply()
    # Originals stay in git, but Vercel removes hidden/ before running the build.
    # Publication checks always run; preservation checks remain strict locally.
    check(require_originals=not args.build)
