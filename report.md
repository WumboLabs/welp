# WLEP → WELP Migration Report

**Date:** 2026-08-26
**Workspace:** `~/Projects/local-llm/welp-development/wlep-to-welp-rename/`
**Migration type:** naming-only. No methodology change.

---

## 1. Executive verdict

The WLEP — WumboLabs Model Evaluation Protocol was renamed to **WELP — WumboLabs Evaluation Lifecycle Protocol** (informal pronunciation: "welp") on 2026-08-26, while the protocol remained DRAFT. All historical WLEP campaign evidence, frozen snapshot manifests, contract files, schema files, and validator copies are preserved unchanged. Validators accept both WLEP and WELP prefixes. A new WELP canonical successor tree lives at `welp-development/welp-to-welp-rename/` with the first WELP snapshot frozen at `welp-next-snapshot-2026-08-26-post-rename`. Five validator fixtures all behave correctly. No methodology, threshold, scorer, or gate change was introduced.

## 2. Old name

- **Acronym:** WLEP
- **Formal:** WumboLabs Model Evaluation Protocol
- **Status:** Legacy draft protocol name (pre-2026-08-26)
- **Snapshot IDs:** `wlep-next-snapshot-2026-08-25-phase5`, `wlep-next-snapshot-2026-08-25-end-to-end`, `wlep-next-snapshot-2026-08-26-post-apodex`, `wlep-validation-2` (campaign)

## 3. New name

- **Acronym:** WELP
- **Formal:** WumboLabs Evaluation Lifecycle Protocol
- **Informal pronunciation:** "welp"
- **Status:** Current and future canonical protocol name (effective 2026-08-26)
- **First snapshot ID:** `welp-next-snapshot-2026-08-26-post-rename`

## 4. Migration scope

In scope (naming-only):
- HivemindVault living protocol notes (renamed WLEP → WELP in body text; legacy alias file retained for wikilink compatibility).
- HivemindVault Change Rationale 2026-08-26 entry recording the rename.
- New canonical WELP overview note + the canonical WELP file at `welp-development/welp-to-welp-rename/protocol/WELP.md`.
- New WELP-named successor contracts (8 files + 1 module index) under `welp-development/welp-to-welp-rename/contracts/`.
- New WELP-named successor schemas (6 files) under `welp-development/welp-to-welp-rename/schemas/`.
- New WELP successor validator `validate_campaign_welp.py` with 5 fixtures; all PASS.
- First WELP snapshot manifest at `welp-development/welp-to-welp-rename/snapshot-freeze/manifest.json`.
- Repo-candidate README, REPO-READINESS, docs, lab-record-template, examples (WELP-canonical).
- Updated body text of `post-apodex-maintenance/publication/repo-candidate/{README,docs/*.md}`.

Out of scope (NOT performed):
- git init in any new repo.
- LICENSE selection.
- Public GitHub push.
- X post or community posting.
- Rerun of any model campaign.
- Modifications to LLMGauge, runtimes, or model binaries.
- Subagent spawns.
- Rewrite of historical Lab Records.
- Deletion of historical WLEP artifacts.

## 5. Historical-preservation policy

All historical WLEP campaign artifacts remain identified as WLEP. Frozen snapshot manifests, frozen contract files, frozen schema files, and frozen validator copies are immutable. The migration applies to current/living protocol artifacts, future protocol snapshots, future campaigns, current generic protocol tooling, the public repo-candidate documentation, and current operational terminology only.

Per `summaries/welp_compatibility_policy.json`:
- Historical `wlep-` filenames are not renamed in place.
- Historical `wlep_` schema filenames are not renamed in place.
- Historical WLEP reports are not retroactively rewritten to WELP.
- Historical Lab Record directory names (e.g. `lab-records/<model>/wlep-<YYYY-MM-DD>/`) are filesystem provenance; never renamed.
- Validators accept both `WLEP-CONFORMANCE.md` (legacy) and `WELP-CONFORMANCE.md` (current).
- Snapshot identity pattern accepts both `wlep-next-snapshot-*` and `welp-next-snapshot-*`.
- Pre-flight const accepts both `wlep-preflight` and `welp-preflight`.
- Contract IDs may use either `wlep-` or `welp-` prefix; a `welp-*` campaign with only `wlep-*` contracts is REJECTED (silent rewrite detection).

