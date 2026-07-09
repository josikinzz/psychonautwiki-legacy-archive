# AGENTS.md

## Start Here
- Read [README.md](README.md) for the archive pipeline, deployment context, and command order.
- For frontend or mobile changes, follow [.impeccable.md](.impeccable.md).

## Hard Invariants
- This is a historical static mirror: do not introduce captures later than `20171231235959`.
- Keep internal archive links root-relative (`/wiki/...`) and deploy the archive on its own host.
- Preserve the desktop Vector presentation; mobile work must remain a reversible shared compatibility layer.

## Common Commands
- `npm run archive:check` validates the manifest and local wiki links.
- `npm run serve` serves `public/` on port 8765.
- The regeneration and post-processing commands are defined in `package.json`; follow the order documented in the README.

## Editing Rules
- Treat `public/` as generated archive output. Prefer updating the responsible script in `scripts/` and rerunning the relevant pipeline step.
- Preserve the `noindex` archive behavior and the Vercel static output directory (`public/`).
- Asset transformations rewrite archive references; run the link checker after changes that rename, remove, or rewrite assets/pages.

## Validation
- Run `npm run archive:check` after archive, link, page, or asset changes.
- Run `python3 -m compileall -q scripts` after Python script changes.
