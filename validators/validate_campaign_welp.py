#!/usr/bin/env python3
"""validate_campaign_welp.py — WELP campaign validator.

Canonical validator for new WELP campaigns. Also accepts frozen historical
campaign artifacts so previously completed evidence bundles remain valid.

Accepts:
  - WELP-CONFORMANCE.md (new campaigns) OR WLEP-CONFORMANCE.md (frozen historical campaigns)
  - protocol_snapshot.id starting with welp-next-snapshot- OR wlep-next-snapshot-
  - contract_id values with welp- OR wlep- prefix
  - preflight const welp-preflight OR wlep-preflight
  - snapshot_status WELP status (DRAFT) regardless of identifier generation
  - Report artifact hierarchy (new-format bundles containing REPORT.md):
    REPORT.md primary + WELP-LAB-RECORD.md companion expected; REPORT.md +
    report.md coexistence is REJECTED as an ambiguous case-different pair.
    Historical bundles without REPORT.md keep the report.md requirement
    (warning only) so frozen evidence bundles remain valid unchanged.

New rules:
  N01  Protocol snapshot id must match ^(welp|wlep)-next-snapshot-
  N02  Pre-flight "preflight" field must be one of welp-preflight or wlep-preflight
  N03  Manifest whose snapshot_id has been rewritten to welp- while the evidence
       bundle still references only frozen historical wlep-* contracts is REJECTED
  N04  WELP campaign using frozen-compatible evidence (e.g. welp-next-snapshot-*
       with wlep_*.schema.json validation paths) is ACCEPTED
  R01  REPORT.md is the primary scientific report of new-format bundles
  R02  REPORT.md + report.md coexistence REJECTED (ambiguous case-different pair)
  R03  WELP-LAB-RECORD.md expected companion in new-format bundles (warning if absent)
  R04  (warning) historical report.md naming; new campaigns use REPORT.md + WELP-LAB-RECORD.md

Usage: validate_campaign_welp.py <campaign_dir> | selftest
"""
import json, os, re, sys, tempfile
from pathlib import Path

HASH = re.compile(r"^[a-f0-9]{64}$")
AUTH_STATUSES = {"READY", "AUTH_BLOCKED", "CLI_INCOMPATIBLE", "NOT_APPLICABLE"}
SNAPSHOT_RE = re.compile(r"^(welp|wlep)-next-snapshot-[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9-]+)?$")
ALLOWED_PREFLIGHT = {"wlep-preflight", "welp-preflight"}


