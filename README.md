# WELP — WumboLabs Evaluation Lifecycle Protocol (repo-candidate)

Public reproducibility package for the **WELP — WumboLabs Evaluation Lifecycle Protocol**.

> Status: **DRAFT**. WELP is not frozen as v1.0. Thresholds marked draft are under empirical validation.

*"Real Hardware. Real Testing. No Hype."*

## Layout

| Path | Contents |
|---|---|
| `protocol/` | protocol notes (phase structure, policies, standards) |
| `contracts/` | versioned evaluation contracts: outcomes, budgets/prompt lanes, real-work applicability, reliability, classification and capability modules. |
| `harness/` | canonical versioned phase implementations, evidence-bound setup/bundle validation and optional measurement import. |
| `scorers/` | reliability scorer v3, evidence-bound qualitative safety review, embedded self-tests and historical acceptance rescore. |
| `fixtures/` | fixed reliability 20-task sample; the Controlled Context fixture (legacy ID: Family A 1.3) and the complementary Multi-Document Context fixture; the Assistant Quality screen; real-work Linux Diagnosis, Tool Recovery, Multi-Turn Correction and Repository Repair fixtures. |
| `schemas/` | Campaign, setup, artifact index, publication, profile, task outcome and toolchain contracts. |
| `hardware-profiles/` | *(see top-level `hardware/`; WELP carries reference runtime identities in `schemas/` + `docs/`)* |
| `docs/` | methodology documentation |
| `examples/` | example campaign records |
| `validators/` | campaign-bundle validator (`validate_campaign_welp.py`, self-test passes) |
| `lab-record-template/` | template for publishing a campaign evidence record |
| `summaries/` | executor-independence + integrity reports (compatibility policy, migration inventory) |

## Core rules

- The testing protocol is fixed before a model is evaluated; a failed gate is a valid result.
- Every canonical run distinguishes REQUESTED vs EFFECTIVE serving configuration; requested flags alone are not proof.
- Single-user baselines run `parallel=1`, `fit=off`; automatic parallelism is never relied upon.
- Every generation-bearing task emits semantic/completion/budget outcomes;
  answerless reasoning is NOT_EVALUABLE, not semantic FAIL. Prospective semantic
  ceilings are bounded and selected from disjoint calibration before scored
  runs; operational role/SLO caps and latency/resource cost remain separate.
- Freeze exact prompt lane, template, sampler, profile and effective reasoning
  control. DEPLOYMENT controls role conclusions; MINIMAL, PUBLISHER and optional
  OPTIMIZED results stay separate. A blocked methodology run has no model verdict.
