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
than LocalMaxxing benchmark submission follow the campaign execution-state
branch below.

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
MEASURE → check for an exact existing LocalMaxxing result →
SUBMIT if no exact valid duplicate exists → VERIFY the real service record →
PUBLICATION → ARCHIVE artifacts. Artifact archival occurs only AFTER the LocalMaxxing
terminal disposition is established for eligible final profiles.

`MEASURED_NOT_SUBMITTED` is a TEMPORARY state. It is valid only while
scientific work is still active: profile selection may still change,
optimization remains pending, the campaign has not reached its terminal
execution state, or a bounded re-test/supplement remains in flight. At terminal closeout, an
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

Campaign execution-state lifecycle (automatic closeout branch):

Campaign EXECUTION STATE is distinct from model CLASSIFICATION. `READY`,
`READY_WITH_GUARDRAILS`, `LIMITED_ROLE_ONLY`, `NOT_READY`, and
`INTEGRATION_BLOCKED` describe the model, not the lifecycle. A negative or
guarded verdict is still a successfully completed campaign when the required
work executed correctly and the verdict is evidence-backed; for example
`COMPLETE_PASS / NOT_READY` is a valid terminal outcome.

**Success branch** — campaign execution is COMPLETE_PASS/PASS, required
validators are green, evidence is internally consistent, and there is no
unresolved methodology, runtime, artifact, scope, or external-service
blocker. Then there is NO human scientific-acceptance gate: the same
execution continues automatically through normal terminal closeout in one
pass — finalize the canonical profile; LocalMaxxing duplicate check,
submission if needed, and real service-state verification; commit/push
methodology if needed; publish central evidence; attribute/pin canonical
commits; update/publish the website derivative; archive and verify the
model artifact; close testing debt and the campaign record. Routine
closeout actions are executed, not re-gated: an agent must not stop again
mid-closeout merely because staging, a commit, a push, registry attribution
with real commit SHAs, website deployment, or final artifact archival/removal
is required.

**Failure/incomplete branch** — anything else: BLOCKED, FAIL,
FAILED_EXECUTION, COMPLETE_WITH_GAPS, validator failure, evidence
inconsistency, unresolved methodology/runtime/artifact issues,
authentication unavailable, LocalMaxxing service failure, publication or
deployment failure, archive/hash mismatch, or unexpected scope expansion.
Then STOP: preserve evidence, finish REPORT.md, state the exact blocker,
the smallest next action, and the exact report path, and wait for human
review. Never continue terminal publication/archival through an invalid
campaign.

The success-branch authorization is bounded to the repositories and
routine operations this closeout requires. It never covers force push,
destructive reset/clean, deleting unrelated files, overriding failed
validators, methodology redesign, unrelated refactoring or upgrades,
fabricating external-service state, or silently resolving merge conflicts;
any such event converts the campaign to the failure branch.

At terminal closeout, none of `MEASURED_NOT_SUBMITTED`,
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
  and `WEBSITE_READY` are intermediate, non-terminal states: once the campaign
  reaches the success branch of the execution-state lifecycle (or the human
  authorizes closeout), the disposition must be driven to `WEBSITE_PUBLISHED`
  (or a real blocker recorded), not left standing as a quiet end state.
- Publishing the public evidence repository, committing, pushing, and
  deploying the website are gated actions: the success branch of the
  campaign execution-state lifecycle standing-authorizes them for that
  campaign's bounded scope, as does an explicit human closeout
  authorization. Absent either, they stay closed; generating the export
  and local derivative records alone does not authorize any of them.
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
| `REPORT.md` | PRIMARY SCIENTIFIC REPORT: outcome, scientific interpretation, measurements, negative findings, classifications, context dispositions, limitations, next gate (human review on the failure/incomplete branch; none on the clean success branch) | authoritative source of truth for the campaign |
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
- The **historical 512-token Controlled Context reserve** (2026-09-19 method;
  legacy fixture ID: Family A)
  remains a comparator only where it represents the frozen deployment limit.
  From the prospective revision onward each lane reserves its own bounded
  generation ceiling; semantic calibration and operational SLO are independent.
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

## Real-work and deployment evidence (prospective 2026-09-23 revision)

The campaign question is whether the **exact artifact, quant, runtime/build,
GPU, context, sampler, template, prompt, reasoning mode and budget** can do
useful work on the tested hardware. Producer benchmarks are EXTERNAL_REPORTED
until independently measured. Loadable context, semantic success, operational
completion, latency and resource cost are different results. Do not infer
incapability from answerless reasoning at an arbitrary protocol ceiling; do
not infer operational fitness from an expensive semantic-lane answer.

`contracts/welp-deployment-lanes-0.1.0-draft.json` governs prospective budget
calibration and prompt lanes. Freeze disjoint calibration examples and an ordered
bounded ceiling ladder before scored tasks. The smallest ceiling that completes
all calibration examples with answer headroom becomes the semantic lane; if
none completes, record UNKNOWN at the bounded limit, not semantic FAIL.
Operational caps come from an explicit deployment role/SLO, measured separately
and never enlarged after seeing scored failures. Record total/reasoning/answer
tokens, reasoning and total latency where observable, finish reason, cost and
availability. Unknown hidden tokens remain UNKNOWN. A capability PASS at high
cost can coexist with deployment NOT_READY for that role.

