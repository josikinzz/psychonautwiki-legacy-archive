# Codebase Cleanup Audit
> Baseline: 2026-07-09 | Updated: 2026-07-09 | Project: psychonautwiki-2016-archive

## Orientation
- Stack and architecture: Python 3 maintenance scripts generate and validate a static `public/` archive; `public/` is generated/archive content and excluded from code refactoring.
- Validation: `python3 -m compileall -q scripts`; `npm run archive:check`.
- Cleanup workspace: `cleanup/`.

## Scope and Inventory
- Repository-owned logic files: **7**.
- Included: `scripts/*.py` (six tracked scripts plus the in-scope untracked normalizer supplied in the worktree).
- Excluded: generated archive/assets (`public/`), temporary output (`output/`, `.audit-screenshots/`), bytecode, configuration, and documentation.
- Measurement: Python AST function complexity (base 1 plus branch/boolean nodes) and physical/approximate logic LOC.

## Executive Summary
- Health: B+; all scripts compile and archive link validation passes.
- Priorities: reduce `standardize-skin.py` CLI orchestration complexity; preserve user-owned work in `enhance-pages.py` and `normalize-asset-extensions.py`.
- Finding counts: P0 0 / P1 1 / P2 0 / P3 0.

## Baseline Metrics
| Metric | Baseline | Target |
|---|---:|---:|
| Inventory files | 7 | 7 accounted for |
| Max logic LOC | 442 | cohesive under 500 |
| Files above 500 logic LOC | 0 | 0 |
| Max function complexity | 20 | <= 10 |
| God objects | 0 | 0 |
| Circular dependencies | 0 observed | 0 |
| Duplicated-knowledge clusters (3+) | 0 confirmed | 0 |
| Confirmed dead-code findings | 0 | 0 |

## Findings
### CLN-006: Split skin-standardization CLI orchestration — P1
- Evidence: `scripts/standardize-skin.py:488` (`main`, complexity 20).
- Impact: argument parsing, validation, mode dispatch, and conversion iteration were coupled in one entry point.
- Test seam: three captured CLI scenarios, Python compilation, and archive link checker.
- Required end state: CLI orchestration delegates batch conversion; existing outputs and exit codes remain unchanged.
- Status: DONE.

## Inventory Disposition
| File | Metrics summary | Disposition | Plan |
|---|---|---|---|
| `scripts/check-psychonautwiki-archive-links.py` | 88 logic LOC; max complexity 13 in validation loop | no action | [plan](plans/scripts-check-psychonautwiki-archive-links-py.md) |
| `scripts/convert-webp.py` | 210; max 14; cohesive conversion pipeline | no action | [plan](plans/scripts-convert-webp-py.md) |
| `scripts/enhance-pages.py` | 231; max 6; user-modified | no action | [plan](plans/scripts-enhance-pages-py.md) |
| `scripts/mirror-psychonautwiki-archive.py` | 390; max 7; cohesive mirror pipeline | no action | [plan](plans/scripts-mirror-psychonautwiki-archive-py.md) |
| `scripts/normalize-asset-extensions.py` | 82; max 7; untracked user work | no action | [plan](plans/scripts-normalize-asset-extensions-py.md) |
| `scripts/standardize-skin.py` | 442; max 20 -> 9 for `main` | actionable | [plan](plans/scripts-standardize-skin-py.md) |
| `scripts/vendor-assets.py` | 346; max 13; cohesive vendoring pipeline | no action | [plan](plans/scripts-vendor-assets-py.md) |

## Final Verification
- Final inventory and reconciliation: 7 inventory files = 7 tracker rows = 7 plans.
- Full validation: `python3 -m compileall -q scripts` passed; `npm run archive:check` passed (535 pages, no broken local wiki links).
- Baseline -> final: `standardize-skin.py` `main` complexity 20 -> 9; all characterization scenario stdout and exit codes matched byte-for-byte.
- Resolved/blocked/justified findings: 1 resolved / 0 blocked / 6 reviewed-no-action.