## 6. HivemindVault changes

- Created new canonical note `WumboLabs Evaluation Lifecycle Protocol (WELP).md` (with the WELP overview and the rename migration note).
- Retained legacy alias file `WumboLabs Model Evaluation Protocol (WLEP).md` (now a stub redirecting to the new note) with Obsidian aliases for `WELP` and `WumboLabs Evaluation Lifecycle Protocol`.
- Retained filename `WLEP Phase Structure.md` (filesystem provenance) with the WELP body content + a migration note + Obsidian aliases including `WELP Phase Structure` so `[[WELP Phase Structure]]` resolves to the same file.
- Updated body text in all 22 living protocol notes to use WELP / WumboLabs Evaluation Lifecycle Protocol. The `MOC`, `Scoring Policy`, `Runtime Pinning`, `Toolchain & Preflight`, `Evaluation Operations`, `Standard Completion Package`, `Standard Campaign Artifacts`, `OMP Integration`, `Serving Profile Identity`, `Method Development Lessons`, `Model Acquisition & Identity`, `Producer Claim Validation`, `Proposed Changes`, `Protocol Open Questions`, `Repetition Policy`, `Scoring Bug & Correction Policy`, `GPU & Host Safety Rules`, `Agent Token & Context Discipline`, `Execution Accounting`, `Early-Stop Philosophy`, `Context Terminology`, `LocalMaxxing Publication Workflow`, `Publication Routing`, `Change Rationale`, `WumboLabs Overview` were all updated.
- Added a `2026-08-26 — Protocol rename milestone` section to `Change Rationale.md`.
- Added migration notes to `WLEP Phase Structure.md`, `WumboLabs Model Evaluation Protocol (WLEP).md`, and the new `WumboLabs Evaluation Lifecycle Protocol (WELP).md`.
- Wikilinks verified: all 24+ internal `[[WumboLabs Evaluation Lifecycle Protocol (WELP)]]` references resolve; the MOC's `[[WELP Phase Structure]]` reference resolves via the alias declaration in the legacy filename file.

## 7. Contract ID migration

- Created WELP-named successor contracts at `welp-development/welp-to-welp-rename/contracts/`:
  - `welp-practical-viability-0.1.3-draft.json` (successor to `wlep-practical-viability` 0.1.3-draft; version bumped to 0.1.4-draft; byte-distinct from frozen 0.1.3-draft).
  - `welp-preflight-0.1.0-draft.json` (successor to `wlep-preflight` 0.1.0-draft; identical content aside from `artifact` field and added `supersedes` block).
  - `welp-reliability-0.1.0-draft.json`, `welp-context-0.1.0-draft.json`, `welp-optimization-0.1.0-draft.json`, `welp-stability-0.1.0-draft.json`, `welp-final-classification-0.1.0-draft.json` (successor stubs with explicit `supersedes` blocks).
  - `welp-modules.json` (Phase 5 module index; `welp-coding`, `welp-structured-interfaces`, `welp-native-tools`, `welp-extraction-rag`, `welp-reasoning`, `welp-linux-systems`, `welp-omp-local-agent`).
- The frozen historical `wlep-` contracts are byte-identical and remain valid.
- Mapping: `summaries/welp_contract_mapping.json`.

## 8. Schema migration

