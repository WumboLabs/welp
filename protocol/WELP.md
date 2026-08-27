# WELP — WumboLabs Evaluation Lifecycle Protocol

Canonical: **WELP — WumboLabs Evaluation Lifecycle Protocol** (informal pronunciation: "welp"). Former name (pre-2026-08-26): WLEP — WumboLabs Model Evaluation Protocol.

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

## Canonical contracts (current)

- `welp-practical-viability` 0.1.4-draft (successor to `wlep-practical-viability` 0.1.3-draft)
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
- `welp_serving_profile.schema.json`
- `welp_toolchain_preflight.schema.json`
- `welp_toolchain_inventory.schema.json`

## Canonical validator (current)

- `validators/validate_campaign_welp.py` — accepts both WELP and WLEP prefixes, 5 fixtures, all PASS.
