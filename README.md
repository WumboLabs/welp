# WELP — WumboLabs Evaluation Lifecycle Protocol (repo-candidate)

Public reproducibility package for the **WELP — WumboLabs Evaluation Lifecycle Protocol**.

> Status: **DRAFT**. WELP is not frozen as v1.0. Thresholds marked draft are under empirical validation.

*"Real Hardware. Real Testing. No Hype."*

## Layout

| Path | Contents |
|---|---|
| `protocol/` | protocol notes (phase structure, policies, standards) |
| `contracts/` | versioned evaluation contracts (welp-practical-viability, welp-reliability, capability modules). |
| `scorers/` | deterministic scorers with embedded self-tests |
| `schemas/` | JSON Schemas — welp_campaign_manifest, welp_artifact_index, welp_publication_status, welp_serving_profile, welp_toolchain_preflight, welp_toolchain_inventory.  |
| `hardware-profiles/` | *(see top-level `hardware/`; WELP carries reference runtime identities in `schemas/` + `docs/`)* |
| `docs/` | methodology documentation |
| `examples/` | example campaign records |
| `validators/` | campaign-bundle validator (`validate_campaign_welp.py`, self-test passes) |
| `lab-record-template/` | template for publishing a campaign evidence record |
| `summaries/` | executor-independence + integrity reports |

## Core rules

- The testing protocol is fixed before a model is evaluated; a failed gate is a valid result.
- Every canonical run distinguishes REQUESTED vs EFFECTIVE serving configuration; requested flags alone are not proof.
- Single-user baselines run `parallel=1`, `fit=off`; automatic parallelism is never relied upon.
- Scorers self-test before live gate use.
- Human-controlled Git operations only.
- [Report artifact hierarchy](protocol/WELP.md#report-artifact-hierarchy): `REPORT.md` is the single authoritative primary scientific report; the Lab Record companion is `WELP-LAB-RECORD.md`; `report.md` is historical-only; superseded prior attempts stay quarantined and never supply current claims.
- [Context Scaling](protocol/context-scaling.md): configured capacity is not full-context validation; practical default selection does not complete the model-card native/official extension envelope.

## First WELP snapshot

The first WELP snapshot is `welp-next-snapshot-2026-08-26-post-rename` (DRAFT — NOT v1.0). See `snapshot-freeze/manifest.json`.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Evidence scope

WELP provides an evaluation methodology and evidence framework. Individual model results are bounded by the tested artifact, runtime, hardware, configuration, and protocol snapshot and should not be generalized beyond that evidence.