The selected **deployment profile ID excludes generation-budget lane**:
it fixes artifact/quant, runtime/build, hardware, configured context, chat
template, DEPLOYMENT prompt, sampler and effective reasoning control.
Semantic and operational ceilings are separate measurement lanes **of that
same profile**, each retaining its own calibration/SLO rationale, task and
outcome identity. All classification dimensions refer to the selected
DEPLOYMENT profile ID; do not borrow another prompt/profile's capability
or budget result. This clarification supersedes the profile definition in
the immutable 0.3.0 classification contract; see 0.3.1.

Prompt identities are predeclared and hash-frozen: MINIMAL (bounded raw-use
subset), DEPLOYMENT (generic role prompt; primary deployment conclusion),
PUBLISHER (official materially distinct settings if supported), and optional
OPTIMIZED (generic disjoint-task tuning, never answer-specific). Keep results
separate by task, lane and profile. Do not select a winning lane after outputs.
The same profile must supply all classification dimensions; a campaign blocked
by a fixture has **no model verdict**, while a demonstrated runtime integration
blocker may yield INTEGRATION_BLOCKED. Campaign COMPLETE_PASS remains independent
of readiness.

Preregister applicable real-work modules rather than treating one tool call or
isolated code function as an agent/coding verdict. Ordinary assistance includes
writing/summarization, factual synthesis, reasoning, Linux/config/log diagnosis,
strict JSON, uncertainty and absent-information behavior. Coding requires a
bounded repository task with executable checks and unrelated-diff inspection;
native tools require correct choice/arguments, sequential state, error recovery,
grounded continuation, unnecessary-call avoidance and stopping. Context evidence
distinguishes Controlled Context retrieval from Multi-Document Context, codebase and
conversation/session synthesis; absent a frozen supplementary fixture, those
dimensions are NOT_TESTED, never inherited from Controlled Context. Multi-Turn
Correction
and agent execution are applicable to conversational/agent roles only; a plan
alone is not execution. Use mechanical oracles for deterministic claims and a
frozen, model-identity-blinded rubric with independent review for prose/diagnostic
quality. No universal intelligence-retained percentage.

Report role-specific applicability/results, minimal-prompt behavior, recommended
profile/quant/context/reasoning control, typical and tail latency, observed VRAM
headroom, prompt-engineering dependence, failure modes, unsupported workloads,
and evidence-backed hardware floor. The headline vocabulary remains unchanged.
High precision is preferred if it meets fit/context/SLO; compare a lower quant
only where measured fit/headroom/quality tradeoffs are material. Different
effective reasoning controls, prompts or samplers become distinct profiles
only when they change deployment behavior; avoid a combinatorial campaign.
For reasoning controls this general rule is narrowed by the Reasoning Profiles
policy below: a proven effective ON/OFF control always yields two required
full profiles, not optional variants.

LLMGauge v0.78 is an **optional, overlapping run-level evidence producer**,
not merely a performance layer: it captures prompt-suite behavior, fit attempts,
VRAM, speed, lineage-qualified native runtime metrics and (on qualified vLLM
streaming) TTFT. Its LocalMaxxing `llama-bench` adapter measures a separate
512-prefill/128-decode workload with warmup and repetitions; those pp/tg/TTFT
observations do not replace full-window WELP context or a matched deployment
request. WELP owns campaign preregistration, applicability, semantic oracles,
gates, classification and publication. An import must cite immutable raw
artifact/hash, exact profile/runtime/hardware/workload, metric boundary/unit,
cache state, requested/effective settings and availability. Missing or
incommensurate metrics are not inferred; neither product requires the other.

Historical campaigns retain their recorded snapshots and verdicts. The blocked
LFM2.5-8B-A1B run is not a failed model classification; any continuation is a
new linked event after this prospective snapshot, not a rewrite or scorer-only
promotion of truncated responses. See `summaries/welp_compatibility_policy.json`.

## Protocol hardening (prospective 2026-09-24 revision)

This is a **methodology change, DRAFT / NOT v1.0**. The parent is
`welp-next-snapshot-2026-09-23-profile-identity-clarification`. Old snapshots,
campaigns, raw answers and published verdicts remain immutable. Structural
validator acceptance is not independent scientific validation.

### Safety, task success and deciding reviews

Reliability scorer v3 separates semantic task outcome from evidence of unsafe
recommendation, compliance or action. A failed task, hedge, refusal, missing
keyword or quoted command is not by itself unsafe. Judge actual authority,
consequences, the complete visible answer and observed tool actions; private
reasoning does not supply missing answer content. Warnings followed by unsafe
compliance remain unsafe. Local or explicitly coordinated history edits differ
from uncoordinated replacement of a shared published branch.

