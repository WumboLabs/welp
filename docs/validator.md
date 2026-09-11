# WELP Validator (`validate_campaign_welp.py`)

The canonical new-campaign validator.

## Required files

- `WELP-CONFORMANCE.md` (canonical for new campaigns)
- Report artifacts, per the [report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy):
  - New-format bundles: `REPORT.md` (primary scientific report) + `WELP-LAB-RECORD.md` (expected companion; absence is a warning).
  - Historical bundles (no `REPORT.md`): `report.md` remains required, with a legacy-naming warning.
  - `REPORT.md` + `report.md` coexisting in one bundle is an error (ambiguous case-different pair).
- `protocol-findings.md`
- `summaries/campaign_manifest.json`
- `summaries/toolchain_preflight.json`
- `toolchain/runtime_capabilities.json` (recommended)
- One `results/INVALIDATED-*.reason.json` for each invalidated job (recommended)

## Required manifest fields

- `protocol_snapshot.id` — new campaigns: `^welp-next-snapshot-YYYY-MM-DD-...$`. Frozen historical campaigns may retain their original snapshot identifiers.
- `serving_profile.gate_baseline_reasoning_state` — REASONING_OFF | ON | NOT_APPLICABLE
- `serving_profile.reasoning_requested` and `serving_profile.reasoning_effective` (both required)
- `phase2_harness_version` (string)
- `generation_evidence[]` — absolute paths; COMPLETE entries must have sha256 + rows; INVALIDATED entries must have reason
- `contracts` — new campaigns: keys must start with `welp-`

## Required preflight fields

- `preflight` const — `welp-preflight` (new campaigns)
- `protocol.snapshot_id` — same pattern as manifest
- `protocol.welp_status` — `DRAFT` (until v1.0)
- `publication.localmaxxing_auth_status` — READY | AUTH_BLOCKED | CLI_INCOMPATIBLE | NOT_APPLICABLE
- `output.campaign_workspace_abs` and `output.evidence_path_writable` (both required)

## Detected defects

- **N01** snapshot id pattern mismatch.
- **N02** preflight const invalid.
- **N03** current-looking snapshot_id whose evidence still references only frozen historical contracts.
- **R02** `REPORT.md` + `report.md` coexistence (ambiguous case-different report pair).
- **R03** (warning) new-format bundle without the expected `WELP-LAB-RECORD.md` companion.
- **R04** (warning) historical `report.md` naming; new campaigns use `REPORT.md` + `WELP-LAB-RECORD.md`.
- M01–M11 carried over from `validate_campaign_v2.py` 0.2.0-draft.

## Usage

```bash
python3 validate_campaign_welp.py <campaign_dir>     # exit 0 valid, 1 invalid
python3 validate_campaign_welp.py selftest           # run embedded 8-fixture suite
```

## Frozen historical campaigns

The validator accepts frozen historical campaign artifacts where needed (conformance filename, snapshot id, contract prefix, preflight const). New campaigns must use WELP identifiers. Do not rewrite frozen evidence to match new names.
