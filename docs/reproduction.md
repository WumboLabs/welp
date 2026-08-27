# WELP Campaign Reproduction (canonical)

## Operator checklist

1. **Preflight (mandatory at campaign START).** Run `welp-preflight` per `summaries/welp_preflight_0.1.0`:
   - HARDWARE: GPU identity, host safety rules, telemetry.
   - TOOLCHAIN: discover installed runtimes, apply DISCOVER-FIRST/REUSE/NEW_RUNTIME_REQUIRED rule.
   - PROTOCOL: snapshot_id = `welp-next-snapshot-2026-08-26-post-rename`.
   - MODEL: producer claims + applicability per [[WELP Phase Structure]].
   - PUBLICATION: LocalMaxxing auth (READY / AUTH_BLOCKED / CLI_INCOMPATIBLE / NOT_APPLICABLE).
   - SAFETY: GPU & Host Safety Rules, stop-on-Xid.
   - OUTPUT: durable long-job paths declared absolute and fail-closed.
2. **Cache-metric probe.** One disjoint-prompt probe per selected runtime; record `CACHE_METRIC_TRUSTED | CACHE_METRIC_FLOOR_PRESENT | CACHE_METRIC_UNAVAILABLE | UNKNOWN` in `toolchain/runtime_capabilities.json`.
3. **Phase progression.** Apply phases per `protocol/WELP.md` and `WELP Phase Structure.md` (in HivemindVault). Stop early per Early-Stop Philosophy.
4. **Phase 3 gate reasoning state.** Declare `gate_baseline_reasoning_state` + REQUESTED/EFFECTIVE before any generation.
5. **Phase 5 module applicability.** Freeze `phase5_applicability.json` before any Phase-5 execution.
6. **Long-job durability.** Absolute path declared first; existence + row count + SHA-256 verified after exit; only then COMPLETE.
7. **Final classification.** `classify.py` consumes the evidence bundle deterministically.
8. **Validation.** `validate_campaign_welp.py <campaign_dir>` MUST exit 0.
9. **Standard Completion Package.** Produce `report.md`, `WELP-CONFORMANCE.md`, `protocol-findings.md`, all machine-readable summaries.
10. **Publication routing.** Per vault Publication Routing:
    - Obsidian: internal WELP operational handbook.
    - GitHub: canonical public WELP evidence/protocol source.
    - LocalMaxxing: community benchmark/report distribution layer.
    - WumboCore Labs: human-readable WELP Lab Records.

## Compatibility

- Historical WLEP campaigns reproduce unchanged with the frozen WLEP snapshot.
- New WELP campaigns use the WELP snapshot + WELP-named successor contracts.
- Both validators accept both prefixes; either filename (`WELP-CONFORMANCE.md` / `WLEP-CONFORMANCE.md`) is valid.

## What is NOT in scope for the migration

- git init (human)
- LICENSE selection (human)
- Public GitHub push (human)
- New model campaign execution (this migration is naming-only)
- LLMGauge / runtimes / model binaries — all unchanged
