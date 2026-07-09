# Cleanup Task Tracker
> Updated: 2026-07-09 | Status: execution complete
> Inventory: 7 | Tracker rows: 7 | Plans: 7

## Reconciliation
- Actionable files: **1**; reviewed/no-action files: **6**.
- TODO / IN_PROGRESS / BLOCKED / DONE tasks: **0 / 0 / 0 / 1**.
- Ledger check: inventory = tracker rows = plans = **7**.

## Execution Order
1. Safety net: CLN-006-T1 characterization.
2. Decomposition: CLN-006-T2 extraction.
3. Final pass: complete.

## File Ledger
| File ID | Status | File | Plan | Note |
|---|---|---|---|---|
| CLN-001 | DONE | `scripts/check-psychonautwiki-archive-links.py` | [plan](plans/scripts-check-psychonautwiki-archive-links-py.md) | reviewed |
| CLN-002 | DONE | `scripts/convert-webp.py` | [plan](plans/scripts-convert-webp-py.md) | reviewed |
| CLN-003 | DONE | `scripts/enhance-pages.py` | [plan](plans/scripts-enhance-pages-py.md) | user-modified |
| CLN-004 | DONE | `scripts/mirror-psychonautwiki-archive.py` | [plan](plans/scripts-mirror-psychonautwiki-archive-py.md) | reviewed |
| CLN-005 | DONE | `scripts/normalize-asset-extensions.py` | [plan](plans/scripts-normalize-asset-extensions-py.md) | user-owned |
| CLN-006 | DONE | `scripts/standardize-skin.py` | [plan](plans/scripts-standardize-skin-py.md) | CLN-006-T1/T2 complete |
| CLN-007 | DONE | `scripts/vendor-assets.py` | [plan](plans/scripts-vendor-assets-py.md) | reviewed |

## Task Ledger
| Task ID | Pri | Status | File ID | Task | Validation |
|---|---|---|---|---|---|
| CLN-006-T1 | P1 | DONE | CLN-006 | Capture CLI behavior | stdout/exit-code comparison |
| CLN-006-T2 | P1 | DONE | CLN-006 | Extract batch conversion | compileall; archive:check |

## Completion Gates
- [x] Final inventory reconciles to rows and plans.
- [x] Every task is DONE or deliberately BLOCKED.
- [x] Every no-action rationale was rechecked.
- [x] Audit targets and whole-repository validation are recorded.
