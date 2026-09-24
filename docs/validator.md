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
- **R09–R14 (methodology-revision era, campaign snapshot date >= 2026-09-19 only; frozen
  historical bundles remain valid unchanged):**
  - **R09** CP-1 outcome/finish accounting: `outcome_semantics`
    (`{contract: welp-outcomes-0.1.0-draft, task_outcome_triples: true}`) and
    `phase_finish_accounting` entries REQUIRED; any COMPLETE rows with
    missing/unknown finish_reason is an error.
  - **R10** Fixture/scorer hash identity: `fixtures`/`scorers` manifest entries
    require 64-hex `sha256`; when the referenced path resolves against the WELP
    repo root, the recorded hash must match the file bytes. For earlier frozen
    snapshots, validate against that snapshot's immutable frozen hash instead
    of today's changed working-tree fixture or scorer bytes
    (`R10_fixtures_hash_mismatch` / `R10_scorers_hash_mismatch`).
  - **R11** `campaign_outcome` REQUIRED: exactly `COMPLETE_PASS |
    COMPLETE_WITH_GAPS | FAILED_EXECUTION | BLOCKED` (execution outcome is
    independent of the model verdict).
  - **R12** `generation_budget.contract = welp-generation-budget-0.1.0-draft`
    REQUIRED, and the matching scorer selftest REQUIRED before live reliability
    use: scorer `/2` historically, `/3` from 2026-09-24.
  - **R13** When the context phase executed (`phases_executed`): `context_validation`
    REQUIRED with exact depths `[2, 25, 50, 75, 95]` and placement preflight
    PASS (`max_placement_error_pp <= 0.5`). Pre-2026-09-23 snapshots require
    their historical `reserve_tokens: 512`; prospective snapshots instead use
    lane-specific R16 reserves. Deferred context is a warning.
  - **R14** `cache_policy` REQUIRED: `scientific_arms: DISABLED_UNCACHED` with a
    `verification` marker; cached serving arms are declared separately and labeled.
- **R15–R16 (prospective snapshots dated >= 2026-09-23 only):** R15 requires
  frozen SHA-256 prompt-lane/profile identities, predeclared bounded semantic
  calibration and positive operational ceiling. R16 requires the legacy
  Family A 1.2 Controlled Context solver (final-rendered-token placement), lane reserves, matched preflight/inference
  tokenization and a hash-pinned fixture. The first 2026-09-23 snapshot retains
  its frozen `welp-final-classification-0.3.0-draft` record. The subsequent
  profile-identity clarification snapshot uses 0.3.1 and requires every
  dimension's selected profile ID to equal the DEPLOYMENT prompt profile ID;
  semantic and operational budget lanes remain separate measurements under
  that same deployment profile. Blocked/failed execution has no readiness
  verdict except an independently evidenced integration blocker on a blocked
  campaign.
- **Prospective hardening (snapshots dated >= 2026-09-24):** scorer v3,
  the Family A 1.3 Controlled Context fixture and classification 0.4; manifest/schema required identity fields
  align, including model/runtime/requested/effective/publication fields.
  `hardening_evidence` is a rooted relative path plus SHA-256 to actual setup,
  paired reliability, context and role evidence. The bundle checker validates
  hashes, re-scores outputs, enforces the required inventory and derives the
  classification/report. COMPLETE_PASS cannot hide missing applicable work,
  invalid execution, pending adaptive sampling or unresolved deciding review.
  Valid negative completed evidence remains distinct from capability success.
  A review record proves provenance/binding, not the truth of its judgment.
  Historical acceptance remains version-aware and does not retroactively apply
  these stronger checks or certify historical scientific interpretations.

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
python3 validators/validate_campaign_welp.py <campaign_dir> # exit 0 valid, 1 invalid
python3 validators/validate_campaign_welp.py selftest       # historical + prospective fixtures
python3 validators/validate_publication.py selftest
python3 validators/validate_publication.py EXPORT PROFILE
python3 harness/setup.py selftest
python3 harness/bundle.py selftest
python3 harness/measurement.py selftest
```

## Frozen historical campaigns

The validator accepts frozen historical campaign artifacts where needed (conformance filename, snapshot id, contract prefix, preflight const). New campaigns must use WELP identifiers. Do not rewrite frozen evidence to match new names.
