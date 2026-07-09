# Cleanup Plan: `scripts/check-psychonautwiki-archive-links.py`
> File ID: CLN-001 | Priority: P3 | File status: DONE

## Assessment
- Single responsibility: manifest and local-link validation. Its complexity is inherent in accumulated error reporting.
- Reopen if checks are split across new archive formats or validation behavior changes.

## Final Gate
- [x] Reviewed; no safe simplifying move justified.