def check(root: Path):
    F = []

    def bad(c, d): F.append(("error", c, d))
    def warn(c, d): F.append(("warning", c, d))
    def ok(c, d=""): F.append(("info", c, d))

    # ---- dual-prefix file presence (N01 acceptance) ----
    has_wlep = (root / "WLEP-CONFORMANCE.md").is_file()
    has_welp = (root / "WELP-CONFORMANCE.md").is_file()
    if has_wlep and has_welp:
        warn("dual_conformance_filenames", "both WLEP-CONFORMANCE.md and WELP-CONFORMANCE.md present; preferring WELP")
    if not (has_wlep or has_welp):
        bad("required:conformance", "WLEP-CONFORMANCE.md or WELP-CONFORMANCE.md required")
    p = root / "protocol-findings.md"
    if p.is_file():
        ok("required:protocol-findings.md")
    else:
        bad("required:protocol-findings.md", "missing")

    # ---- R-section report artifact hierarchy ----
    # Exact-case name matching (not Path.is_file) keeps case-insensitive
    # filesystems from misreading a legacy report.md as a new-format REPORT.md.
    bundle_names = {q.name for q in root.iterdir()} if root.is_dir() else set()
    has_primary = "REPORT.md" in bundle_names
    has_lab_record = "WELP-LAB-RECORD.md" in bundle_names
    has_legacy_report = "report.md" in bundle_names
    if has_primary:
        ok("R01_primary_report", "REPORT.md")
        if has_legacy_report:
            bad("R02_ambiguous_report_pair",
                "REPORT.md and report.md coexist; REPORT.md is the sole primary "
                "scientific report and the Lab Record must be WELP-LAB-RECORD.md")
        if has_lab_record:
            ok("R03_lab_record", "WELP-LAB-RECORD.md")
        else:
            warn("R03_lab_record_expected",
                 "WELP-LAB-RECORD.md absent; current standard expects the "
                 "standardized Lab Record companion")
    elif has_legacy_report:
        ok("required:report.md")
        warn("R04_legacy_report_naming",
             "report.md is the historical convention; new campaigns use "
             "REPORT.md (primary) + WELP-LAB-RECORD.md (companion)")
    else:
        bad("required:report.md", "missing")

    # ---- manifest parse ----
    man = root / "summaries/campaign_manifest.json"
    m = {}
    if man.is_file():
        try:
            m = json.load(open(man))
        except Exception as e:
            bad("manifest_parse", str(e))
    else:
        bad("manifest_missing", str(man))

    # ---- N01 protocol snapshot id pattern ----
    sid = (m.get("protocol_snapshot") or {}).get("id", "")
    if not sid:
        bad("N01_snapshot_id_missing", "protocol_snapshot.id absent")
    elif not SNAPSHOT_RE.match(sid):
        bad("N01_snapshot_id_pattern", f"snapshot id {sid!r} does not match ^(welp|wlep)-next-snapshot-")
    else:
        ok("N01_snapshot_id", sid)

    # ---- N02 preflight const ----
    pf = root / "summaries/toolchain_preflight.json"
    if pf.is_file():
        try:
            tpf = json.load(open(pf))
            preflight_const = tpf.get("preflight")
            if preflight_const in ALLOWED_PREFLIGHT:
                ok("N02_preflight_const", preflight_const)
            else:
                bad("N02_preflight_const", f"invalid/absent: {preflight_const!r}")
            # welp_status + snapshot identity
            proto = tpf.get("protocol", {})
            if proto.get("welp_status") == "DRAFT":
                ok("welp_status", "DRAFT")
            else:
                warn("welp_status_missing_or_non_draft", str(proto.get("welp_status")))
            pf_sid = proto.get("snapshot_id", "")
            if not SNAPSHOT_RE.match(pf_sid):
                bad("N01_preflight_snapshot_id_pattern", f"preflight snapshot_id {pf_sid!r} invalid")
        except Exception as e:
            bad("preflight_parse", str(e))
    else:
        bad("preflight_missing", str(pf))

    # ---- contract_ids allow welp- and wlep- ----
    for cid, cobj in (m.get("contracts") or {}).items():
        if cid.startswith("welp-") or cid.startswith("wlep-"):
            ok("contract_id_prefix", cid)
        else:
            bad("contract_id_prefix", f"unknown prefix on {cid!r}")

    # ---- M-section checks (carried over from frozen 0.2.0) ----
    sp = m.get("serving_profile", {})
    grs = sp.get("gate_baseline_reasoning_state")
    if grs in ("REASONING_OFF", "ON", "NOT_APPLICABLE"):
        ok("M05_gate_reasoning_state", grs)
    else:
        bad("M05_gate_reasoning_state", "explicit gate reasoning state required")
    rq, ef = sp.get("reasoning_requested"), sp.get("reasoning_effective")
    if rq and ef:
        ok("M06_requested_effective_recorded")
    else:
        bad("M06_requested_effective_recorded", "both requested and effective reasoning state required")
    hv = m.get("phase2_harness_version")
    if hv:
        ok("M07_phase2_harness_version", str(hv))
    else:
        bad("M07_phase2_harness_version", "missing")

    # ---- N03 improper-rewrite detection ----
    # A welp-* campaign whose contract IDs are ALL wlep-* (with no welp-* counterpart)
    # suggests the campaign was silently relabeled from WLEP to WELP. Reject.
    sid_prefix = sid.split("-", 1)[0] if sid else ""
    contract_ids = list((m.get("contracts") or {}).keys())
    if sid_prefix == "welp":
        legacy_only = all(c.startswith("wlep-") for c in contract_ids) and len(contract_ids) > 0
        if legacy_only:
            bad("N03_improper_rewrite",
                f"snapshot_id starts with welp- but contracts are all wlep-: {contract_ids}")
        else:
            ok("N03_welp_with_welp_contracts", f"{len(contract_ids)} contracts; prefix={sid_prefix}")
    elif sid_prefix == "wlep":
        if any(c.startswith("welp-") for c in contract_ids):
            warn("N03_wlep_snapshot_with_welp_contracts",
                 f"wlep-* snapshot references welp-* contracts: {contract_ids}")
        else:
            ok("N03_wlep_with_wlep_contracts", f"{len(contract_ids)} contracts; prefix={sid_prefix}")
    else:
        # already flagged by N01; nothing more to say
        pass

    # ---- contract_ids allow welp- and wlep- ----
    for cid, cobj in (m.get("contracts") or {}).items():
        if cid.startswith("welp-") or cid.startswith("wlep-"):
            ok("contract_id_prefix", cid)
        else:
            bad("contract_id_prefix", f"unknown prefix on {cid!r}")

    caps = root / "toolchain/runtime_capabilities.json"
    if caps.is_file():
        try:
            c = json.load(open(caps))
            if "runtimes" in c:
                ok("M08_cache_metric_probe_present")
            else:
                warn("M08_cache_metric_probe", "no runtimes section")
        except Exception as e:
            warn("M08_cache_metric_probe_parse", str(e))
    else:
        warn("M08_cache_metric_probe_absent", "runtime_capabilities.json missing")

    ev = m.get("generation_evidence", [])
    for e in ev:
        path = e.get("path", "")
        if os.path.isabs(path):
            ok("M09_absolute_evidence_path", path)
        else:
            bad("M09_relative_evidence_path", path)
        status = e.get("status")
        if status == "COMPLETE":
            if HASH.match(e.get("sha256", "")) and e.get("rows") is not None:
                ok("M10_hash_count_recorded", path)
            else:
                bad("M10_hash_or_count_missing", path)
        elif status == "INVALIDATED":
            if e.get("reason"):
                ok("M11_invalidated_accounted", path)
            else:
                bad("M11_invalidated_unaccounted", path)

    # ---- secret heuristic ----
    for p in root.rglob("*"):
        if p.is_file() and p.stat().st_size < 2_000_000:
            try:
                t = p.read_text(errors="ignore")
            except Exception:
                continue
            if re.search(r"bhk_[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}", t):
                bad("secret_pattern_heuristic", str(p.relative_to(root)))

    return {"valid": not any(f[0] == "error" for f in F), "findings": F}


