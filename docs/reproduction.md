# WELP Campaign Reproduction (canonical)

## Operator checklist

1. **Preflight (mandatory at campaign START).** Run `welp-preflight` per `summaries/welp_preflight_0.1.0`:
   - HARDWARE: GPU identity, host safety rules, telemetry.
   - TOOLCHAIN: discover installed runtimes, apply DISCOVER-FIRST/REUSE/NEW_RUNTIME_REQUIRED rule.
   - MODEL: producer claims + applicability per [[WELP Phase Structure]].
   - PUBLICATION: LocalMaxxing auth (READY / AUTH_BLOCKED / CLI_INCOMPATIBLE / NOT_APPLICABLE).
   - SAFETY: GPU & Host Safety Rules, stop-on-Xid.
   - OUTPUT: durable long-job paths declared absolute and fail-closed.
2. **Cache-metric probe.** One disjoint-prompt probe per selected runtime; record `CACHE_METRIC_TRUSTED | CACHE_METRIC_FLOOR_PRESENT | CACHE_METRIC_UNAVAILABLE | UNKNOWN` in `toolchain/runtime_capabilities.json`.
3. **Phase progression.** Apply [WELP](../protocol/WELP.md); the vault Phase Structure is a human-readable mirror, not an alternative canonical source. Preserve early safety/quality stops and report resulting coverage gaps.
4. **Phase 3 gate reasoning state.** Declare `gate_baseline_reasoning_state` + REQUESTED/EFFECTIVE before any generation. For methodology-revision-era campaigns: freeze the generation-budget policy per `welp-generation-budget` (per-task `answer_budget` + rationale, lanes), record only reasoning controls proven effective on the pinned runtime, emit CP-1 outcome triples per task (`welp-outcomes`), and verify the reliability scorer self-test (`python3 scorers/score_reliability.py selftest`) plus the acceptance rescore before live use. Scientific arms run cache-disabled and verified uncached; record `cache_policy` in the manifest.
   For snapshots dated 2026-09-23 or later, also freeze `welp-deployment-lanes`:
   exact MINIMAL/DEPLOYMENT prompt bytes and SHA-256, profile/template/sampler,
   any materially different PUBLISHER lane, and optional preregistered
   OPTIMIZED lane. Choose a bounded semantic ceiling from disjoint nonscored
   calibration before scored answers; operational ceilings follow the real role
   SLO, not the semantic ceiling. Record completion, reasoning/answer tokens,
   time and cost separately by lane. `welp-final-classification-0.3.0-draft`
   requires one selected profile for every verdict dimension.
