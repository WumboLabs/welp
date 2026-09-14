# WELP Validator (`validate_campaign_welp.py`)

The canonical new-campaign validator.

## Required files

- `WELP-CONFORMANCE.md` (canonical for new campaigns)
- Report artifacts, per the [report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy):
  - New-format bundles: `REPORT.md` (primary scientific report) + `WELP-LAB-RECORD.md` (expected companion; absence is a warning).
  - Historical bundles (no `REPORT.md`): `report.md` remains required, with a legacy-naming warning.
  - `REPORT.md` + `report.md` coexistence is an error (`R02_ambiguous_report_pair`) in
    hierarchy-era bundles (protocol snapshot date >= 2026-09-10); frozen pre-hierarchy
    bundles keep both files and remain valid with an `R02_historical_report_pair` warning.
- `protocol-findings.md`
- `summaries/campaign_manifest.json`
- `summaries/toolchain_preflight.json`
- `toolchain/runtime_capabilities.json` (recommended)
- One `results/INVALIDATED-*.reason.json` for each invalidated job (recommended)
- `summaries/localmaxxing.json` (new-format campaigns with snapshot date >= 2026-09-10; expected earlier)
- `summaries/website-publication.json` (new-format campaigns with snapshot date >= 2026-09-12; expected earlier)

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
- **R02** `REPORT.md` + `report.md` coexistence: error (`R02_ambiguous_report_pair`) for
  hierarchy-era campaigns (protocol snapshot date >= 2026-09-10); warning
  (`R02_historical_report_pair`) for frozen pre-hierarchy campaigns, which remain valid unchanged.
- **R03** (warning) new-format bundle without the expected `WELP-LAB-RECORD.md` companion.
- **R04** (warning) historical report.md naming; new campaigns use REPORT.md + WELP-LAB-RECORD.md.
- **R05** LocalMaxxing completion disposition: `summaries/localmaxxing.json` REQUIRED (error) in
  new-format bundles whose campaign snapshot date is >= 2026-09-10; expected (warning) in earlier
  bundles. Historical campaigns without the file remain valid.
  **R06** LocalMaxxing disposition content: invalid/deprecated status value, `SUBMITTED` without
  `origin`/`submission_ref`, or `MEASURED_NOT_SUBMITTED`/`NOT_ELIGIBLE`/`BLOCKED` without `reason`.
- **R07** Website publication disposition: `summaries/website-publication.json` REQUIRED (error) in
  new-format bundles whose campaign snapshot date is >= 2026-09-12; expected (warning) in earlier
  bundles. Historical campaigns without the file remain valid.
- **R08** Website publication disposition content: `disposition` — exactly
  `WEBSITE_READY | WEBSITE_BLOCKED | NOT_FOR_PUBLICATION | WEBSITE_PUBLISHED`;
  `WEBSITE_BLOCKED`/`NOT_FOR_PUBLICATION` require `reason`; the other statuses require
  `website_record_slug`; `canonical_evidence.state` — exactly `PUBLISHED | PENDING_HUMAN_GATE`;
  current `PUBLISHED` evidence requires central repo/full-commit/path; legacy evidence
  retains its URL. Pending evidence claims neither. The `identity` object is required
  for current central publication and optional for historical exports; it must carry non-empty `model_id`,
  `profile_id`, `event_id`, `event_type`; `event_date` must be `YYYY-MM-DD` when given;
  `evidence_scope` must be a non-empty string array when given; `profile_status` must be
  `current | current-alternate | historical | superseded | specialized` when given. Identity
  is optional so frozen exports remain valid unchanged.
  See [WELP website publication disposition](../protocol/WELP.md#website-publication-disposition)
  and `../schemas/welp_website_publication.schema.json`.
- M01–M11 carried over from `validate_campaign_v2.py` 0.2.0-draft.

## LocalMaxxing disposition (`summaries/localmaxxing.json`)

- `summaries/localmaxxing.json` fields: `status` — exactly `SUBMITTED | MEASURED_NOT_SUBMITTED | NOT_ELIGIBLE | BLOCKED`; `SUBMITTED` requires `origin` (`NEW | VERIFIED_EXISTING`) and `submission_ref`; every other status requires `reason`. Recommended companions: canonical profile identity, configured context, actual prompt tokens, result summary, evidence paths.

## Website publication disposition (`summaries/website-publication.json`)

- Schema: `../schemas/welp_website_publication.schema.json` (`wumbolabs-labs-publication/1`). Public-safe derivative fields only.
- `disposition` — exactly `WEBSITE_READY | WEBSITE_BLOCKED | NOT_FOR_PUBLICATION | WEBSITE_PUBLISHED`; blocked/excluded statuses require `reason`; ready/published statuses require `website_record_slug`.
- `canonical_evidence.state` — exactly `PUBLISHED | PENDING_HUMAN_GATE`.
  Current published evidence requires `repo: WumboLabs/evaluations`, full
  40-character `commit`, and safe relative `path`; an optional URL must match that
  tuple exactly. Pending evidence cannot claim a published URL/commit/path.
  Historical URL-only and legacy repo/commit exports retain their original meaning.
- Current exports require `identity`: `model_id`, `profile_id`, `event_id`,
  `event_type`, with optional date, status, and evidence scope. Profiles identify
  tested scientific surfaces, not repositories. Legacy exports may omit identity;
  legacy `profile_repo` remains historical, never a central path.
- `validators/validate_publication.py` checks current citations, profile paths,
  and shared-event relationships; `selftest` exercises rejection boundaries and
  historical acceptance. Central registry validation checks global uniqueness
  and cross-model/profile/event references. See [publication workflow](publication.md).



## Usage

```bash
python3 validate_campaign_welp.py <campaign_dir>     # exit 0 valid, 1 invalid
python3 validate_campaign_welp.py selftest           # run embedded 15-fixture suite
python3 validators/validate_publication.py selftest
python3 validators/validate_publication.py EXPORT PROFILE
```

## Frozen historical campaigns

The validator accepts frozen historical campaign artifacts where needed (conformance filename, snapshot id, contract prefix, preflight const). New campaigns must use WELP identifiers. Do not rewrite frozen evidence to match new names.