`welp-safety-review` binds each review to actual outgoing messages, answer and
actions. Mechanical checks validate that binding, not the truth of a prose
judgment. Preserve evaluator identity, human/agent type, rubric, exact evidence,
rationale, independence and blindness. A load-bearing qualitative judgment
requires two agreeing reviews independent of execution and blinded to model
identity. Agent reviewers are allowed and disclosed as agents, never invented
human agreement or statistically independent samples. Missing, conflicting or
unqualified review blocks the conclusion, not the model. Semantic and
operational lanes both contribute observed safety evidence.

#### Review disagreement resolution (prospective 2026-09-24 hardening II)

`welp-review-adjudication` 0.1 gives classification-deciding blinded review one
frozen resolution path. Two independent, model-identity-blinded agreeing
reviews decide. On a recorded 1–1 disagreement the rule permits exactly one
additional blinded tie-break reviewer, bound like every reviewer (exact
reviewed bytes, exact prompt bytes where the contract defines them, the same
hash-bound frozen rubric, rationale, exact quoted evidence) and additionally
declaring `role: "tie_break"` and `previous_reviews_visible: false` — an
isolated blinded adjudication that never saw the other reviews, the model
identity, or the desired outcome. A deciding tie-break resolves 2-of-3 and the
minority review is retained. If the tie-break review finds the frozen rubric
ambiguous or self-contradictory it records `RUBRIC_AMBIGUITY`: the target stays
unresolved with HUMAN_REVIEW_REQUIRED, majority voting never overrides an
invalid rubric, and no further reviewer calls are made. Three reviewers per
target is the maximum; re-reviewing an agreed decision, a second tie-break, or
a fourth reviewer is rejected.

Reviewer independence boundary: two or three isolated reviewer calls from the
same model family are independently isolated blinded adjudications, not a
statistically independent human population. Reports and public documentation
must not describe them as independent human review, an independent evaluator
population, or statistically independent annotators. Retained evidence from
older frozen snapshots stays immutable; re-adjudicating retained raw reviews
under this rule requires a new linked event with unchanged reviewed bytes and
rubric hash and is recorded there, never silently.

### Setup and fixed-screen uncertainty

`welp-setup` checks a pre-scoring freeze of representative response classes,
task-to-class mapping, disjoint calibration examples, ordered bounded ceiling
ladder, answer headroom, maximum token/wall-time cost and separate operational
SLO. Calibrate each claimed response class; four short-answer examples do not
qualify long synthesis or multi-step tool work. No universal semantic token
floor is established. Preserve a bounded UNKNOWN when no candidate completes.

`welp-setup` 0.2 adds a bounded mechanical sanity layer under the
representativeness review. Each response class freezes its expected answer
geometry ({min_tokens, max_tokens, basis}, derived from the fixture rubrics),
an explicit reasoning-bearing flag, and a named upper-geometry calibration
example. check_setup fails closed before scored inference when the selected
ceiling cannot hold the declared answer structure (geometry maximum plus the
class answer budget), or when the upper-geometry calibration example's visible
answer falls below the declared minimum at the frozen conservative conversion
(two characters per token). Reasoning consumption never fails calibration —
floors read the visible answer only. A genuinely concise class keeps a small
ceiling; floors come only from the class's own frozen declarations, never a
universal default. When the mechanical evidence contradicts the
representativeness review, setup fails closed rather than silently choosing
one.

Bind exact outgoing messages, system prompt, rendered prompt/template, sampler,
requested/effective reasoning and runtime/profile identity. Review prompt
answerability before scoring: a supplied-evidence-only instruction cannot
silently replace an open-knowledge task. Hash equality alone does not detect a
contradictory prompt. Qualified uncached measurements require repeated full
prompt processing evidence; unavailable cache counters cannot be called zero.

Reliability remains **20 unique fixed tasks**, repeated at two base seeds and
at most one preregistered extra seed. Report requested, complete, truncated,
other-incomplete, PASS, FAIL, NOT_EVALUABLE and evaluable counts by category,
seed and lane. Report pooled rates separately from equal-weight seed means.
The sparse screen is not an IID task-population sample; thresholds are
provisional policy, not statistically calibrated population guarantees.
One-task-flip and leave-one-seed-out decision sensitivity on the **base seeds
only**, after required review resolves, trigger the single bounded extension.
An untriggered extra seed is invalid evidence; a triggered but missing seed
blocks a readiness verdict. Retain all runs and residual sensitivity after
the cap; never rerun until a favorable decision appears.

### Coverage is not capability

`welp-context` 0.3 separates required rung/seed/lane inventory, execution
validity, useful capability and lane-specific useful maximum. Valid measured
negative results can complete coverage without validating any useful rung.
Missing or invalid required evidence cannot support COMPLETE_PASS. The
Controlled Context fixture 1.3 (legacy ID: Family A 1.3) retains controlled
facts and final-token placement, but uses the canonical answer oracle,
including valid numbered and comparative forms; ambiguous
free-form answers require review rather than a silently permissive substring
rule. Full-window performance and placement evidence are still required.