- Created WELP-named successor schemas at `welp-development/welp-to-welp-rename/schemas/`:
  - `welp_campaign_manifest.schema.json` (additive: protocol_snapshot.id.pattern now allows `welp-` and `wlep-`).
  - `welp_artifact_index.schema.json` (no field changes; title literal updated).
  - `welp_publication_status.schema.json` (no field changes; title literal updated).
  - `welp_serving_profile.schema.json` (additive: `gate_baseline_reasoning_state` enum and `reasoning_requested`/`reasoning_effective` strings).
  - `welp_toolchain_preflight.schema.json` (title literal `welp-preflight`; protocol.snapshot_id pattern accepts both prefixes).
  - `welp_toolchain_inventory.schema.json` (title literal `welp-toolchain-inventory`).
- The frozen historical `wlep_*.schema.json` files are byte-identical and remain valid.
- Mapping: `summaries/welp_schema_mapping.json`.

## 9. Validator compatibility

- New validator at `welp-development/welp-to-welp-rename/validators/validate_campaign_welp.py`.
- 5 fixtures (all PASS):
  1. valid historical WLEP campaign: ACCEPTED.
  2. valid current WELP campaign: ACCEPTED.
  3. WELP campaign using legacy-compatible evidence: ACCEPTED.
  4. invalid unknown protocol prefix: REJECTED.
  5. historical WLEP manifest whose identity was silently rewritten to WELP: REJECTED.
- Frozen validators continue to validate historical WLEP campaigns:
  - `post-apodex-maintenance/validators/validate_campaign_v2.py` selftest PASS (2/2).
  - `overnight-hardening-2026-08-25/publication/repo-candidate/validation/wlep_validate.py` selftest PASS (3/3).
  - `final-hardening/validators/final_validate.py` selftest PASS (2/2).
  - `post-apodex-maintenance/publication/repo-candidate/validators/validate_campaign_v2.py` (canonical in repo-candidate): PRE-EXISTING DEFECT — its `good` fixture has `<home>/camp/results/phase3_raw.jsonl` which fails M09 (M09 expects absolute path). NOT introduced by the migration. Tracked as an open issue.
- Mapping: `summaries/welp_validator_compatibility.json`.

## 10. Repo-candidate changes

- `welp-development/welp-to-welp-rename/`: created new canonical repo-candidate tree.
  - `README.md` (WELP canonical, with compatibility section).
  - `REPO-READINESS.md` (WELP).
  - `LICENSE_TODO` (carried over; LICENSE decision pending human).
  - `protocol/WELP.md`.
  - `contracts/`, `schemas/`, `validators/`, `docs/`, `examples/`, `lab-record-template/`, `summaries/`, `snapshot-freeze/`, `fixtures/` (reserved).
- `wlep-development/post-apodex-maintenance/publication/repo-candidate/`: existing tree updated to mention WELP in README and add WELP header lines to `docs/output-durability.md` and `docs/runtime-selection.md`. No frozen files were renamed; only the canonical mutable copy was updated.

## 11. Workspace/path decision

- Legacy development root: `~/Projects/local-llm/wlep-development/` — preserved as filesystem provenance.
- New WELP canonical root: `~/Projects/local-llm/welp-development/welp-to-welp-rename/` — current/future development.
- Decision rationale: renaming the historical root would invalidate frozen manifest hash tables that reference relative paths under `wlep-development/`. Co-locating the new tree as a subdirectory keeps the operator's tree navigable while preserving historical provenance.
- Future option: collapse `welp-to-welp-rename/` into the parent root once the migration is fully accepted. Documented in `workspace_decision.md`.

## 12. First WELP snapshot

- **ID:** `welp-next-snapshot-2026-08-26-post-rename`
- **Parent:** `wlep-next-snapshot-2026-08-26-post-apodex`
- **Migration type:** naming-only
- **Methodology change:** NO
- **Status:** DRAFT — NOT v1.0
- **Manifest path:** `welp-development/welp-to-welp-rename/snapshot-freeze/manifest.json`
- **Protocol changes:** `summaries/welp_protocol_changes.json` records all naming changes; nothing methodology changed.

## 13. Executor-independence result

