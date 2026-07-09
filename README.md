# PsychonautWiki Archive (through 2017)

An open-source preservation scrape of PsychonautWiki as it existed during Josie Kins's tenure, before control of the site moved away from her. It preserves the public site state through the end of 2017 using Internet Archive captures; no page capture later than `20171231235959` is included (the latest archived page capture is `20171207012416`).

The purpose is historical preservation: to keep this period of the website openly accessible and inspectable rather than allowing its public record to disappear.

Browse the archive at [psychonautwiki.josiekins.xyz](https://psychonautwiki.josiekins.xyz).

The generated archive lives in `public/` so Vercel can serve it as a static site root. Internal wiki links are root-relative (`/wiki/...`), so it is deployed on its own host. The preservation build vendors assets and removes dead dependencies for snappy loading, and adds a custom mobile view for modern browsers. Otherwise, the archived content and historical desktop presentation have been kept the same.

## Contents

- `public/` - generated static archive pages, `manifest.json`, and `assets/` (locally vendored CSS/images/icons/fonts plus shared client-side search and mobile compatibility assets)
- `public/404.html` - custom not-archived page (Vercel serves it automatically for missing paths on static deploys; the local `npm run serve` dev server uses its own plain 404)
- `scripts/mirror-psychonautwiki-archive.py` - repeatable Wayback/CDX mirror generator
- `scripts/standardize-skin.py` - rebuilds mobile-skin (Minerva) and foreign-language captures on the standard English Vector chrome (`--in-place`, or `--vector-pages PAGE ...` for Vector-structure sources)
- `scripts/vendor-assets.py` - downloads all remote CSS/image assets from Wayback into `public/assets/` (resumable) and rewrites pages to use them; localizes `url()` refs inside CSS
- `scripts/normalize-asset-extensions.py` - renames assets whose byte format does not match their filename extension and rewrites local HTML/CSS references
- `scripts/enhance-pages.py` - strips dead MediaWiki JS/head links, neutralizes red links, and injects the shared search/random and mobile compatibility layers; `--build-index` regenerates `public/assets/search-index.json`
- `scripts/convert-webp.py` - converts vendored JPG/PNG assets to WebP where smaller and rewrites references
- `scripts/check-psychonautwiki-archive-links.py` - manifest and local-link checker
- `vercel.json` - static Vercel deployment config

After a fresh `archive:build`, run the post-processing pipeline in this order: `archive:standardize` → `archive:vendor` → `archive:normalize-assets` → `archive:enhance` → `archive:check`.

## Commands

```bash
npm run archive:check
npm run serve
```

Regenerate from Internet Archive:

```bash
npm run archive:build
```

## Archive Ledger

- Source: Internet Archive CDX/API captures of `psychonautwiki.org/wiki/*`
- Cutoff: `20171231235959`
- Pages: see `public/manifest.json`
- Robots: generated pages include `noindex`

No license is granted for the archived page contents by this repository. This repo exists as a historical preservation archive.