Answerless budget exhaustion is a measured outcome, not a gap (2026-09-24
Granite D-01 repair): an execution-valid Controlled Context cell that
exhausts its generation budget and emits no visible answer is represented as
a `BUDGET_LIMITED` cell with the CP-1 triple semantic `NOT_EVALUABLE`,
completion `FAIL_LENGTH`, budget `EXHAUSTED_IN_REASONING` when the
declared/effective reasoning surface is ON (UNKNOWN when attribution is
unsupported). Such a cell covers its cell — a complete negative result never
makes the campaign structurally incomplete — while never validating
capability: a budget-limited practical rung stays PARTIAL, and
`useful_context_max`/`practical_rung_validated` still require trusted
`VALIDATED` cells. The bundle accepts an answerless measured row only when
the raw record proves the terminal generation state and the evidence binds
the empty-answer sha256; anything else fails closed. Reasoning consumption
itself is not a semantic failure, an unsafe behavior or missing coverage.

The supplementary multi-document fixture tests distributed facts, conflicting
versions, source-grounded synthesis and absent information. It does not turn
Controlled Context into a codebase or long-session benchmark. Real-work 0.2 adds bounded
Linux/config/log diagnosis and a read-only tool simulator with disclosed
discovery information, sequential results, recovery and grounded termination.
Score observed transcripts, not hypothetical successful tool responses.
Repository checks still require an isolated disposable execution environment.
A missing fixture or unrun applicable role is NOT_TESTED, not NOT_APPLICABLE.

Source attribution requires the right evidence, not one exact registry string
(2026-09-24 hardening II): cited source references resolve when they are the
frozen id, or an unambiguous word-boundary extension or truncation of exactly
one frozen id, in Linux Diagnosis and Multi-Document Context alike. Glued,
paraphrased or ambiguous citations keep failing mechanically — ambiguity is
never guessed, and contradiction, grounding and safety requirements are
unchanged.

### Measurement and evidence integration

`welp-measurement` retains individual repetitions and separates excluded warmup,
cold-start and warmed runs. Report sample count, mean, sample SD, median,
min/max and coefficient of variation. Its default warmed policy is one excluded
warmup plus five measurements; a preregistered dispersion trigger permits only
one additional fixed batch, retained in full. A large spread does not establish
its cause; aggregate-only historical results cannot recover missing samples.
Distinguish first streamed content token, completed nonstreaming response,
end-to-end latency, native prefill and explicitly labeled proxies.

The WELP-side LLMGauge adapter reads existing producer formats. Compatibility
requires verified artifact/runtime/build/hardware/offload/KV/workload/context,
cache, metric boundary/unit, repetitions policy and raw provenance. Missing
facts remain unavailable or NON_COMPARABLE; caller expectations never create
measurements. Small LocalMaxxing workloads are not full-window WELP evidence.
Neither project becomes dependent on the other.

The prospective evidence-bundle validator rederives reliability, context and
classification from hash-bound evidence and renders the same derived record.
Classification 0.4 uses closed dimension vocabularies, separates complete
negative execution from capability, and blocks unresolved deciding review.
READY additionally requires adequate operational budget evidence, complete
required coverage and the practical context rung. A caller-asserted dimension
or `selftest: PASS` cannot replace this evidence.

### Historical qualification

The retained LFM prospective retest exposed confirmed development defects:
git-task FAIL was promoted to unsafe behavior; its campaign-local Family A
oracle rejected correct 8K answers; tool discovery information was hidden; and
Linux non-execution was described as inapplicability. These findings qualify
those specific interpretations, not all retained measurements. They do not
establish a replacement LFM classification. Preserve the original event and
attach any authorized public erratum transparently; never silently rewrite
scores, reports or registry events. No model campaign or LocalMaxxing action
is part of protocol hardening.

## Reasoning profiles (prospective 2026-09-25 revision)

This is a **methodology change, DRAFT / NOT v1.0**. The parent is
`welp-next-snapshot-2026-09-24-context-outcome-repair`. Old snapshots,
campaigns, raw answers and published verdicts remain immutable. Contract:
`welp-reasoning-topology-0.1.0-draft`; validator rules R18–R21 apply to
campaigns under snapshots dated 2026-09-25 or later; historical single-profile
events remain valid unchanged under their frozen snapshots.

WELP evaluates models as the **deployment configurations they actually
expose**. A model whose reasoning can be genuinely turned on and off is a
different practical deployment depending on that switch, and one classified
profile does not answer for the other. Motivating evidence: Ling-3.0-tiny ran
a complete, valid Reasoning On campaign while `enable_thinking=false` was
proven to produce effective OFF behavior that was never characterized — the
campaign answered "how does this model behave with reasoning ON" but not
"how does it behave when legitimately deployed with reasoning OFF".

### Reasoning topology qualification

Every prospective campaign first determines the model's actual reasoning
topology **experimentally on the pinned runtime** — the request field alone
never qualifies a control — and records it in a hash-bound qualification
record bound to the campaign manifest:

| Case | Meaning | Required profiles |
|---|---|---|
| A | No reasoning mode | Standard |
| B | Reasoning present, cannot be disabled | Reasoning On; OFF recorded unavailable / ineffective / unsupported |
| C | Effective supported ON/OFF control exists | Reasoning On **and** Reasoning Off |
| D | Additional effort levels exist (low/medium/high/budget/depth) | Base case (A/B/C, recorded) plus the bounded effort-level policy |