PASS. A fresh agent with no conversation history can answer the six executor-independence questions using only the listed vault notes, the post-apodex frozen manifest, the WELP canonical artifacts, and the machine-readable migration summaries. Documented in `summaries/welp_executor_independence.json`.

## 14. Historical-integrity validation

PASS. All historical WLEP campaign evidence, frozen snapshot manifests, contract files, schema files, and validator copies are SHA-256 verified unchanged:
- `apodex-1.1-mini/WLEP-CONFORMANCE.md` and the byte-identical `apodex-1.1-mini/publication/repo-candidate/lab-records/apodex-1.1-mini/wlep-2026-08-25/WLEP-CONFORMANCE.md` both sha256=`dfac0bcf96c98a5d50f2b783dcb3aa7ab4ede0cb763fb1b09be3d4bb4b653136`.
- `apodex-1.1-mini/summaries/wlep_conformance.json` sha256=`a2c30e293edadb3d6273fb9ad1623e1b620fabd907adc4944351866eb2b36921`.
- `nemotron-3-nano-4b/WLEP-CONFORMANCE.md` sha256=`d60affa476057bcefb97f3e241641f1b90f3ae099edc41afe4f3d1e3ad242522`.
- `final-hardening/protocol-freeze/manifest.json` sha256=`35084c2421803a0886731fc579a3d829f7328f63d771430fa8e85b6d94df025e`.
- `overnight-hardening-2026-08-25/protocol-freeze/manifest.json` sha256=`c1c1fa8ae2b38626554c650a1d601f2720aea711076528064ea044536acb4bea`.
- `phase5-hardening/protocol-freeze/manifest.json` sha256=`789165347f4ee8c0ff384989717642b85b06663026ec19342ba6a708a940418a`.
- `post-apodex-maintenance/protocol-freeze/manifest.json` sha256=`97f278b35838b4e82f9b825b967e12f888031cf9fc95dc7ea1c9dc7d9ae69f81`.
- `post-apodex-maintenance/pre_snapshot/manifest.json` sha256=`fce20d39b3ceef2b46cfc51d65a2fce5d051afc0ba07303e8d1521cd42743f34`.
- `post-apodex-maintenance/pf01-scorer/contracts/wlep-practical-viability-0.1.3-draft.json` sha256=`003ee7f797f78a115c72a3a22d632b79e9ba2eb21c2e50d1d76dd0626faba239` (matches frozen manifest).
- `post-apodex-maintenance/pf01-scorer/score_pv.py` sha256=`d5dedf5b5bae21e3add97a4675b3ba82b5130eaff0ae14c35abe97532b846424` (matches frozen manifest).
- `post-apodex-maintenance/publication/repo-candidate/contracts/preflight/wlep-preflight-0.1.0-draft.json` sha256=`bfb68f4cbb58004d61c1b6274d6caea4b43249c07cc4d90cfac87c64725c89fc`.
- `post-apodex-maintenance/publication/repo-candidate/schemas/toolchain_inventory/schema.json` sha256=`03ba39879a6e0931a6dcb17b65e2fb5d2b96a1534a1566bd7e379466ae0b5316`.
- `post-apodex-maintenance/publication/repo-candidate/schemas/toolchain_preflight/schema.json` sha256=`2f1c4aa17bad15dace838aed3bc91fc0219bd3bb204505489783d7f1cd885cfc`.
- `score_pv.py` self-test (frozen 0.1.3-draft) PASS (60/60 fixtures).
- Detailed in `summaries/welp_historical_integrity.json`.

## 15. Open issues