5. **Phase 5 module applicability.** Freeze `phase5_applicability.json` before any Phase-5 execution.
6. **Long-job durability.** Absolute path declared first; existence + row count + SHA-256 verified after exit; only then COMPLETE.
7. **Context characterization (mandatory coverage accounting).** Freeze the [Context Scaling](../protocol/context-scaling.md) method revision/hash and answer the checklist below before context testing; finalize every row in the [model-card coverage table](../lab-record-template/README.md#model-card-context-coverage), including untested ranges. Capacity admission alone is not validation; practical default selection is not a context stop condition.
   Prospective Family A uses `harness/context.py:construct_family_a` with a
   callback that applies the pinned inference chat template/BOS and returns
   final token count and each fact's token offset. Retain the bounded
   placement attempts, verify final preflight/inference token equality, and
   reserve the chosen generation ceiling independently per lane; a 512-token
   semantic reserve is not universal. Freeze separate multi-document,
   repository and session tasks when making those claims.
8. **LocalMaxxing completion disposition (mandatory).** Once the canonical practical profile is selected, evaluate LocalMaxxing eligibility per [WELP](../protocol/WELP.md#localmaxxing-completion-disposition). If eligible: freeze the canonical benchmark command and actual prompt, run the current official LocalMaxxing method, validate the local result, search for an exact existing submission, and submit during campaign completion when submission access works. Record `summaries/localmaxxing.json` with exactly one status (`SUBMITTED` with origin `NEW`/`VERIFIED_EXISTING` and the submission reference, `MEASURED_NOT_SUBMITTED`, `NOT_ELIGIBLE` with the demonstrated representation limit, or `BLOCKED` with the exact blocker), the canonical profile identity, configured context, actual prompt tokens, and the result summary. This step is the explicitly authorized external-submission exception; a generic "no external submission" rule must not suppress it, and it authorizes no other external action.
9. **Final classification.** `harness/classification.py` derives the verdict from the evidence bundle. Report practical-profile selection separately from model-card context completeness; do not infer the latter from a classifier result. A blocked methodology campaign has no verdict without an independently demonstrated integration blocker.
   Preregister role applicability and real-work fixtures per
   `contracts/welp-real-work-0.1.0-draft.json`. Native tool calls require an
   effective interface and sequential state/error recovery, not a text-only
   imitation. Execute model-authored repository changes only in an isolated
   disposable sandbox; compare against executable tests and inspect unrelated
   diffs. For writing, diagnosis and synthesis retain factual oracles,
   uncertainty checks, a blind qualitative rubric, and any disagreement.
   Distinguish WELP campaign evidence from optional LLMGauge measurements;
   no historical event gains prospective labels retroactively.
10. **Validation.** `validate_campaign_welp.py <campaign_dir>` MUST exit 0. It does not enforce the new narrative context-coverage gate: review the table and evidence explicitly.
11. **Standard Completion Package.** Produce `REPORT.md` (primary scientific report), `WELP-LAB-RECORD.md` (standardized Lab Record companion), `WELP-CONFORMANCE.md`, `protocol-findings.md`, all machine-readable summaries including `summaries/localmaxxing.json` and the public-safe website-publication export `summaries/website-publication.json` with its explicit disposition — and, when requested, a `<campaign-slug>-review-report.md` human summary under the campaign bundle `<campaign>/reviews/` that links back to the primary report. Do not create `report.md`; see the [report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy). Include context coverage and outstanding work even after an early stop.
12. **Publication routing.** Follow the
    [four-layer publication contract](publication.md): local `research/model-evaluations/`
    holds working/raw science; `WumboLabs/evaluations` holds public scientific
    evidence; `wumbolabs.dev/evaluations/` is human discovery/share; the NAS archive
    holds large model artifacts. Obsidian remains the internal operational handbook.
    LocalMaxxing disposition rules in step 8 are unchanged. Current exports identify
    model/profile/event and immutable central repo/full-commit/path. Never create a
    new `eval-*` repository. Pushes and website deployment run under the campaign's
    standing automatic-closeout authorization (success branch of the WELP
    execution-state lifecycle) or explicit human authorization.

## Model-card context checklist

Freeze the plan before testing; replace planned entries with measured results or
explicit dispositions before reporting:

1. What does the authoritative official model card/config claim? Pin sources, revisions/hashes, and exact token units.
2. What is the exact native maximum? Include its own mandatory disposition row.
3. Is there an official extension mechanism? Pin documentation and verify requested versus effective mechanism configuration; a large context flag is insufficient.
4. What is each extension's exact documented maximum? Include a separate mandatory row per official surface, or source-backed absence of an extension.
5. What proportional major rungs and exact maxima will be tested? Freeze fit/accounting, safety constraints, reserve, output budget, template/tokenizer, seeds, and gates.
6. Which rows are capacity-only? Label capacity admission without implying full-context validation.
7. Which rows are near-full occupied? Report final rendered input tokens / usable prompt budget, >=97% hard floor / >=99% preferred, output reserve, safety allowance, and full-occupancy performance/resource evidence.
8. Which rows have useful-context validation at that near-full occupancy? Verify measured 2/25/50/75/95 depths (<=0.50 percentage-point error, <=0.25 preferred), highest-runnable native/extended seed requirements, and separate request/observation counts.
9. What remains untested or partial? Record every gap, demonstrated fit/integration limit, evidence path, and deferral reason; never silently omit an advertised range.
10. Is model-card context coverage complete? Only all completed required rung/maxima dispositions permit CONTEXT CHARACTERIZATION COMPLETE. PRACTICAL PROFILE SELECTED or PRACTICAL BASELINE CHARACTERIZED may precede this gate.

## Report artifact checklist

Before completion, verify:

1. Exactly one CURRENT primary `REPORT.md`?
2. Lab Record named `WELP-LAB-RECORD.md` (not `report.md`)?
3. No ambiguous `report.md` companion present?
4. Does every companion point to the current `REPORT.md`?
5. If a prior attempt was superseded: quarantined under an unmistakable `-prior-attempt-quarantined/` path, excluded from current claims, with quarantine path, reason, and any data reuse recorded in `REPORT.md`?
6. Are current/superseded statuses explicit in every report's role header?
7. Are request/arm fingerprints internally consistent where applicable?

## Compatibility

- Historical campaigns reproduce unchanged against their frozen snapshot.
- New WELP campaigns use the current WELP snapshot and WELP-named contracts.
- The validator accepts frozen historical campaign artifacts where needed.
- Current-facing publication uses WELP terminology. Frozen identifiers stay exact.

## Out of scope here

- git init, LICENSE selection, and the initial public push (human)
- New model campaign execution
- LLMGauge / runtimes / model binaries