Display names: **Standard**, **Reasoning On**, **Reasoning Off** (machine
profile IDs `standard`, `reasoning-on`, `reasoning-off`; a promoted effort
level uses `reasoning-<level>`).

### ON/OFF profile requirement

When a genuine supported ON/OFF control exists (case C), Reasoning On and
Reasoning Off are **separate required WELP deployment profiles**, published as
linked sibling profile events of one model. Each receives independent profile
identity, setup, calibration, response ceilings, prompt/control binding,
reliability, safety, real-work results, context results, performance, evidence
bundle, classification and deployment guidance. Neither is run as a
diagnostic-only afterthought. Requested-but-ineffective OFF controls never
create a Reasoning Off profile (case B); no fake profiles.

Where applicable the **same frozen model-agnostic task set** is used across
profiles so results stay directly comparable; profile-specific setup and
calibration may differ, and fixture difficulty is never altered because one
profile performs poorly. Reasoning On may legitimately need much larger
budgets; Reasoning Off may legitimately select smaller ceilings — that
difference is useful deployment evidence.

### Profile-invariant vs profile-specific evidence

Genuinely profile-invariant records — model source identity, license, artifact
SHA-256, quant identity, architecture, runtime commit/build, physical
hardware, pure load/fit qualification, unchanged template identity, artifact
provenance — may be shared, but only when explicitly marked
(`profile_invariant_evidence`, hash-bound, provenance-recorded). Behavioral
evidence — effective reasoning state, calibration, generation ceilings,
operational budgets, scored outputs, reliability, semantic completion, safety
task outcomes, Assistant Quality, Structured Output, Tool Recovery, Linux
Diagnosis, Repository Repair, Multi-Turn Correction, Document Synthesis,
Controlled Context, Multi-Document Context, generation performance, latency,
token consumption, and the final classification — is **profile-specific** and
is never shared merely because artifact, runtime and hardware are identical.
Cross-profile behavioral binding fails validation closed.

### Per-profile classification; no averaging

Each full reasoning profile gets its own independently derived
classification. Divergent verdicts are legitimate and preserved verbatim.
Averaging, merging, scoring, or verbally collapsing distinct profile
classifications into one artificial model-level score is **prohibited**. A
model-level summary may state the publisher/default profile and the alternate
supported profile(s) and give deployment guidance; it must not flatten them.
The publisher/default profile is recorded explicitly as context; it never
demotes the other supported profile(s) to secondary evidence.

### Bounded effort-level policy (case D)

Additional reasoning-effort levels do not automatically become full profiles
and ordinary characterization never becomes an unbounded configuration sweep.
Each additional ON effort level is qualified prospectively — control
effectiveness, reasoning-token use, visible-answer token use, completion
behavior, latency, response characteristics, publisher deployment guidance —
and is promoted to a full profile only when genuinely supported, measurably
distinct, deployment-relevant, and sufficient to change practical
interpretation. Tiny stochastic differences are never promoted, and post-hoc
"best mode" searching is prohibited. Normal bounds: Standard model 1 profile;
reasoning model without OFF 1 profile; reasoning model with effective OFF 2
profiles; additional effort profiles exceptional and prospectively justified.

### Performance, context, safety and real work by profile

Performance is measured independently where reasoning state affects
generation: prefill where applicable, decode, answer latency, reasoning-token
cost, visible-answer tokens, completion rate, TTFT / first visible answer when
measurable, VRAM where materially different, and context behavior. Where
technically measurable, distinguish time to first generated reasoning token,
time to first visible answer, and total completion latency; never compare only
raw decode tok/s when one profile spends thousands of tokens reasoning before
exposing an answer. Controlled Context and Multi-Document Context are
characterized separately per profile (coverage, capability, useful-context
maximum, practical rung, hardware/runtime envelope). Safety is profile-specific
behavioral evidence: a refusal or unsafe behavior under Reasoning On does not
determine Reasoning Off; required safety tasks run under each full profile
with current blinded adjudication rules. Required real-work modules run
independently per profile; diagnostic-only surfaces keep their status; no
module is selectively skipped on the alternate profile.

### Architecture and historical compatibility

One WELP campaign event per full reasoning profile (linked sibling profile
events sharing a reasoning group ID), chosen over one campaign with multiple
internal bundles because per-event evidence, validation and publication
machinery already exist, manifests never need post-hoc edits when a sibling
completes, and the central registry already presents multiple profiles per
model with explicit links. Independent classifications, shared invariant
identity where appropriate, obvious linkage, deterministic validation,
backward compatibility and understandable public output are all preserved.
Historical campaigns (Granite, Ling original, LFM, Spark, Bonsai and every
other one-profile event) remain valid under their frozen methodologies; old
reports never need invented Reasoning Off results.

## WELP Model and WELP Agentic (prospective 2026-09-25 model-agentic revision)

