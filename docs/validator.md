# WELP Validator (`validate_campaign_welp.py`)

The canonical new-campaign validator. Accepts both WELP and WLEP prefixes.

## Required files (any of these work)

- `WELP-CONFORMANCE.md` (canonical for new campaigns) OR `WLEP-CONFORMANCE.md` (legacy)
- `report.md`
- `protocol-findings.md`
- `summaries/campaign_manifest.json`
- `summaries/toolchain_preflight.json`
- `toolchain/runtime_capabilities.json` (recommended)
- One `results/INVALIDATED-*.reason.json` for each invalidated job (recommended)

## Required manifest fields

- `protocol_snapshot.id` — must match `^(welp|wlep)-next-snapshot-YYYY-MM-DD-...$`
- `serving_profile.gate_baseline_reasoning_state` — REASONING_OFF | ON | NOT_APPLICABLE
- `serving_profile.reasoning_requested` and `serving_profile.reasoning_effective` (both required)
- `phase2_harness_version` (string)
- `generation_evidence[]` — absolute paths; COMPLETE entries must have sha256 + rows; INVALIDATED entries must have reason
- `contracts` — keys must start with `welp-` or `wlep-`

## Required preflight fields

- `preflight` const — `welp-preflight` (current) or `wlep-preflight` (legacy-compatible)
- `protocol.snapshot_id` — same pattern as manifest
- `protocol.welp_status` — `DRAFT` (until v1.0)
- `publication.localmaxxing_auth_status` — READY | AUTH_BLOCKED | CLI_INCOMPATIBLE | NOT_APPLICABLE
- `output.campaign_workspace_abs` and `output.evidence_path_writable` (both required)

## Detected defects

- **N01** snapshot id pattern mismatch.
- **N02** preflight const invalid.
- **N03** silently rewritten legacy manifest: welp-* snapshot_id referencing only wlep-* contracts.
- M01–M11 carried over from `validate_campaign_v2.py` 0.2.0-draft.

## Usage

```bash
python3 validate_campaign_welp.py <campaign_dir>     # exit 0 valid, 1 invalid
python3 validate_campaign_welp.py selftest           # run embedded 5-fixture suite
```

## Backwards compatibility

The WELP validator is a strict superset of the frozen `validate_campaign_v2.py` (0.2.0-draft). Historical WLEP campaigns continue to validate against either validator; new WELP campaigns validate against `validate_campaign_welp.py`.

For historical WLEP reproduction, the frozen `wlep_validate.py` and `final_validate.py` are also available unchanged.
