# WELP — WumboLabs Evaluation Lifecycle Protocol (repo-candidate)

Public reproducibility package for the **WELP — WumboLabs Evaluation Lifecycle Protocol** (canonical successor to WLEP).

> Status: **DRAFT**. WELP is not frozen as v1.0. Thresholds marked draft are under empirical validation.

> **Naming migration (2026-08-26):** the active protocol was renamed from WLEP to WELP. The current canonical artifacts in this directory use the `welp-` prefix. Historical WLEP artifacts (snapshots, contracts, schemas, validator copies, Lab Records) are preserved unchanged in their original locations and remain valid for reproducing old campaigns. See `summaries/welp_compatibility_policy.json` for the formal compatibility policy.

*"Real Hardware. Real Testing. No Hype."*

## Layout

| Path | Contents |
|---|---|
| `protocol/` | protocol notes (phase structure, policies, standards) |
| `contracts/` | versioned evaluation contracts (welp-practical-viability, welp-reliability, capability modules). Legacy `wlep-` contracts retained for historical reproducibility under `wlep-development/`. |
| `scorers/` | deterministic scorers with embedded self-tests |
| `schemas/` | JSON Schemas — welp_campaign_manifest, welp_artifact_index, welp_publication_status, welp_serving_profile, welp_toolchain_preflight, welp_toolchain_inventory. Legacy `wlep_*.schema.json` retained for historical compatibility. |
| `hardware-profiles/` | *(see top-level `hardware/`; WELP carries reference runtime identities in `schemas/` + `docs/`)* |
| `docs/` | methodology documentation |
| `examples/` | example campaign records |
| `validators/` | campaign-bundle validator (`validate_campaign_welp.py`, self-test passes) accepting both WELP and WLEP prefixes |
| `lab-record-template/` | template for publishing a campaign evidence record |
| `summaries/` | migration inventory, compatibility policy, contract/schema/validator mappings, executor-independence + integrity reports, rename verdict |

## Core rules

- The testing protocol is fixed before a model is evaluated; a failed gate is a valid result.
- Every canonical run distinguishes REQUESTED vs EFFECTIVE serving configuration; requested flags alone are not proof.
- Single-user baselines run `parallel=1`, `fit=off`; automatic parallelism is never relied upon.
- Scorers self-test before live gate use.
- Human-controlled Git operations only.

## Compatibility and history

Historical records created before the rename may identify the protocol as WLEP. Those identifiers are intentionally preserved for reproducibility. Validators in this repo accept both `WLEP-CONFORMANCE.md` (legacy) and `WELP-CONFORMANCE.md` (canonical for new campaigns). Frozen campaign snapshots beginning with `wlep-next-snapshot-*` are immutable.

See `summaries/welp_migration_inventory.json` for the full reference inventory, `summaries/welp_compatibility_policy.json` for the rules, and `summaries/welp_contract_mapping.json` + `summaries/welp_schema_mapping.json` for the contract/schema mappings.

## First WELP snapshot

The first WELP snapshot is `welp-next-snapshot-2026-08-26-post-rename` (DRAFT — NOT v1.0). Parent: `wlep-next-snapshot-2026-08-26-post-apodex`. Migration type: naming-only. See `snapshot-freeze/manifest.json`.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Evidence scope

WELP provides an evaluation methodology and evidence framework. Individual model results are bounded by the tested artifact, runtime, hardware, configuration, and protocol snapshot and should not be generalized beyond that evidence.