# ---------------- fixtures (5 required) ----------------
def _good_legacy_wlep(td):
    g = Path(td) / "good_legacy_wlep"
    g.mkdir(parents=True)
    (g / "report.md").write_text("ok\n")
    (g / "WLEP-CONFORMANCE.md").write_text("conformant (legacy WLEP campaign)\n")
    (g / "protocol-findings.md").write_text("PF-01\n")
    (g / "summaries").mkdir(parents=True)
    (g / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "wlep-next-snapshot-2026-08-25-end-to-end"},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "wlep-phase2-harness/0.4.0-draft",
        "contracts": {"wlep-practical-viability": {}, "wlep-reliability": {}},
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "b" * 64, "rows": 90}]}))
    (g / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "wlep-preflight",  # legacy const
        "protocol": {"snapshot_id": "wlep-next-snapshot-2026-08-25-end-to-end", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (g / "toolchain").mkdir()
    (g / "toolchain/runtime_capabilities.json").write_text(json.dumps({
        "runtimes": {"llama.cpp-f280b269": {"status": "CACHE_METRIC_FLOOR_PRESENT", "floor": 74}}}))
    (g / "results").mkdir()
    (g / "results/INVALIDATED-phase2-run1.reason.json").write_text('{"reason":"SHORT_RESPONSE"}')
    return g


def _good_current_welp(td):
    g = Path(td) / "good_current_welp"
    g.mkdir(parents=True)
    (g / "report.md").write_text("ok\n")
    (g / "WELP-CONFORMANCE.md").write_text("conformant (current WELP campaign)\n")
    (g / "protocol-findings.md").write_text("PF-01\n")
    (g / "summaries").mkdir(parents=True)
    (g / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "welp-next-snapshot-2026-08-26-post-rename"},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "welp-phase2-harness/0.1.0-draft",
        "contracts": {"welp-practical-viability": {}, "welp-reliability": {}},
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "c" * 64, "rows": 90}]}))
    (g / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",  # current const
        "protocol": {"snapshot_id": "welp-next-snapshot-2026-08-26-post-rename", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (g / "toolchain").mkdir()
    (g / "toolchain/runtime_capabilities.json").write_text(json.dumps({
        "runtimes": {"llama.cpp-f280b269": {"status": "CACHE_METRIC_FLOOR_PRESENT", "floor": 74}}}))
    (g / "results").mkdir()
    (g / "results/INVALIDATED-phase2-run1.reason.json").write_text('{"reason":"SHORT_RESPONSE"}')
    return g


def _good_new_hierarchy(td):
    """Current artifact hierarchy: REPORT.md primary + WELP-LAB-RECORD.md companion."""
    g = Path(td) / "good_new_hierarchy"
    g.mkdir(parents=True)
    (g / "REPORT.md").write_text(
        "Artifact role: PRIMARY SCIENTIFIC REPORT\nStatus: CURRENT\nok\n")
    (g / "WELP-LAB-RECORD.md").write_text(
        "Artifact role: WELP LAB RECORD\nPrimary scientific report: REPORT.md\n")
    (g / "WELP-CONFORMANCE.md").write_text("conformant (new artifact hierarchy)\n")
    (g / "protocol-findings.md").write_text("PF-01\n")
    (g / "summaries").mkdir(parents=True)
    (g / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "welp-next-snapshot-2026-08-26-post-rename"},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "welp-phase2-harness/0.1.0-draft",
        "contracts": {"welp-practical-viability": {}, "welp-reliability": {}},
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "f" * 64, "rows": 90}]}))
    (g / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",
        "protocol": {"snapshot_id": "welp-next-snapshot-2026-08-26-post-rename", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (g / "toolchain").mkdir()
    (g / "toolchain/runtime_capabilities.json").write_text(json.dumps({
        "runtimes": {"llama.cpp-f280b269": {"status": "CACHE_METRIC_FLOOR_PRESENT", "floor": 74}}}))
    return g


def _ambiguous_report_pair(td):
    """Ambiguity defect: REPORT.md (primary) and report.md coexist in one bundle."""
    b = Path(td) / "bad_ambiguous_report_pair"
    b.mkdir(parents=True)
    (b / "REPORT.md").write_text("Artifact role: PRIMARY SCIENTIFIC REPORT\nStatus: CURRENT\n")
    (b / "report.md").write_text("historical companion (ambiguous)\n")
    (b / "WELP-CONFORMANCE.md").write_text("ok\n")
    (b / "protocol-findings.md").write_text("ok\n")
    (b / "summaries").mkdir(parents=True)
    (b / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "welp-next-snapshot-2026-08-26-post-rename"},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "welp-phase2-harness/0.1.0-draft",
        "contracts": {"welp-practical-viability": {}, "welp-reliability": {}},
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "0" * 64, "rows": 90}]}))
    (b / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",
        "protocol": {"snapshot_id": "welp-next-snapshot-2026-08-26-post-rename", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (b / "toolchain").mkdir()
    (b / "toolchain/runtime_capabilities.json").write_text(json.dumps({
        "runtimes": {"llama.cpp-f280b269": {"status": "CACHE_METRIC_FLOOR_PRESENT", "floor": 74}}}))
    return b


def _new_hierarchy_missing_lab_record(td):
    """New-format bundle without the Lab Record companion: valid, R03 warning."""
    g = Path(td) / "good_new_hierarchy_no_lab_record"
    g.mkdir(parents=True)
    (g / "REPORT.md").write_text("Artifact role: PRIMARY SCIENTIFIC REPORT\nStatus: CURRENT\n")
    (g / "WELP-CONFORMANCE.md").write_text("ok\n")
    (g / "protocol-findings.md").write_text("ok\n")
    (g / "summaries").mkdir(parents=True)
    (g / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "welp-next-snapshot-2026-08-26-post-rename"},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "welp-phase2-harness/0.1.0-draft",
        "contracts": {"welp-practical-viability": {}, "welp-reliability": {}},
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "1" * 64, "rows": 90}]}))
    (g / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",
        "protocol": {"snapshot_id": "welp-next-snapshot-2026-08-26-post-rename", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (g / "toolchain").mkdir()
    (g / "toolchain/runtime_capabilities.json").write_text(json.dumps({
        "runtimes": {"llama.cpp-f280b269": {"status": "CACHE_METRIC_FLOOR_PRESENT", "floor": 74}}}))
    return g


def _invalid_unknown_prefix(td):
    b = Path(td) / "bad_unknown_prefix"
    b.mkdir(parents=True)
    (b / "report.md").write_text("ok\n")
    (b / "WELP-CONFORMANCE.md").write_text("ok\n")
    (b / "protocol-findings.md").write_text("ok\n")
    (b / "summaries").mkdir(parents=True)
    (b / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "wxyz-next-snapshot-2026-09-01-something"},  # unknown prefix
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "unknown-harness/0.1.0",
        "contracts": {"wxyz-practical-viability": {}},  # unknown prefix
        "generation_evidence": []}))
    (b / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "wxyz-preflight",  # unknown
        "protocol": {"snapshot_id": "wxyz-next-snapshot-2026-09-01-something", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    return b


def _improperly_rewritten_legacy(td):
    """Historical WLEP manifest whose identity was silently rewritten to welp-* (N03).

    We model the defect: a historical campaign that was frozen under wlep-* but whose
    campaign_manifest.json was edited to point at a welp-next-snapshot-* ID, with the
    evidence bundle still carrying the original wlep-* contracts. The validator must
    flag the snapshot-id vs evidence-bundle mismatch.
    """
    b = Path(td) / "bad_rewritten_legacy"
    b.mkdir(parents=True)
    (b / "report.md").write_text("ok\n")
    (b / "WELP-CONFORMANCE.md").write_text("ok (but evidence still wlep-*)\n")
    (b / "protocol-findings.md").write_text("ok\n")
    (b / "summaries").mkdir(parents=True)
    (b / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "welp-next-snapshot-2026-08-26-post-rename"},  # silently rewritten
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "wlep-phase2-harness/0.4.0-draft",  # original WLEP
        "contracts": {"wlep-practical-viability": {}, "wlep-reliability": {}},  # original WLEP
        "evidence_origin": "frozen wlep-next-snapshot-2026-08-25-end-to-end",  # provenance
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "d" * 64, "rows": 90}]}))
    (b / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",
        "protocol": {"snapshot_id": "welp-next-snapshot-2026-08-26-post-rename", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    # The validator's prefix-accept logic is permissive (allows welp- or wlep-), so this fixture alone
    # is valid. To detect improper rewriting, the additional check below inspects that
    # WELP campaigns using welp- IDs don't reuse wlep- contracts unless explicitly bridged.
    return b


def _welp_using_legacy_evidence(td):
    """WELP campaign using legacy-compatible evidence (welp-next-snapshot- + welp- contracts
    coexisting with old wlep_*.schema.json validation paths). Should PASS.
    """
    g = Path(td) / "good_welp_legacy_evidence"
    g.mkdir(parents=True)
    (g / "report.md").write_text("ok\n")
    (g / "WELP-CONFORMANCE.md").write_text("conformant (WELP campaign with legacy-compatible evidence)\n")
    (g / "protocol-findings.md").write_text("ok\n")
    (g / "summaries").mkdir(parents=True)
    (g / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": "welp-next-snapshot-2026-08-26-post-rename"},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "welp-phase2-harness/0.1.0-draft",
        "contracts": {"welp-practical-viability": {}, "welp-reliability": {},
                      "welp-context": {}, "welp-native-tools": {}},
        "schema_validations": [
            "schemas/welp_campaign_manifest.schema.json",
            "schemas/welp_serving_profile.schema.json",
            "schemas/wlep_serving_profile.schema.json (legacy-compatible)"
        ],
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "e" * 64, "rows": 90}]}))
    (g / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",
        "protocol": {"snapshot_id": "welp-next-snapshot-2026-08-26-post-rename", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (g / "toolchain").mkdir()
    (g / "toolchain/runtime_capabilities.json").write_text(json.dumps({
        "runtimes": {"llama.cpp-f280b269": {"status": "CACHE_METRIC_FLOOR_PRESENT", "floor": 74}}}))
    return g


def selftest():
    with tempfile.TemporaryDirectory() as td:
        rg_legacy = check(_good_legacy_wlep(td))
        rg_welp = check(_good_current_welp(td))
        rg_mixed = check(_welp_using_legacy_evidence(td))
        rb_unknown = check(_invalid_unknown_prefix(td))
        rb_rewritten = check(_improperly_rewritten_legacy(td))
        rg_new = check(_good_new_hierarchy(td))
        rb_ambig = check(_ambiguous_report_pair(td))
        rg_new_nolr = check(_new_hierarchy_missing_lab_record(td))
        fails = []
        for label, r in [("legacy_wlep_rejected", rg_legacy), ("current_welp_rejected", rg_welp),
                         ("welp_with_legacy_evidence_rejected", rg_mixed),
                         ("new_hierarchy_rejected", rg_new),
                         ("new_hierarchy_without_lab_record_rejected", rg_new_nolr)]:
            if not r["valid"]:
                fails.append(label + ": " + str([x for x in r["findings"] if x[0] == "error"]))
        for label, r in [("unknown_prefix_accepted", rb_unknown), ("improperly_rewritten_legacy_accepted", rb_rewritten),
                         ("ambiguous_report_pair_accepted", rb_ambig)]:
            if r["valid"]:
                fails.append(label + ": " + str([x for x in r["findings"] if x[0] == "error"]))
        if not any(f[0] == "error" and f[1] == "R02_ambiguous_report_pair" for f in rb_ambig["findings"]):
            fails.append("ambiguous_pair_missing_R02_error")
        if not any(f[0] == "warning" and f[1] == "R03_lab_record_expected" for f in rg_new_nolr["findings"]):
            fails.append("new_hierarchy_without_lab_record_missing_R03_warning")
        if not any(f[0] == "warning" and f[1] == "R04_legacy_report_naming" for f in rg_welp["findings"]):
            fails.append("legacy_report_missing_R04_warning")
        print(json.dumps({
            "fixture_sets": 8,
            "accepted_legacy_wlep": rg_legacy["valid"],
            "accepted_current_welp": rg_welp["valid"],
            "accepted_welp_with_legacy_evidence": rg_mixed["valid"],
            "accepted_new_hierarchy": rg_new["valid"],
            "rejected_unknown_prefix": not rb_unknown["valid"],
            "improperly_rewritten_legacy_passed": rb_rewritten["valid"],
            "rejected_ambiguous_report_pair": not rb_ambig["valid"],
            "new_hierarchy_without_lab_record_valid_with_warning": rg_new_nolr["valid"],
            "failures": fails,
            "pass": not fails,
        }, indent=2))
        return 0 if not fails else 1


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    r = check(Path(sys.argv[1]))
    print(json.dumps(r, default=str, indent=1))
    sys.exit(0 if r["valid"] else 1)
