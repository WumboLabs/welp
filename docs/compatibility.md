# WELP — historical compatibility

The active protocol was renamed from WLEP to WELP on 2026-08-26. This note describes how historical WLEP artifacts continue to be supported.

## What is preserved

- Frozen snapshots: `wlep-next-snapshot-2026-08-25-phase5`, `wlep-next-snapshot-2026-08-25-end-to-end`, `wlep-next-snapshot-2026-08-26-post-apodex`.
- Frozen campaign artifacts: apodex-1.1-mini (with `WLEP-CONFORMANCE.md`), Nemotron `wlep-validation-2`, LFM2.5-1.2B/2.6B QAD, Qwen3.8-27B.
- Frozen contracts: any `wlep-*.json` whose hash is recorded in a published campaign manifest.
- Frozen schemas: any `wlep_*.schema.json` whose hash is recorded in a published campaign manifest.
- Lab Record directory names like `lab-records/<model>/wlep-<YYYY-MM-DD>/` are filesystem provenance; do not rename.

## What is not silently rewritten

- WLEP reports are not retroactively renamed to WELP.
- `wlep-` contract filenames are not renamed to `welp-` (would invalidate frozen hashes).
- `wlep_` schema filenames are not renamed to `welp_` (would invalidate frozen hashes).
- Historical snapshot manifest hash tables are unchanged.

## Machine-readable aliases

- `welp-` and `wlep-` are both accepted by the canonical validator.
- `WELP-CONFORMANCE.md` and `WLEP-CONFORMANCE.md` are both accepted as required files.
- `welp-preflight` and `wlep-preflight` are both accepted as preflight const values.
- `welp-next-snapshot-*` and `wlep-next-snapshot-*` are both accepted as protocol_snapshot.id.

## Reproducibility

Reproducing an old campaign:
1. Use the frozen snapshot at `wlep-next-snapshot-<date>-<suffix>/protocol-freeze/manifest.json`.
2. Use the frozen contracts, scorers, and validators at the recorded SHA-256s.
3. Use `wlep_validate.py` (frozen) or the new `validate_campaign_welp.py` (accepts both prefixes).

Running a new campaign:
1. Use the first WELP snapshot at `welp-next-snapshot-2026-08-26-post-rename`.
2. Use the canonical WELP-named successor contracts at `welp-development/welp-to-welp-rename/contracts/`.
3. Use `validate_campaign_welp.py`.
4. Produce `WELP-CONFORMANCE.md` and `summaries/welp_conformance.json`.
