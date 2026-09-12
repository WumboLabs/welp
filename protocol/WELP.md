# WELP — WumboLabs Evaluation Lifecycle Protocol

Canonical: **WELP — WumboLabs Evaluation Lifecycle Protocol** (informal pronunciation: "welp").

> Status: DRAFT. WELP is NOT frozen as v1.0. Thresholds marked draft are under empirical validation.

See `../summaries/welp_compatibility_policy.json` for the formal compatibility policy, `../summaries/welp_migration_inventory.json` for the reference inventory, and `../snapshot-freeze/manifest.json` for the first WELP snapshot.

## Conceptual summary

> "WELP — the WumboLabs Evaluation Lifecycle Protocol — is a reproducible, phase-gated workflow for evaluating local AI models on real hardware. Each campaign freezes the exact model, runtime, hardware, configuration, test contracts, and scoring rules before testing begins. Models then progress through admission, performance, practical viability, reliability, applicable capabilities, context, variance, optimization, stability, and final role classification. Models that fail an early gate stop there instead of consuming unnecessary compute, while successful, failed, and invalidated runs all remain documented."

## Optional informal tagline

> "Run the evidence. Follow the gates. If the model fails: welp."

## Phases (summary)

```
Model → Provenance → Admission → Performance → Practical Viability
  → Reliability → Capability Modules → Context → Variance
  → Optimization → Soak → Final Classification
```

## Context characterization gate

[WELP Context Scaling](context-scaling.md) is the detailed current DRAFT
methodology for future campaigns. Pin the authoritative official card/config
and extension documentation before testing. Every native and officially
advertised extended range, including each exact maximum, requires an explicit
tested or demonstrated limiting disposition.

Configured capacity is not context validation: capacity admission with a small
prompt is admission only. Full-context claims require actual final
rendered/tokenized input at near-full usable-budget occupancy (>=97% hard floor,
>=99% preferred, with reserved generation tokens and justified safety allowance),
full-window performance, and useful-context evidence at that occupancy.

**PRACTICAL PROFILE SELECTED** and **PRACTICAL BASELINE CHARACTERIZED** are
separate from **MODEL-CARD CONTEXT ENVELOPE COMPLETE**. A practical default is
never an automatic stop condition for context characterization. Only completed
dispositions for all required native/official extension rungs and exact maxima
permit **CONTEXT CHARACTERIZATION COMPLETE**. `PARTIAL` and `NOT_TESTED` do not;
properly demonstrated `FIT_LIMIT` and `INTEGRATION_BLOCKED` do, without implying
model-quality FAIL. A measured `FAILED` gate is a negative completed disposition,
not `VALIDATED`; see the method for evidence requirements.

