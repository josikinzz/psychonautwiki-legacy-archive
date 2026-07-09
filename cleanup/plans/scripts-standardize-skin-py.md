# Cleanup Plan: `scripts/standardize-skin.py`
> File ID: CLN-006 | Priority: P1 | File status: DONE

## Assessment
- `main` mixed parsing, validation, dispatch, and conversion iteration (complexity 20).
- Test seam: missing-template, invalid mode-combination, and zero-page `--out --limit 1` CLI scenarios.

## Required End State
- `main` dispatches; batch conversion has an explicit function; CLI output and exit codes are unchanged.

## Ordered Tasks
- [x] CLN-006-T1 — capture scenario outputs and exit codes.
- [x] CLN-006-T2 — extract `parse_args` and `convert_minerva_pages`; validate compilation and archive links.

## Progress and Evidence
- 2026-07-09: all three output hashes matched before/after; `main` complexity 20 -> 9; `npm run archive:check` passed.

## Final Gate
- [x] Required end state holds.
