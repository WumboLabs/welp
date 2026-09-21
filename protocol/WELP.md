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

Terminal closeout (lifecycle ordering):

For an eligible final accepted profile the lifecycle order is:
MEASURE → HUMAN ACCEPT → check for an exact existing LocalMaxxing result →
SUBMIT if no exact valid duplicate exists → VERIFY the real service record →
ARCHIVE artifacts. Artifact archival occurs only AFTER the LocalMaxxing
terminal disposition is established for eligible final profiles.

`MEASURED_NOT_SUBMITTED` is a TEMPORARY state. It is valid only while
scientific work is still active: profile selection may still change,
optimization remains pending, the human acceptance gate is still open, or a
bounded re-test/supplement remains in flight. At terminal closeout, an
eligible final profile must NOT silently remain `MEASURED_NOT_SUBMITTED`; a
terminal non-submission requires an explicit recorded reason:

- `NOT_ELIGIBLE` — demonstrated representation limit (status `NOT_ELIGIBLE`).
- `DUPLICATE_EXISTING` — an exact valid result already exists on the service:
  record `SUBMITTED` with `origin: VERIFIED_EXISTING` and verify that existing
  service record; never create a duplicate.
- `SERVICE_BLOCKED` — service/authentication/availability blocker: record
  `BLOCKED` with the exact blocker evidence.
- `HUMAN_DEFERRED` — the responsible human gate explicitly deferred the
  submission; record the deferral decision and date.

Never fabricate `verifiedRun`, `submission_ref`, or service identity, and
never claim verification without real service evidence. If the canonical
scientific profile or result changes after an earlier measurement, re-check
eligibility and exact identity before submitting or reusing any earlier
record.

Two-stage campaign lifecycle (science turn / closeout turn):

Normal model work runs in two stages with exactly one human acceptance gate
between them:

- **Stage A — science:** test, validate, produce the final scientific
  report/recommendation, and stop once for human scientific acceptance. No
  external actions beyond the campaign boundary.
- **Stage B — closeout:** after explicit human acceptance, complete the whole
  terminal lifecycle in one authorized pass: finalize the canonical profile;
  LocalMaxxing duplicate check; submit the eligible final result; verify the
  real service state; commit/push methodology if needed; publish central
  evidence; attribute/pin canonical commits; update/publish the website
  derivative; archive and verify the model artifact; close testing debt and
  the campaign record.

A closeout handoff MAY explicitly authorize the bounded Git
staging/commit/push, publication, deployment, and archival actions for that
exact closeout. When it does, those routine actions are executed, not
re-gated: an agent must not stop again mid-closeout merely because staging,
a commit, a push, registry attribution with real commit SHAs, website
deployment, or final artifact archival/removal is required. Human SCIENTIFIC
acceptance remains the Stage A → Stage B transition and is never bypassed;
blanket authorization outside a human-approved closeout is never inferred.

At authorized terminal closeout, none of `MEASURED_NOT_SUBMITTED`,
`WEBSITE_READY`, `PENDING_HUMAN_GATE`, or local-retained artifacts may stand
as quiet end states for an eligible final profile. Valid terminal
non-completion requires a REAL blocker — authentication unavailable, service
failure, merge conflict, validator failure, publication-provider failure,
artifact verification failure, or explicit human deferral — recorded with
evidence.

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
  `canonical_evidence.state = PENDING_HUMAN_GATE` (targeting the existing
  `WumboLabs/evaluations` repository) rather than inventing a canonical URL. A website
  record generated from a pending export must state that evidence publication
  is pending; it must not claim canonical public evidence exists. `PENDING_HUMAN_GATE`
  and `WEBSITE_READY` are intermediate, non-terminal states: once the human has
  accepted the science and authorized the closeout's publication actions, the
  disposition must be driven to `WEBSITE_PUBLISHED` (or a real blocker recorded),
  not left standing as a quiet end state.
- Publishing the public evidence repository, committing, pushing, and
  deploying the website remain human-gated external actions; generating the
  export and local derivative records does not authorize any of them. An
  explicit human closeout authorization for the specific campaign satisfies
  those gates for its bounded scope; absent one, they stay closed.
- The website consumes a full-commit, SHA-256-pinned central registry and
  immutable event exports through deterministic sync. Its local registry,
  record pages, and generated indexes are derivatives, not separate sources.
