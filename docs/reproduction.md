# WELP Campaign Reproduction (canonical)

## Operator checklist

1. **Preflight (mandatory at campaign START).** Run `welp-preflight` per `summaries/welp_preflight_0.1.0`:
   - HARDWARE: GPU identity, host safety rules, telemetry.
   - TOOLCHAIN: discover installed runtimes, apply DISCOVER-FIRST/REUSE/NEW_RUNTIME_REQUIRED rule.
   - PROTOCOL: record the frozen snapshot_id and current Context Scaling revision/hash; preserve exact historical snapshot identities when reproducing earlier campaigns.
   - MODEL: producer claims + applicability per [[WELP Phase Structure]].
   - PUBLICATION: LocalMaxxing auth (READY / AUTH_BLOCKED / CLI_INCOMPATIBLE / NOT_APPLICABLE).
   - SAFETY: GPU & Host Safety Rules, stop-on-Xid.
   - OUTPUT: durable long-job paths declared absolute and fail-closed.
2. **Cache-metric probe.** One disjoint-prompt probe per selected runtime; record `CACHE_METRIC_TRUSTED | CACHE_METRIC_FLOOR_PRESENT | CACHE_METRIC_UNAVAILABLE | UNKNOWN` in `toolchain/runtime_capabilities.json`.
3. **Phase progression.** Apply [WELP](../protocol/WELP.md); the vault Phase Structure is a human-readable mirror, not an alternative canonical source. Preserve early safety/quality stops and report resulting coverage gaps.
4. **Phase 3 gate reasoning state.** Declare `gate_baseline_reasoning_state` + REQUESTED/EFFECTIVE before any generation.
5. **Phase 5 module applicability.** Freeze `phase5_applicability.json` before any Phase-5 execution.
6. **Long-job durability.** Absolute path declared first; existence + row count + SHA-256 verified after exit; only then COMPLETE.
7. **Context characterization (mandatory coverage accounting).** Freeze the [Context Scaling](../protocol/context-scaling.md) method revision/hash and answer the checklist below before context testing; finalize every row in the [model-card coverage table](../lab-record-template/README.md#model-card-context-coverage), including untested ranges. Capacity admission alone is not validation; practical default selection is not a context stop condition.
8. **Final classification.** `classify.py` consumes the evidence bundle deterministically. Report practical-profile selection separately from model-card context completeness; do not infer the latter from a classifier result.
9. **Validation.** `validate_campaign_welp.py <campaign_dir>` MUST exit 0. It does not enforce the new narrative context-coverage gate: review the table and evidence explicitly.
10. **Standard Completion Package.** Produce `REPORT.md` (primary scientific report), `WELP-LAB-RECORD.md` (standardized Lab Record companion), `WELP-CONFORMANCE.md`, `protocol-findings.md`, all machine-readable summaries — and, when requested, a `<campaign-slug>-review-report.md` human summary under `~/Projects/local-llm/tmp/` that links back to the primary report. Do not create `report.md`; see the [report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy). Include context coverage and outstanding work even after an early stop.
11. **Publication routing (separate human authorization required).** Per vault Publication Routing:
    - Obsidian: internal WELP operational handbook.
    - GitHub: canonical public WELP evidence/protocol source.
    - LocalMaxxing: community benchmark/report distribution layer.
    - WumboCore Labs: human-readable WELP Lab Records.

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

- git init, LICENSE selection, and public push (human)
- New model campaign execution
- LLMGauge / runtimes / model binaries
