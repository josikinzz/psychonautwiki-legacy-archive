# AGENTS.md

## Scope
Applies to generated archive pages and vendored assets under `public/`.

## Hard Invariants
- Preserve archived content and the `20171231235959` capture cutoff.
- Keep wiki links root-relative and retain `noindex` metadata.
- Do not manually redesign desktop Vector chrome; mobile compatibility must follow [.impeccable.md](../.impeccable.md).

## Editing Rules
- Prefer the corresponding `scripts/` pipeline step for systematic changes. Direct edits are appropriate only for deliberately maintained shared assets such as `assets/archive.js` and `assets/mobile.css`.
- After renaming or rewriting pages/assets, run `npm run archive:check` from the repository root.