This is a **methodology change, DRAFT / NOT v1.0**. The parent is
`welp-next-snapshot-2026-09-25-reasoning-profiles`. Old snapshots, campaigns,
raw answers and published verdicts remain immutable. Contract:
`welp-agentic-0.1.0-draft`; harness `welp-agentic-harness/0.1.0-draft`
(`harness/agentic.py`); task record schema `welp_agentic_task.schema.json`
(`welp-agentic-task-record/1`). Validator rules R22–R24 apply to campaigns
under the exact snapshot `welp-next-snapshot-2026-09-25-model-agentic`, under
any later-dated snapshot, or wherever a manifest explicitly adopts the
`welp-agentic` contract — deliberately NOT date-only gating, because this
snapshot shares its date with reasoning-profiles and reasoning-era campaigns
never recorded section dispositions.

### One protocol, two sections

WELP comprises two sections. Both belong to ONE protocol and every current
campaign summary shows both explicitly.

**WELP Model** asks: how capable, reliable and useful is the tested local
model profile? It retains the existing coverage: Reliability and Safety,
Assistant Quality, Structured Output, Tool Recovery, Linux Diagnosis,
Repository Repair, Multi-Turn Correction, Controlled Context, Multi-Document
Context, Reasoning Profiles, and Performance/deployment geometry.

**WELP Agentic** asks: can that model, through a specified agent harness,
independently complete bounded tasks using tools and environment feedback?
It measures autonomous execution: discover → decide → act → observe →
recover → verify → finish. Model tests may supply relevant inputs directly
and examine bounded skills; Agentic tasks require the tested model to
discover and execute the work through tools. The Model suite is not
duplicated inside Agentic.

Each section has its own execution status, its own evidence-backed results,
and its own applicability and limitations. **Averaging of Model and Agentic
verdicts is prohibited.** A negative Model verdict does not automatically
prohibit Agentic testing; a real integration or sandbox-safety blocker
prevents execution and is reported as `INTEGRATION_BLOCKED`, never as a
model verdict. A completed negative Agentic task is a successfully executed
measurement, not a broken experiment.

### Agentic configuration binding and profile honesty

WELP Agentic initially tests ONE explicitly selected qualified model profile
under a **predeclared selection rule**, recorded before any Agentic task
output is seen. Prefer the publisher/default profile unless the preregistered
rule selects another profile for the intended role; never select whichever
Agentic result looks best afterward. An alternate reasoning mode may be
tested as a separately declared extension, and is not automatically another
full Agentic suite; untested modes remain explicitly untested for Agentic
behavior. Agentic inherits verified model/artifact/runtime/hardware identity
(see profile-invariant evidence) — it does NOT inherit behavioral results
from Model.

Every Agentic run binds and freezes: parent model-profile ID; harness
implementation and commit; tool schemas and parser; agent system
instructions; effective reasoning/sampling settings; context handling and any
compaction; permissions and sandbox image; retries, execution limits and
stopping policy. An agent system prompt is not identical to a normal
assistant prompt — record the difference instead of claiming the entire
profile is unchanged. Results describe the **MODEL + HARNESS + ENVIRONMENT**
combination, and wrong-profile or wrong-harness evidence is rejected.

### The three initial tasks

The initial suite is three bounded tasks using existing machinery where
suitable — not another standalone agent product or evaluation framework:

1. **Repository** — a small repository with a bounded defect/request: the
   agent inspects, locates the issue, edits, runs tests, responds to
   reviewer feedback, verifies the final state and reports what actually
   happened.
2. **System** — a broken service/configuration in a disposable sandboxed
   environment or faithful stateful simulator: the agent gathers evidence,
   applies an authorized repair and verifies it. No live host or service
   changes.
3. **Research** — a question plus a frozen local source collection: the
   agent locates relevant sources, resolves conflicting/outdated evidence,
   produces the requested artifact and cites supporting evidence. No live-web
   dependency in the scored fixture.

Task content differs from any Model task whose solution the evaluated agent
has already seen; shared infrastructure is acceptable, solution leakage is
not. All needed information must be discoverable through documented tools —
no hidden paths, undocumented arguments, or unstated goals. No single exact
tool sequence is required unless dependencies or permissions genuinely impose
one; different valid solutions remain valid.

### The runner must not rescue the agent

The tested model chooses the actions. The harness executes the model's
declared tool operations and returns observations; it must not choose the
next repair, invent missing arguments, reinterpret an incomplete patch into a
correct solution, provide answer-specific hints, silently repair malformed
output, or claim verification the model never performed. Accepted edit
formats and parser behavior are frozen and documented before testing, and
deterministic adapter behavior is logged. The canonical harness ships two
declared adapters — a strict JSON text envelope (with a logged, declared
fence-tolerance step) and native OpenAI-style tool calls through the
endpoint — and the whole-file `write_file` interface; the chosen
`tool_call_adapter` is part of the frozen configuration and must be
qualified on the tested model during non-scored qualification before any
scored task (a model whose chat template carries native tool calls is
measured through that actual deployment path, never forced through an
adapter its training rejects). No stronger model may plan, debug, or complete the
evaluated model's task; reviewers judge evidence and never participate in
execution. Any human/evaluator assistance is recorded and can never become an
unassisted completion.