- Scorers self-test before live gate use (`python3 scorers/score_reliability.py selftest`; `python3 harness/<module>.py selftest`).
- Human-controlled Git operations only.
- [Report artifact hierarchy](protocol/WELP.md#report-artifact-hierarchy): `REPORT.md` is the single authoritative primary scientific report; the Lab Record companion is `WELP-LAB-RECORD.md`; `report.md` is historical-only; superseded prior attempts stay quarantined and never supply current claims.
- [Context Scaling](protocol/context-scaling.md): the Controlled Context
  fixture (legacy ID: Family A 1.3) places targets against the final rendered
  token stream; lane-specific reserves and Multi-Document Context, codebase
  and session results remain distinct. Configured capacity
  is not useful context; practical default selection does not complete the
  model-card envelope.
- [Protocol hardening](protocol/WELP.md#protocol-hardening-prospective-2026-09-24-revision):
  task failure is not unsafe behavior; unresolved deciding review blocks a
  verdict. Context coverage, execution validity, capability and useful maximum
  are independent axes. Twenty fixed tasks repeated across seeds are not an
  IID population sample. Performance imports retain raw provenance and boundaries.
- [Publication operating contract](docs/publication.md): website for human discovery/share; `WumboLabs/evaluations` for public scientific evidence and exact repo/full-commit/path citations; local `research/model-evaluations/` for working/raw science; NAS archive for large model artifacts. Model/profile/event identity is independent of repository boundaries. Never create a new `eval-*` repository.

## WELP snapshots

| Snapshot | Status | Scope |
|---|---|---|
| `welp-next-snapshot-2026-08-26-post-rename` | frozen (DRAFT — NOT v1.0) | First WELP snapshot; naming-only migration. Manifest: `snapshot-freeze/manifest.json` (immutable). |
| `welp-next-snapshot-2026-09-19-methodology-revision` | frozen DRAFT (NOT v1.0); methodology in force | Methodology revision (`methodology_changed: YES`): CP-1 outcome semantics, CP-2 generation-budget policy, reliability scorer v2 + re-derived 20×2 gates, useful-context outcome lanes + standardized 512-token reserve, canonical harness/scorers/fixtures, in-repo classification, validator R09–R14. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-19-methodology-revision/manifest.json`. |
| `welp-next-snapshot-2026-09-21-localmaxxing-closeout-rule` | frozen DRAFT (NOT v1.0); superseded lifecycle rule | LocalMaxxing terminal-closeout and two-stage lifecycle delta (`methodology_changed: NO`); the two-stage rule is superseded by the 2026-09-22 automatic-closeout delta. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-21-localmaxxing-closeout-rule/manifest.json`. |
| `welp-next-snapshot-2026-09-22-automatic-closeout-lifecycle` | frozen DRAFT (NOT v1.0); lifecycle in force | Automatic-closeout execution-state lifecycle delta (`methodology_changed: NO`); no measurement-methodology change. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-22-automatic-closeout-lifecycle/manifest.json`. |
| `welp-next-snapshot-2026-09-22-readme-lineage-documentation` | frozen DRAFT (NOT v1.0); superseded | README snapshot-lineage documentation correction only (`methodology_changed: NO`); retains the 2026-09-19 methodology and 2026-09-22 automatic-closeout lifecycle. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-22-readme-lineage-documentation/manifest.json`. |
| `welp-next-snapshot-2026-09-23-real-hardware-real-testing` | frozen DRAFT (NOT v1.0); superseded profile wording | Bounded semantic/deployment budget lanes, frozen prompt identities, Family A rendered-token placement, real-work fixtures and LLMGauge boundary. Its 0.3.0 classification contract included budget lane in the profile ID; that inconsistency is corrected prospectively by the next snapshot. Manifest remains immutable: `snapshot-freeze/welp-next-snapshot-2026-09-23-real-hardware-real-testing/manifest.json`. |
| `welp-next-snapshot-2026-09-23-profile-identity-clarification` | frozen DRAFT (NOT v1.0); superseded | Semantic/operational budget lanes are distinct measurements of the same selected DEPLOYMENT profile. Classification 0.3.1 binds selected profile to DEPLOYMENT. Parent: 2026-09-23 real-hardware snapshot. Immutable manifest: `snapshot-freeze/welp-next-snapshot-2026-09-23-profile-identity-clarification/manifest.json`. |
| `welp-next-snapshot-2026-09-24-protocol-hardening` | frozen DRAFT (NOT v1.0); superseded | Evidence-bound safety/task separation, classification 0.4, executable context coverage/oracles, class-specific setup, bounded reliability sensitivity, Linux/tool/multi-document fixtures and qualified LLMGauge import. Parent: profile-identity clarification. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-24-protocol-hardening/manifest.json`. |
| `welp-next-snapshot-2026-09-24-review-and-setup-hardening` | **current DRAFT** (NOT v1.0); methodology changed YES; display names introduced | Frozen blinded-review disagreement resolution (one tie-break, 2-of-3, RUBRIC_AMBIGUITY fails closed to human review), welp-setup 0.2 mechanical calibration sanity layer (expected answer geometry, ceiling floor, upper-geometry coherence), unambiguous source-attribution aliasing in Linux Diagnosis and Multi-Document Context, and the clear display-name layer (machine IDs unchanged). Parent: protocol-hardening. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-24-review-and-setup-hardening/manifest.json`. |

Historical campaigns retain their recorded snapshots and are never relabeled.
Compatibility acceptance does not certify a historical interpretation as
scientifically correct: confirmed scoring defects require explicit qualification.
Development replay is supplementary sensitivity evidence, not a replacement
model classification. See `summaries/welp_compatibility_policy.json`.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Evidence scope

WELP provides an evaluation methodology and evidence framework. Individual model results are bounded by the tested artifact, runtime, hardware, configuration, and protocol snapshot and should not be generalized beyond that evidence.
