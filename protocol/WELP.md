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
- `welp_serving_profile.schema.json`
- `welp_toolchain_preflight.schema.json`
- `welp_toolchain_inventory.schema.json`

## Canonical validator (current)

- `validators/validate_campaign_welp.py` — accepts both WELP and legacy prefixes, 5 fixtures, all PASS.