- `REPORT.md` and `WELP-LAB-RECORD.md` expose the disposition and the
  canonical-evidence state; the [completion
  checklist](../docs/reproduction.md#operator-checklist) includes the export.
- Publication identity: assign stable `model_id`, `profile_id`, and `event_id`
  before publication. Append an event under `models/<model_id>/events/<event_id>/`
  in **WumboLabs/evaluations**; register a new profile there only when the tested
  artifact/runtime/deployment surface materially differs. Never create an
  `eval-*` repository. Current profile descriptors use `wumbolabs-eval-profile/2`;
  legacy `/1` descriptors and export `identity.profile_repo` remain historical.
- A published current citation is `{repo, commit, path}` with the full 40-character
  commit SHA and a safe relative artifact path. Shared comparisons live once under
  `shared-events/<shared_event_id>/`, explicitly linked to their models/profiles;
  they have no fabricated owner model. Display attribution does not change science.
- Follow [the publication operating contract](../docs/publication.md) for the
  four-layer architecture, validation, public-safety review, sharing, and cutover.

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

## Task outcome semantics (methodology revision, 2026-09-19)

Every generation-bearing task emits the canonical CP-1 outcome record
(`contracts/welp-outcomes-0.1.0-draft.json`): `semantic`
(`PASS | FAIL | NOT_EVALUABLE`), `completion`
(`COMPLETE | FAIL_LENGTH | EMPTY_ANSWER | INVALID_STOP`), `budget`
(`WITHIN | EXHAUSTED_IN_REASONING | EXHAUSTED_IN_ANSWER | UNKNOWN`), plus
verbatim `finish_reason` wherever the runtime exposes it and the
reasoning/answer token split where measurable.

- Semantic correctness is judged from the usable final-answer channel only.
  Incomplete output does **not** automatically imply semantic FAIL; a
  conclusion that cannot be supported is `NOT_EVALUABLE` — mandatory for
  empty answers and answerless truncation. Reasoning traces may support
  attribution but never substitute for the completed final answer and never
  justify semantic PASS.
- Completion failure (`truncation` = `FAIL_LENGTH`) is an operational
  failure: deployment-relevant, always reported, never a semantic judgment.
- Hidden or unsupported reasoning-token accounting is `UNKNOWN`, never
  guessed.
- Historical campaigns keep their recorded boolean outcomes; scorer-only
  rescoring of retained raw outputs under this vocabulary is new
  supplementary evidence, never a relabel.

## Generation budget policy (methodology revision, 2026-09-19)

The configuration is part of the result
(`contracts/welp-generation-budget-0.1.0-draft.json`):

- Every generation-bearing task freezes `answer_budget`, its generation
  ceiling(s), declared reasoning state, requested vs effective reasoning
  control, and a written rationale. There is **no universal answer-budget
  multiplier law**; a tokenized-reference multiplier may be used as a
  construction heuristic when the fixture states it, justified from expected
  answer form, formatting requirements, acceptable alternatives, a
  class-specific floor, and expected complexity.
- Only reasoning controls **proven effective on the pinned runtime** may be
  load-bearing. A requested-but-ignored control is recorded MEASURED
  (`reasoning_requested` ≠ `reasoning_effective`), never treated as
  effective. Where separation is unenforceable, phases run declared
  total-cap **lanes**.
- Lanes: a predeclared **semantic/non-starving lane** (semantic capability
  claims, completion-conditioned) and the frozen **operational-budget lane**
  (completion/truncation/budget discipline; guardrails, never semantic
  labels). Phases do not automatically double; reliability-class phases and
  the useful-context gate use two lanes when justified.
- Standardized context output reserve: **512 tokens**, derived as
  `max(512, 2 × answer_budget of the useful-context gate tasks)` with the
  gate answer budget 256; campaign-by-campaign 512-vs-640 variance is
  prohibited from this snapshot on.
- Cache policy: scientific performance arms run **disabled/verified
  uncached**; cached serving may be measured separately, labeled `CACHED`,
  and never replaces uncached canonical performance. Harness surfaces
  cached-token telemetry where the runtime provides it.

## Runtime admission levels (methodology revision, 2026-09-19)

"Loaded successfully" is not admission. `harness/admission.py` codifies:

- **BASIC** admission: stock architecture, stock runtime, conventional
  artifact — current practice (coherent generation, template correct, no
  hidden offload, deterministic re-runs, zero CUDA/OOM/Xid).
- **ENHANCED_SEMANTIC** admission additionally required when ANY of: custom
  quant type, custom fork/runtime, activation transform, custom kernel,
  new/unusual architecture, speculative/MTP component, materially unusual
  template, multimodal projector in the tested profile. Adds the known-answer
  battery: factual probe, reasoning smoke, strict structured output,
  absent-information grounding (exact minimum frozen in the harness module;
  full admission redesign is planned P2 follow-up). Custom-runtime campaigns
  must not regress to "it loaded, therefore admitted".

## Failure attribution (methodology revision, 2026-09-19)

Every classification-relevant FAIL carries a cause attribution where evidence
allows: `model | runtime | hardware | scorer-artifact | protocol-limitation |
unknown` (primary + evidence). Attribution does not erase or soften the
measured result. Claim classes remain exactly: `MEASURED, DERIVED, INFERENCE,
HYPOTHESIS, EXTERNAL_REPORTED, UNKNOWN`.

## Canonical contracts (current)

- `welp-outcomes` 0.1.0-draft (task outcome semantics; new)
- `welp-generation-budget` 0.1.0-draft (budget policy, reserve, cache; new)
- `welp-practical-viability` 0.1.4-draft
- `welp-reliability` 0.2.0-draft (scorer v2 + re-derived 20×2 gate; supersedes 0.1.0-draft for new campaigns)
- `welp-context` 0.1.0-draft (superseded for full-context claims by `context-scaling.md`)
- `welp-optimization` 0.1.0-draft
- `welp-stability` 0.1.0-draft
- `welp-final-classification` 0.2.0-draft (in-repo classification logic; supersedes 0.1.0-draft for new campaigns)
- `welp-preflight` 0.1.0-draft
- Phase 5 module contracts (indexed in `contracts/welp-modules.json`): `welp-coding`, `welp-structured-interfaces`, `welp-native-tools`, `welp-extraction-rag`, `welp-reasoning`, `welp-linux-systems`, `welp-omp-local-agent`.

## Canonical schemas (current)

- `welp_campaign_manifest.schema.json`
- `welp_artifact_index.schema.json`
- `welp_publication_status.schema.json`
- `welp_website_publication.schema.json`
- `welp_eval_profile.schema.json`
- `welp_serving_profile.schema.json`
- `welp_toolchain_preflight.schema.json`
- `welp_toolchain_inventory.schema.json`
- `welp_task_outcome.schema.json` (CP-1 task-instance outcome record; new)

## Canonical harness, scorers, and fixtures (current)

- `harness/` — canonical, versioned phase implementations (`welp-phase-harness/1.0.0-draft`): outcomes vocabulary + derivation (`welp_outcomes.py`), admission levels (`admission.py`), quality screen scoring (`quality.py`), reliability scoring/aggregation/gates (`reliability.py`), capability-probe scoring (`capabilities.py`), useful-context outcomes + reserve (`context.py`), final classification (`classification.py`). Campaign wrappers may call canonical behavior; they must not fork scoring semantics.
- `scorers/score_reliability.py` (`welp-reliability-scorer/2`, embedded self-tests) and `scorers/rescore_acceptance.py` (frozen-output acceptance corpus, read-only).
- `fixtures/reliability/welp-reliability-sample-20-v2.json`, `fixtures/useful_context/family-a.json`, `fixtures/quality/welp-quality-screen-12-v1.json` — frozen before outputs, hash-identified in campaign manifests.

## Canonical validator (current)

- `validators/validate_campaign_welp.py` — accepts both WELP and legacy prefixes and both report naming generations, self-test fixtures all PASS; requires the LocalMaxxing completion disposition (`summaries/localmaxxing.json`) for new-format campaigns with snapshot dates from 2026-09-10 on, and the website publication disposition (`summaries/website-publication.json`) for new-format campaigns with snapshot dates from 2026-09-12 on. For methodology-revision-era campaigns (snapshot dates from 2026-09-19 on) it additionally enforces R09–R14: finish/outcome accounting, fixture/scorer hash identity, campaign outcome + budget policy records, reliability scorer v2 self-test, context depth-set/placement evidence, and cache-policy records; frozen historical bundles continue validating unchanged.
- `validators/validate_publication.py` — current immutable citations, scientific IDs,
  shared relationships, and profile-path consistency; legacy URL exports remain accepted.