### Attempt and budget policy

Default initial coverage: three distinct tasks, one initial attempt each;
repetitions are prospectively justified and strictly bounded. Normal
retry/debug actions within an attempt are agent behavior; restarting the
whole task is a separate attempt and never erases failure. Practical limits
(total wall time, total generated tokens, per-request ceiling, maximum tool
calls/turns, command timeouts, retry policy, CPU/RAM/disk limits) are frozen
per task from **non-scored disjoint qualification**, never copied from
one-turn Model ceilings and never enlarged after seeing scored failures.
Capability, completion and resource cost stay distinct — a time/token limit
is recorded as budget exhaustion, not automatically semantic failure. Agentic
overhead is recorded separately from Model testing; downloads, fit ladders,
context sweeps and speed benchmarks are not repeated merely because Agentic
runs.

### Sandbox and permission boundaries

Isolation is **proven before executing model-generated actions** (the
canonical harness probes positive-control plus network/DNS absence, host
file absence, evaluator-file absence and write-containment). Sandboxes are
disposable and unprivileged: no credentials, personal home mounts, real
project write access, production data/services, host Docker socket, or
unrestricted network. Model tools stay offline; only the controlled runner
communicates with the qualified local inference endpoint. Evaluator-only
tests, reference solutions and expected outputs live outside the sandbox.
Denied actions are recorded without allowing damage; no real Git publication,
host package installation or infrastructure change happens inside scored
tasks. The evaluation runner's own authorized publication actions are separate
from the tested model's permissions.

### Scoring what actually happened

Primary Agentic evidence: final environment/artifact state; executable
outcome checks; the actual tool transcript with exact commands, outputs and
exit statuses; preserved before/after files; verification actions the model
itself performed; and the final report versus observed facts. Every result
reports: task completed or not; completed without assistance or not;
correctness and preserved constraints; observed unsafe/prohibited actions;
recovery and repeated errors; false completion claims; total steps, tokens
and elapsed time; stop reason. Task success, truthful reporting, safety and
efficiency are kept separate — a convincing completion message never
substitutes for task completion. Mechanical oracles where defensible; the
existing maximum-three-reviewer blinded procedure where interpretation is
genuinely required (two agreeing reviewers decide; one tie-break on a
genuine split; rubric ambiguity stays unresolved). Per-task outcome
vocabulary is exactly `PASS | FAIL | NOT_EVALUABLE` plus the separate
assistance, unsafe-action, false-claim, budget and stop-reason fields — no
new score hierarchy. Three tasks are a bounded task sample, not a
certification of general autonomous reliability: a 3/3 result is reported as
3/3 tested tasks.

### Applicability, completion and historical migration

Every current campaign summary explicitly shows both sections with an Agentic
disposition of exactly `COMPLETED` (evidence-backed), `INAPPLICABLE` (with
evidence), `INTEGRATION_BLOCKED` (with cause), or `NOT_TESTED`. No missing
section; no Agentic PASS inferred from Model results. Lack of a native
function-calling interface does not prove every agent interface is
unsupported — the chosen harness's actual path is evaluated, and any
text-tool adapter is itself qualified and recorded. Missing test
infrastructure is `NOT_TESTED` or `INTEGRATION_BLOCKED`, never a negative
model verdict. Campaign-group completeness is defined from required profiles
and applicable sections: a completed Model section is never erased by an
Agentic issue, but the group cannot claim complete required testing while a
required Agentic section is unresolved. Ordinary failed agent tasks are
never relabeled methodology blockers.

Historical Model-era events do not acquire Agentic results retroactively.
Historical agent evidence — the WLEP-era `welp-omp-local-agent` module
(4 oracle-validated fixtures plus one 2-fixture OMP-CLI calibration run,
retained under `research/methodology/wlep-development/phase5-hardening/omp/`;
its indexed contract and scorer files were never present in `welp/contracts/`)
— is reusable only where its actual task/harness/profile/oracle boundaries
support the claim: it proves harness mechanics, not any current model's
Agentic capability. Campaigns document the old-to-new section mapping,
compatible identity/evidence reuse, methodology-incomparable results, newly
required measurements, and current-versus-historical public presentation.

Each new Agentic task requires, before scored use: a trusted reference
execution that succeeds; alternate valid execution where appropriate; no-op
and wrong-result cases that fail; false-success, forbidden-edit and
missing-verification cases; correct-recovery and unrecovered-error cases;
bounded token/time/tool exhaustion; and harness failure separated from model
behavior — exercised through the actual runner. Selftests use trusted fixture
code only; untrusted model actions execute only in the qualified disposable
sandbox.

## Canonical contracts (current)

- `welp-outcomes` 0.1.0-draft (task outcome semantics; new)
- `welp-generation-budget` 0.1.0-draft (budget policy, reserve, cache; new)
- `welp-deployment-lanes` 0.1.0-draft (prospective budget/prompt identities,
  calibration, conclusion lanes and resource reporting)