- **Pre-existing M09 fixture bug** in `post-apodex-maintenance/publication/repo-candidate/validators/validate_campaign_v2.py`: the embedded `good` fixture uses `<home>/camp/results/phase3_raw.jsonl` as a relative path. M09 expects absolute. NOT introduced by the migration. Tracked as out-of-scope fix; recommend pre-deploy: replace with `<workspace>/camp/results/phase3_raw.jsonl` (absolute).
- **Vault head reconciliation:** the WELP migration edited body text of multiple HivemindVault notes. Obsidian auto-backup committed the edits at 2026-08-26 18:58:09 (vault head 2cbcba0). The first WELP snapshot's note_hashes record the post-apodex (2f2b6bb6) hashes for the unchanged notes and mark edited ones as `post-migration-hash-recorded-after-edit`. The next non-rename frozen snapshot should re-hash the post-migration vault head cleanly.
- **Out-of-scope human actions awaiting:** commit HivemindVault rename, initialize public Git repository, select a LICENSE, decide on the next non-rename frozen snapshot. All are out of scope for this migration agent per the hard boundaries in the migration spec.

## 16. Artifact index

### HivemindVault (modified)
- `03 - Reference/WumboLabs/WumboLabs Evaluation Lifecycle Protocol (WELP).md` (new)
- `03 - Reference/WumboLabs/WumboLabs Model Evaluation Protocol (WLEP).md` (legacy alias stub)
- `03 - Reference/WumboLabs/WLEP Phase Structure.md` (filename retained, body + alias added)
- 22 other living protocol notes (body WLEP → WELP; migration notes where relevant)

### welp-development/welp-to-welp-rename/ (new canonical root)
- `README.md`
- `REPO-READINESS.md`
- `LICENSE_TODO`
- `protocol/WELP.md`
- `contracts/`
  - `welp-practical-viability-0.1.3-draft.json` (successor 0.1.4-draft content)
  - `welp-preflight-0.1.0-draft.json`
  - `welp-reliability-0.1.0-draft.json`
  - `welp-context-0.1.0-draft.json`
  - `welp-optimization-0.1.0-draft.json`
  - `welp-stability-0.1.0-draft.json`
  - `welp-final-classification-0.1.0-draft.json`
  - `welp-modules.json`
- `schemas/`
  - `welp_campaign_manifest.schema.json`
  - `welp_artifact_index.schema.json`
  - `welp_publication_status.schema.json`
  - `welp_serving_profile.schema.json`
  - `welp_toolchain_preflight.schema.json`
  - `welp_toolchain_inventory.schema.json`
- `validators/validate_campaign_welp.py`
- `docs/`
  - `README.md`
  - `validator.md`
  - `compatibility.md`
  - `reproduction.md`
- `examples/`
  - `README.md`
  - `toolchain_inventory.example.json`
- `lab-record-template/`
  - `README.md`
  - `LAB-RECORD-LAYOUT.md`
- `summaries/`
  - `welp_migration_inventory.json`
  - `welp_compatibility_policy.json`
  - `welp_contract_mapping.json`
  - `welp_schema_mapping.json`
  - `welp_validator_compatibility.json`
  - `welp_publication_routing.json`
  - `welp_protocol_changes.json`
  - `welp_historical_integrity.json`
  - `welp_executor_independence.json`
  - `welp_repo_readiness.json`
  - `welp_rename_verdict.json`
- `snapshot-freeze/manifest.json` (first WELP snapshot)
- `workspace_decision.md`
- `fixtures/` (reserved for future use)
- `report.md` (this document)

### wlep-development/post-apodex-maintenance/publication/repo-candidate/ (canonical copy updated)
- `README.md` (added WELP header)
- `docs/output-durability.md` (added WELP header)
- `docs/runtime-selection.md` (added WELP header)

### Historical artifacts (unchanged)
- All `wlep-next-snapshot-*` manifests (post-apodex-maintenance, final-hardening, overnight-hardening-2026-08-25, phase5-hardening, gate-calibration)
- All `wlep-` contract files
- All `wlep_*.schema.json` files
- All validator copies (post-apodex `validate_campaign_v2.py`, overnight `wlep_validate.py`, final-hardening `final_validate.py`)
- All apodex, nemotron, lfm, qwen3.8 campaign trees

---

*This migration is naming-only. The protocol methodology, gates, scorers, and thresholds are unchanged. WELP remains DRAFT — NOT v1.0.*
