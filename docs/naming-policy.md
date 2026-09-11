# WELP naming policy

Canonical protocol name: **WELP** (WumboLabs Evaluation Lifecycle Protocol).

## Current / new work

All new and current-facing artifacts use `WELP` / `welp`:

- docs, READMEs, templates, examples
- new contracts, schemas, reports, Lab Records
- Labs catalog presentation
- WumboCore Lab Records

Do not introduce noncanonical protocol identifiers in current-facing material.

## Report artifact filenames

Campaign report artifacts have fixed role names (full hierarchy and precedence
rules: [Report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy)):

- `REPORT.md` — the primary scientific report; exactly one per current campaign bundle.
- `WELP-LAB-RECORD.md` — the standardized Lab Record companion; summarize/index `REPORT.md`, never compete with it.
- `<campaign-slug>-review-report.md` — optional human review summary; a noncanonical convenience document.
- `report.md` — historical: accepted in frozen bundles, prohibited as a future Lab Record name, and never coexisting with `REPORT.md`.

## Frozen provenance

Do not rewrite frozen provenance identifiers. Exact historical snapshot IDs, contract IDs, conformance filenames, campaign directory names, and hash-bound evidence stay as recorded.

## Validator compatibility

The campaign validator may retain historical identifiers where required to validate frozen campaign artifacts. New campaigns must still use WELP identifiers.

## Publication

Human-readable publication uses WELP. Translate internal frozen identifiers to canonical WELP terminology when the exact historical string is not required for reproducibility.