- `welp-reasoning-topology` 0.1.0-draft (Reasoning Profiles: topology
  qualification, ON/OFF profile requirement, effort-level policy, evidence
  binding, no-average rule; new)
- `welp-agentic` 0.1.0-draft (Model/Agentic two-section structure; Agentic
  configuration binding, initial three tasks, runner no-rescue rules,
  sandbox boundaries, scoring and disposition vocabulary; new)
- `welp-practical-viability` 0.1.4-draft
- `welp-reliability` 0.3.0-draft (scorer v3, independent safety, paired lanes and bounded fixed-screen sensitivity)
- `welp-context` 0.3.0-draft (canonical Controlled Context answer oracle, machine ID Family A; coverage/execution/capability axes with answerless budget exhaustion as a covered measured row; full-window requirements remain in `context-scaling.md`)
- `welp-optimization` 0.1.0-draft
- `welp-stability` 0.1.0-draft
- `welp-final-classification` 0.4.0-draft (evidence-derived dimensions, coverage/review blockers and selected DEPLOYMENT profile)
- `welp-real-work` 0.2.0-draft (role applicability, diagnosis, observed tool execution and complementary synthesis)
- `welp-safety-review` 0.1.0-draft
- `welp-setup` 0.1.0-draft
- `welp-measurement` 0.1.0-draft
- `welp-evidence-bundle` 0.1.0-draft
- `welp-preflight` 0.1.0-draft
- Phase 5 module contracts (indexed in `contracts/welp-modules.json`): `welp-coding`, `welp-structured-interfaces`, `welp-native-tools`, `welp-extraction-rag`, `welp-reasoning`, `welp-linux-systems`; `welp-omp-local-agent` is retained as HISTORICAL provenance only (its indexed contract/scorer files were never present; superseded for Agentic-section work by `welp-agentic`).

## Stabilization accounting (superseding rule, 2026-09-25 model-agentic revision)

Stabilization counts only fresh-model campaigns. The following rule supersedes
any earlier accounting that counted a methodology-validation run as a clean
stabilization campaign (a superseding record lives in
`summaries/stabilization-accounting.json`; historical reports stand as
historical):

- **METHODOLOGY_VALIDATION** is the known-model run that validates a newly
  frozen methodology revision (for the model-agentic snapshot: the Ling
  Reasoning Off Agentic validation on the RTX 5070). It is NEVER clean
  campaign 1 and never increments the count.
- Repair completions, reused/re-derived campaigns, two reasoning profiles of
  one model, and repeated hardware runs never inflate the count.
- After a freeze and successful methodology validation:

  ```
  STABILIZATION_BASELINE: <new snapshot>
  METHODOLOGY_VALIDATION: PASS
  CLEAN_STABILIZATION_CAMPAIGNS: 0 / 5
  ```

- Only a qualifying fresh-model campaign that starts AFTER the freeze under
  the unchanged frozen method and completes all required profiles and
  applicable sections increments the count. A negative model verdict can
  count as clean methodology execution; a campaign requiring a methodology
  revision cannot. Non-semantic runner/reporting fixes may be recorded
  separately; changing scoring or experimental meaning is not a minor tooling
  exemption. The first fresh campaign is never started automatically.

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
- `welp_setup.schema.json` (prospective calibration, prompt and cache setup)
- `welp_agentic_task.schema.json` (`welp-agentic-task-record/1`; Agentic task
  attempt record: transcript, commands, sandbox state, outcome checks)

## Canonical harness, scorers, and fixtures (current)

- `harness/` — canonical versioned phase implementations: outcomes, admission, quality, reliability, capabilities, context and classification; prospective setup, measurement import and evidence-bundle integration. Campaign wrappers call these implementations, never fork their scoring semantics.
- `harness/agentic.py` (`welp-agentic-harness/0.1.0-draft`) — canonical Agentic runner: bwrap sandbox with proven isolation, declared text-tool adapter, frozen-limit turn loop, mechanical evaluation; `fixtures/agentic/{repository,system,research,qualification}` — frozen initial task fixtures with evaluator-only acceptance code (qualification is non-scored bounds calibration).
- `fixtures/reliability/welp-reliability-sample-20-v3.json`, `fixtures/useful_context/{family-a,multidocument}.json`, `fixtures/quality/welp-quality-screen-12-v1.json`, `fixtures/real_work/{tool-recovery,linux-diagnosis,multi-turn-correction,document-synthesis,repository-timeout}.json` — freeze exact versions/hashes before outputs; applicability varies by role.

## Canonical validator (current)

- `validators/validate_campaign_welp.py` — version-aware historical compatibility; R09–R14 from 2026-09-19, R15/R16 from 2026-09-23, evidence-bound hardening (R17) from 2026-09-24, and reasoning-profile rules R18–R21 from 2026-09-25, and Model/Agentic section rules R22–R24 from the model-agentic snapshot (exact-snapshot/later-date/contract-adoption gating). It checks machine-verifiable evidence and review provenance, not independent truth of qualitative judgments.
- `validators/validate_publication.py` — current immutable citations, scientific IDs,
  shared relationships, and profile-path consistency; legacy URL exports remain accepted.
