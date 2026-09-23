# WELP — WumboLabs Evaluation Lifecycle Protocol (repo-candidate)

Public reproducibility package for the **WELP — WumboLabs Evaluation Lifecycle Protocol**.

> Status: **DRAFT**. WELP is not frozen as v1.0. Thresholds marked draft are under empirical validation.

*"Real Hardware. Real Testing. No Hype."*

## Layout

| Path | Contents |
|---|---|
| `protocol/` | protocol notes (phase structure, policies, standards) |
| `contracts/` | versioned evaluation contracts: outcomes, budgets/prompt lanes, real-work applicability, reliability, classification and capability modules. |
| `harness/` | canonical versioned phase implementations (`welp-phase-harness/1.0.0-draft`): outcomes, admission, quality, reliability gates, capabilities, context, classification. |
| `scorers/` | deterministic scorers with embedded self-tests (`welp-reliability-scorer/2`, acceptance rescore). |
| `fixtures/` | frozen evaluation fixtures: reliability 20-task sample, useful-context Family A 1.2, quality screen 12, real-work tool recovery, multi-turn correction, document synthesis and repository bug. |
| `schemas/` | Campaign, artifact index, publication status, website export, eval profile, serving profile, task outcome, and toolchain contracts. |
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
- [Context Scaling](protocol/context-scaling.md): Family A 1.2 places targets
  against the final rendered token stream; lane-specific reserves and
  multi-document/codebase/session results remain distinct. Configured capacity
  is not useful context; practical default selection does not complete the
  model-card envelope.
- [Publication operating contract](docs/publication.md): website for human discovery/share; `WumboLabs/evaluations` for public scientific evidence and exact repo/full-commit/path citations; local `research/model-evaluations/` for working/raw science; NAS archive for large model artifacts. Model/profile/event identity is independent of repository boundaries. Never create a new `eval-*` repository.

## WELP snapshots

| Snapshot | Status | Scope |
|---|---|---|
| `welp-next-snapshot-2026-08-26-post-rename` | frozen (DRAFT — NOT v1.0) | First WELP snapshot; naming-only (WLEP → WELP). Manifest: `snapshot-freeze/manifest.json` (immutable). |
| `welp-next-snapshot-2026-09-19-methodology-revision` | frozen DRAFT (NOT v1.0); methodology in force | Methodology revision (`methodology_changed: YES`): CP-1 outcome semantics, CP-2 generation-budget policy, reliability scorer v2 + re-derived 20×2 gates, useful-context outcome lanes + standardized 512-token reserve, canonical harness/scorers/fixtures, in-repo classification, validator R09–R14. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-19-methodology-revision/manifest.json`. |
| `welp-next-snapshot-2026-09-21-localmaxxing-closeout-rule` | frozen DRAFT (NOT v1.0); superseded lifecycle rule | LocalMaxxing terminal-closeout and two-stage lifecycle delta (`methodology_changed: NO`); the two-stage rule is superseded by the 2026-09-22 automatic-closeout delta. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-21-localmaxxing-closeout-rule/manifest.json`. |
| `welp-next-snapshot-2026-09-22-automatic-closeout-lifecycle` | frozen DRAFT (NOT v1.0); lifecycle in force | Automatic-closeout execution-state lifecycle delta (`methodology_changed: NO`); no measurement-methodology change. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-22-automatic-closeout-lifecycle/manifest.json`. |
| `welp-next-snapshot-2026-09-22-readme-lineage-documentation` | frozen DRAFT (NOT v1.0); superseded | README snapshot-lineage documentation correction only (`methodology_changed: NO`); retains the 2026-09-19 methodology and 2026-09-22 automatic-closeout lifecycle. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-22-readme-lineage-documentation/manifest.json`. |
| `welp-next-snapshot-2026-09-23-real-hardware-real-testing` | **current DRAFT** (NOT v1.0); methodology changed YES | Bounded semantic/deployment budget lanes, frozen prompt identities, Family A rendered-token placement, profile-pure classification, stateful tool and multi-turn fixtures, explicit real-work applicability and LLMGauge evidence boundary. Parent: 2026-09-22 README lineage snapshot. Manifest: `snapshot-freeze/welp-next-snapshot-2026-09-23-real-hardware-real-testing/manifest.json`. |

Historical campaigns remain valid under their recorded snapshots and are never relabeled; scorer-only rescoring of retained raw outputs under the new vocabulary is new supplementary evidence linked to the original events (`scorers/rescore_acceptance.py`).

## License

Licensed under the [Apache License 2.0](LICENSE).

## Evidence scope

WELP provides an evaluation methodology and evidence framework. Individual model results are bounded by the tested artifact, runtime, hardware, configuration, and protocol snapshot and should not be generalized beyond that evidence.