Fit-first safety and earlier phase stops remain binding. A bounded campaign may
stop and report deferred context gaps without claiming context completeness.
Use the mandatory [coverage checklist](../docs/reproduction.md#model-card-context-checklist)
and [report table](../lab-record-template/README.md#model-card-context-coverage).
Freeze this methodology's revision/hash for new work; do not rewrite historical
reports or frozen contracts to imply broader coverage.

## LocalMaxxing completion disposition

Every model campaign must evaluate LocalMaxxing eligibility once the canonical
practical profile is selected, and record exactly one completion disposition.
A campaign must never silently omit LocalMaxxing; a generic "no external
benchmark submission" rule does not suppress this step. External actions other
than LocalMaxxing benchmark submission keep their separate human gates.

Canonical statuses (exactly these values):

| Status | Meaning |
|---|---|
| `SUBMITTED` | A LocalMaxxing-compatible benchmark of the canonical practical stack exists and is recorded on the service. `origin` states `NEW` or `VERIFIED_EXISTING`; the submission id/reference is recorded. |
| `MEASURED_NOT_SUBMITTED` | A valid local benchmark completed but external submission did not occur. Exact reason required. |
| `NOT_ELIGIBLE` | The canonical practical stack cannot be faithfully represented by the current LocalMaxxing benchmark/submission schema or supported engine surface. Technically demonstrated with an evidence path. Never substitute an alternate engine merely to obtain a score. |
| `BLOCKED` | The stack is intended and eligible, but benchmark or submission could not complete due to an integration, authentication, service, or reproducibility blocker. Exact blocker required. |

`NOT_APPLICABLE` / `NOT_AUTHORIZED` are deprecated as completion dispositions
for otherwise eligible model campaigns; `NOT_ELIGIBLE` is reserved for
demonstrated representation limits. The campaign-start preflight auth state
(`READY | AUTH_BLOCKED | CLI_INCOMPATIBLE | NOT_APPLICABLE`) is a separate
readiness record; authentication failure at submission time yields `BLOCKED`,
not `NOT_ELIGIBLE`. Model science may be PASS while this disposition is
`MEASURED_NOT_SUBMITTED` or `BLOCKED`; the unresolved status stays visible.

Rules:

- LocalMaxxing benchmarks the CANONICAL PRACTICAL PROFILE: model artifact,
  quant/precision, engine/runtime version, configured context, KV dtype,
  speculation/MTP when canonical, serving geometry, hardware profile, and
  relevant power configuration. Do not submit an experimental context
  boundary, a convenient alternate engine, or a one-off profile as though it
  represented the canonical stack.
- Configured context capacity and actual prompt tokens are always reported
  separately. Actual prompt tokens must be demonstrated (measured endpoint
  usage or the tokenized prompt bytes); a nominal
  `--prompt-tokens`-style value alone is not evidence unless the current
  tool demonstrably creates a prompt of that length.
- The benchmark follows the CURRENT official LocalMaxxing method: its
  canonical prompts where defined, its warmup/repetition policy, and its
  verification fields. Never fabricate verification fields
  (`verifiedRun` evidence such as prompt/output samples, engine timings, or
  spec/MTP acceptance stats); record unavailable values accurately.
- Before any new submission, search local run stores and any
  service-exposed history for an exact existing record (artifact, quant,
  engine, key geometry, hardware, context). An exact match is
  `SUBMITTED` with `origin: VERIFIED_EXISTING`; never create a duplicate.
  A materially different record does not satisfy the disposition.
- Machine-readable summary: `summaries/localmaxxing.json`; validated by
  `validators/validate_campaign_welp.py` for new campaigns (see
  `../docs/validator.md`). `REPORT.md` exposes eligibility, status, the
  benchmarked canonical profile, actual prompt tokens, result summary,
  submission origin/reference, and the exact reason when not submitted.

## Website publication disposition

Every full WELP model campaign must disposition website publication explicitly
once the campaign closes; it must never silently omit website-publication
state. The WumboLabs website is a human-readable DERIVATIVE of accepted public
evidence, never a second independent source of model facts. Where website
content conflicts with campaign evidence, `REPORT.md` (and the retained raw
evidence behind it) governs and the website is stale/defective.

Canonical statuses (exactly these values):

| Status | Meaning |
|---|---|
| `WEBSITE_READY` | The campaign is closed and has sufficient public-safe material to publish. |
| `WEBSITE_BLOCKED` | Intended for publication but blocked by missing public evidence, an unresolved privacy/publication concern, or a website integration blocker. Exact reason required. |
| `NOT_FOR_PUBLICATION` | Intentionally excluded from the website. Exact reason required. |
| `WEBSITE_PUBLISHED` | Public evidence and the website record are published and verified. |

Machine-readable export: `summaries/website-publication.json`, schema
`../schemas/welp_website_publication.schema.json` (`wumbolabs-labs-publication/1`).
The export carries only public-safe derivative fields (identity, tested
artifact, runtime/hardware, WELP outcome/classification, context profile and
dispositions, headline performance, quality/guardrails/reliability,
LocalMaxxing summary, canonical-evidence state, website record slug, bounded
public summary). It must not contain credentials, local absolute paths,
private usernames, raw prompt logs, telemetry dumps, or internal debug state.

Rules:

- When canonical public evidence is not yet published, the export records
  `canonical_evidence.state = PENDING_HUMAN_GATE` (with a proposed repository
  identity where applicable) rather than inventing a canonical URL. A website
  record generated from a pending export must state that evidence publication
  is pending; it must not claim canonical public evidence exists.
- Publishing the public evidence repository, committing, pushing, and
  deploying the website remain human-gated external actions; generating the
  export and local derivative records does not authorize any of them.
- The website consumes the export through its publication registry and
  deterministic sync workflow. Website record pages and generated index
  surfaces are derived from the registry/exports, not independently
  hand-maintained.
- `REPORT.md` and `WELP-LAB-RECORD.md` expose the disposition and the
  canonical-evidence state; the [completion
  checklist](../docs/reproduction.md#operator-checklist) includes the export.
- Publication identity (added 2026-09-12): before publication a campaign must
  answer — What is the `model_id`? What is the `profile_id`? Is this profile
  already published? If yes, this event appends to the existing canonical
  profile repository; if no, exactly one new canonical profile repository is
  created for it. What is the `event_id`? The export records these in the
  optional `identity` object (`schemas/welp_website_publication.schema.json`,
  0.2.0-draft, additive/backward-compatible); each canonical eval repository
  carries a `profile.json` descriptor
  (`schemas/welp_eval_profile.schema.json`, `wumbolabs-eval-profile/1`).
  The default is NOT one repository per campaign and NOT one repository for
  every profile of a model. Profile boundaries follow material scientific
  surfaces (artifact/quant family, runtime family, deployment topology),
  not campaign or test boundaries.

The campaign validator enforces the disposition for new-format campaigns
whose protocol snapshot date is 2026-09-12 or later (`R07`/`R08`); earlier
bundles receive a warning only and remain valid unchanged. See
`../docs/validator.md`.

## Report artifact hierarchy

Every campaign bundle has one obvious authoritative scientific report and
clearly subordinate companions. The hierarchy is readable from filenames alone.

| Artifact | Role | Authority |
|---|---|---|
| `REPORT.md` | PRIMARY SCIENTIFIC REPORT: outcome, scientific interpretation, measurements, negative findings, classifications, context dispositions, limitations, next human gate | authoritative source of truth for the campaign |
| `WELP-LAB-RECORD.md` | standardized structured WELP Lab Record | companion/index of the SAME campaign; not another experiment, another run, or an independent report |
| `<campaign-slug>-review-report.md` | human review summary (conventionally under the campaign bundle as `<campaign>/reviews/`) | noncanonical convenience summary; must prominently link `REPORT.md` and `WELP-LAB-RECORD.md` |
| `<campaign>-prior-attempt-quarantined/` | superseded prior execution preserved intact | superseded forensic evidence; never current evidence |

Rules:

- Exactly one current primary `REPORT.md` per active campaign bundle. If any
  companion conflicts with it, `REPORT.md` governs, and the discrepancy is a
  documentation defect: reconcile from retained raw evidence, not from whichever
  value is more convenient, then correct or explicitly report the defect.
- Do not create `report.md` in future campaigns. `REPORT.md` and `report.md`
  must never coexist as differently-cased names for two different document
  roles. `report.md` remains legitimate only as frozen historical evidence.
- Each current campaign-facing report opens with a lightweight role header, for
  example: `Artifact role:`, `Campaign:`, `Status: CURRENT | CURRENT COMPANION`,
  plus a pointer to the primary report (`Primary scientific report: REPORT.md`
  in companions). Keep it minimal; clarity, not bureaucracy.
- Where the values exist, reports may carry a short human-readable run
  fingerprint — campaign slug, execution date, scientific request count,
  server/runtime arm count, outcome/decision label — so current, superseded,
  and summarized artifacts are distinguishable at a glance. Omit counts where
  those concepts do not apply. This is a readability aid, not a cryptographic
  identity.
- A prior substantial execution that must be superseded is preserved intact
  under an unmistakable sibling path (preferred suffix:
  `-prior-attempt-quarantined`), never silently deleted, overwritten, merged
  into the current run, or treated as current evidence. The current `REPORT.md`
  records: that a prior attempt exists, its quarantine path, why it was
  superseded, and whether any data from it is used. Current scientific claims
  come from the current execution; do not relabel quarantined bytes when
  preservation contracts require byte identity.

The validator enforces this hierarchy for hierarchy-era campaigns (protocol
snapshot dated 2026-09-10 or later) and accepts frozen pre-hierarchy bundles —
including legacy `REPORT.md` + `report.md` coexistence — without retroactive
failure; see `../docs/validator.md`.

## Canonical contracts (current)

- `welp-practical-viability` 0.1.4-draft
- `welp-reliability` 0.1.0-draft
- `welp-context` 0.1.0-draft
- `welp-optimization` 0.1.0-draft
- `welp-stability` 0.1.0-draft
- `welp-final-classification` 0.1.0-draft
- `welp-preflight` 0.1.0-draft
- Phase 5 module contracts (indexed in `contracts/welp-modules.json`): `welp-coding`, `welp-structured-interfaces`, `welp-native-tools`, `welp-extraction-rag`, `welp-reasoning`, `welp-linux-systems`, `welp-omp-local-agent`.

## Canonical schemas (current)

- `welp_campaign_manifest.schema.json`
- `welp_artifact_index.schema.json`
- `welp_publication_status.schema.json`
- `welp_website_publication.schema.json`
- `welp_serving_profile.schema.json`
- `welp_toolchain_preflight.schema.json`
- `welp_toolchain_inventory.schema.json`

## Canonical validator (current)

- `validators/validate_campaign_welp.py` — accepts both WELP and legacy prefixes and both report naming generations, 15 fixtures, all PASS; requires the LocalMaxxing completion disposition (`summaries/localmaxxing.json`) for new-format campaigns with snapshot dates from 2026-09-10 on, and the website publication disposition (`summaries/website-publication.json`) for new-format campaigns with snapshot dates from 2026-09-12 on.
