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
  - Report artifact hierarchy (hierarchy-era bundles: protocol snapshot dated
    2026-09-10 or later): REPORT.md primary + WELP-LAB-RECORD.md companion
    expected; REPORT.md + report.md coexistence is REJECTED as an ambiguous
    case-different pair. Frozen pre-hierarchy bundles keep both files
    (warning) and bundles without REPORT.md keep the report.md requirement
    (warning only) so frozen evidence bundles remain valid unchanged.

New rules:
  N01  Protocol snapshot id must match ^(welp|wlep)-next-snapshot-
  N02  Pre-flight "preflight" field must be one of welp-preflight or wlep-preflight
  N03  Manifest whose snapshot_id has been rewritten to welp- while the evidence
       bundle still references only frozen historical wlep-* contracts is REJECTED
  N04  WELP campaign using frozen-compatible evidence (e.g. welp-next-snapshot-*
       with wlep_*.schema.json validation paths) is ACCEPTED
  R01  REPORT.md is the primary scientific report of new-format bundles
  R02  REPORT.md + report.md coexistence: error in hierarchy-era bundles
       (protocol snapshot >= 2026-09-10); warning for frozen pre-hierarchy
       bundles, which remain valid unchanged
  R03  WELP-LAB-RECORD.md expected companion in new-format bundles (warning if absent)
  R04  (warning) historical report.md naming; new campaigns use REPORT.md + WELP-LAB-RECORD.md
  R05  LocalMaxxing completion disposition (summaries/localmaxxing.json):
       REQUIRED (error) in new-format bundles whose campaign snapshot date is
       >= 2026-09-10; expected (warning) in earlier bundles so frozen evidence
       remains valid unchanged
  R06  LocalMaxxing disposition content: status must be exactly SUBMITTED |
       MEASURED_NOT_SUBMITTED | NOT_ELIGIBLE | BLOCKED; SUBMITTED requires
       origin (NEW | VERIFIED_EXISTING) + submission_ref; the other statuses
       require reason
  R07  Website publication disposition (summaries/website-publication.json):
       REQUIRED (error) in new-format bundles whose campaign snapshot date is
       >= 2026-09-12; expected (warning) in earlier bundles so frozen evidence
       remains valid unchanged
  R08  Website publication disposition content: disposition must be exactly
       WEBSITE_READY | WEBSITE_BLOCKED | NOT_FOR_PUBLICATION | WEBSITE_PUBLISHED;
       WEBSITE_BLOCKED / NOT_FOR_PUBLICATION require reason; the other statuses
       require website_record_slug; canonical_evidence.state must be exactly
       PUBLISHED | PENDING_HUMAN_GATE; PUBLISHED requires a canonical_evidence
       URL; PENDING_HUMAN_GATE must not carry a claimed canonical URL; when the
       optional identity object is present it must carry non-empty model_id,
       profile_id, event_id, event_type, a YYYY-MM-DD event_date when given,
       a non-empty evidence_scope string array when given, and a valid
       profile_status when given (identity is optional so frozen exports
       remain valid unchanged)

Usage: validate_campaign_welp.py <campaign_dir> | selftest
"""
import json, os, re, sys, tempfile
from pathlib import Path

HASH = re.compile(r"^[a-f0-9]{64}$")
AUTH_STATUSES = {"READY", "AUTH_BLOCKED", "CLI_INCOMPATIBLE", "NOT_APPLICABLE"}
SNAPSHOT_RE = re.compile(r"^(welp|wlep)-next-snapshot-[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9-]+)?$")
ALLOWED_PREFLIGHT = {"wlep-preflight", "welp-preflight"}
LMX_STATUSES = {"SUBMITTED", "MEASURED_NOT_SUBMITTED", "NOT_ELIGIBLE", "BLOCKED"}
LMX_DISPOSITION_REQUIRED_FROM = "2026-09-10"  # campaign snapshot dates from this day on
REPORT_HIERARCHY_FROM = "2026-09-10"  # REPORT.md/WELP-LAB-RECORD.md hierarchy effective from this snapshot date
WEBSITE_STATUSES = {"WEBSITE_READY", "WEBSITE_BLOCKED", "NOT_FOR_PUBLICATION", "WEBSITE_PUBLISHED"}
WEBSITE_EVIDENCE_STATES = {"PUBLISHED", "PENDING_HUMAN_GATE"}
WEBSITE_DISPOSITION_REQUIRED_FROM = "2026-09-12"  # campaign snapshot dates from this day on
PROFILE_STATUSES = {"current", "current-alternate", "historical", "superseded", "specialized"}


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
    sid = (m.get("protocol_snapshot") or {}).get("id", "")
    mdate = re.match(r"^(?:welp|wlep)-next-snapshot-([0-9]{4}-[0-9]{2}-[0-9]{2})", sid)

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
            # Frozen pre-hierarchy campaigns (protocol snapshot predating the
            # report artifact hierarchy) may legitimately carry REPORT.md +
            # report.md; only hierarchy-era campaigns are held to the single
            # primary report rule.
            if mdate and mdate.group(1) < REPORT_HIERARCHY_FROM:
                warn("R02_historical_report_pair",
                     f"REPORT.md and report.md coexist in a frozen pre-hierarchy "
                     f"campaign (snapshot {mdate.group(1)} < {REPORT_HIERARCHY_FROM}); "
                     "accepted as historical evidence; do not rename or delete")
            else:
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

    # ---- N01 protocol snapshot id pattern ----
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

    # ---- R05/R06 LocalMaxxing completion disposition ----
    lmx_file = root / "summaries/localmaxxing.json"
    lmx = None
    if lmx_file.is_file():
        try:
            lmx = json.load(open(lmx_file))
        except Exception as e:
            bad("R06_localmaxxing_parse", str(e))
    lmx_required = bool(has_primary and mdate and mdate.group(1) >= LMX_DISPOSITION_REQUIRED_FROM)
    if lmx is None:
        if lmx_required:
            bad("R05_localmaxxing_disposition_required",
                f"campaign snapshot dated {mdate.group(1)} (>= {LMX_DISPOSITION_REQUIRED_FROM}) "
                "requires summaries/localmaxxing.json with the LocalMaxxing completion disposition")
        else:
            warn("R05_localmaxxing_disposition_expected",
                 "summaries/localmaxxing.json absent; current campaigns record the "
                 "LocalMaxxing completion disposition (status, origin, actual prompt tokens)")
    elif isinstance(lmx, dict):
        lmx_status = lmx.get("status")
        if lmx_status in LMX_STATUSES:
            ok("R06_localmaxxing_status", lmx_status)
            if lmx_status == "SUBMITTED":
                if lmx.get("submission_ref"):
                    ok("R06_localmaxxing_reference", str(lmx["submission_ref"]))
                else:
                    bad("R06_localmaxxing_reference_missing",
                        "SUBMITTED requires submission_ref (id/URL of the recorded submission)")
                if lmx.get("origin") not in ("NEW", "VERIFIED_EXISTING"):
                    bad("R06_localmaxxing_origin",
                        f"SUBMITTED requires origin NEW or VERIFIED_EXISTING, got {lmx.get('origin')!r}")
            elif not lmx.get("reason"):
                bad("R06_localmaxxing_reason_missing",
                    f"{lmx_status} requires the exact reason/blocker")
        else:
            bad("R06_localmaxxing_status",
                f"invalid status {lmx_status!r}; expected one of {sorted(LMX_STATUSES)}")
    else:
        bad("R06_localmaxxing_parse", "summaries/localmaxxing.json must contain a JSON object")

    # ---- R07/R08 website publication disposition ----
    web_file = root / "summaries/website-publication.json"
    web = None
    if web_file.is_file():
        try:
            web = json.load(open(web_file))
        except Exception as e:
            bad("R08_website_publication_parse", str(e))
    web_required = bool(has_primary and mdate and mdate.group(1) >= WEBSITE_DISPOSITION_REQUIRED_FROM)
    if web is None:
        if web_required:
            bad("R07_website_publication_disposition_required",
                f"campaign snapshot dated {mdate.group(1)} (>= {WEBSITE_DISPOSITION_REQUIRED_FROM}) "
                "requires summaries/website-publication.json with the website publication disposition")
        else:
            warn("R07_website_publication_disposition_expected",
                 "summaries/website-publication.json absent; current campaigns record the "
                 "website publication disposition (disposition, canonical evidence state, record slug)")
    elif isinstance(web, dict):
        web_status = web.get("disposition")
        if web_status in WEBSITE_STATUSES:
            ok("R08_website_disposition", web_status)
            if web_status in ("WEBSITE_BLOCKED", "NOT_FOR_PUBLICATION"):
                if web.get("reason"):
                    ok("R08_website_reason", str(web["reason"]))
                else:
                    bad("R08_website_reason_missing",
                        f"{web_status} requires the exact reason")
            elif not web.get("website_record_slug"):
                bad("R08_website_record_slug_missing",
                    f"{web_status} requires website_record_slug")
            evidence = web.get("canonical_evidence")
            if not isinstance(evidence, dict):
                bad("R08_website_evidence_state",
                    "canonical_evidence object with state PUBLISHED | PENDING_HUMAN_GATE required")
            else:
                ev_state = evidence.get("state")
                if ev_state in WEBSITE_EVIDENCE_STATES:
                    ok("R08_website_evidence_state", ev_state)
                    if ev_state == "PUBLISHED" and not evidence.get("url"):
                        bad("R08_website_evidence_url_missing",
                            "canonical_evidence.state PUBLISHED requires the canonical evidence URL")
                    if ev_state == "PENDING_HUMAN_GATE" and evidence.get("url"):
                        bad("R08_website_evidence_url_pending_conflict",
                            "canonical_evidence.state PENDING_HUMAN_GATE must not claim a canonical URL")
                else:
                    bad("R08_website_evidence_state",
                        f"invalid canonical_evidence.state {ev_state!r}; expected one of {sorted(WEBSITE_EVIDENCE_STATES)}")
            # ---- R08 identity (optional, additive 2026-09-12) ----
            identity = web.get("identity")
            if identity is not None:
                if isinstance(identity, dict):
                    missing_ident = [k for k in ("model_id", "profile_id", "event_id", "event_type")
                                     if not str(identity.get(k) or "").strip()]
                    if missing_ident:
                        bad("R08_website_identity_incomplete",
                            f"identity present but missing non-empty {', '.join(missing_ident)}")
                    else:
                        ok("R08_website_identity",
                           f"{identity.get('model_id')} / {identity.get('profile_id')} / {identity.get('event_id')}")
                    idate = identity.get("event_date")
                    if idate is not None and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(idate)):
                        bad("R08_website_identity_event_date",
                            f"identity.event_date must be YYYY-MM-DD, got {idate!r}")
                    iscope = identity.get("evidence_scope")
                    if iscope is not None and (not isinstance(iscope, list) or not iscope
                                               or not all(isinstance(s, str) and s.strip() for s in iscope)):
                        bad("R08_website_identity_scope",
                            "identity.evidence_scope must be a non-empty array of surface strings when present")
                    istatus = identity.get("profile_status")
                    if istatus is not None and istatus not in PROFILE_STATUSES:
                        bad("R08_website_identity_profile_status",
                            f"invalid identity.profile_status {istatus!r}; expected one of {sorted(PROFILE_STATUSES)}")
                else:
                    bad("R08_website_identity_parse", "identity must be a JSON object when present")
        else:
            bad("R08_website_disposition",
                f"invalid disposition {web_status!r}; expected one of {sorted(WEBSITE_STATUSES)}")
    else:
        bad("R08_website_publication_parse", "summaries/website-publication.json must contain a JSON object")

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
        "protocol_snapshot": {"id": "welp-next-snapshot-2026-09-10-hierarchy"},
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
        "protocol": {"snapshot_id": "welp-next-snapshot-2026-09-10-hierarchy", "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (b / "summaries/localmaxxing.json").write_text(json.dumps(
        {"status": "SUBMITTED", "origin": "NEW",
         "submission_ref": "cmtexample0000000000000", "actual_prompt_tokens": 330}))
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


def _historical_pre_hierarchy_pair(td):
    """Frozen pre-hierarchy campaign: REPORT.md + report.md coexist (MiniCPM shape).

    Real bundles executed 2026-09-09/10 under protocol snapshot
    welp-next-snapshot-2026-08-26-post-rename predate the report artifact
    hierarchy; the coexisting pair is frozen historical evidence, not a defect.
    """
    g = Path(td) / "good_historical_pre_hierarchy_pair"
    g.mkdir(parents=True)
    (g / "REPORT.md").write_text("Artifact role: PRIMARY SCIENTIFIC REPORT\nStatus: CURRENT\n")
    (g / "report.md").write_text("historical report (frozen pre-hierarchy bundle)\n")
    (g / "WELP-CONFORMANCE.md").write_text("conformant (frozen pre-hierarchy campaign)\n")
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
                                 "status": "COMPLETE", "sha256": "9" * 64, "rows": 90}]}))
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


def _new_format_localmaxxing_bundle(td, name, snapshot_date, lmx_summary, web_summary=None):
    """Shared builder: new-format bundle with a post-integration snapshot date."""
    g = Path(td) / name
    g.mkdir(parents=True)
    (g / "REPORT.md").write_text("Artifact role: PRIMARY SCIENTIFIC REPORT\nStatus: CURRENT\n")
    (g / "WELP-LAB-RECORD.md").write_text(
        "Artifact role: WELP LAB RECORD\nPrimary scientific report: REPORT.md\n")
    (g / "WELP-CONFORMANCE.md").write_text("ok\n")
    (g / "protocol-findings.md").write_text("ok\n")
    (g / "summaries").mkdir(parents=True)
    snap = f"welp-next-snapshot-{snapshot_date}-localmaxxing"
    (g / "summaries/campaign_manifest.json").write_text(json.dumps({
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": snap},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "welp-phase2-harness/0.1.0-draft",
        "contracts": {"welp-practical-viability": {}, "welp-reliability": {}},
        "generation_evidence": [{"path": "/workspace/camp/results/phase3_raw.jsonl",
                                 "status": "COMPLETE", "sha256": "b" * 64, "rows": 90}]}))
    (g / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",
        "protocol": {"snapshot_id": snap, "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (g / "toolchain").mkdir()
    (g / "toolchain/runtime_capabilities.json").write_text(json.dumps({
        "runtimes": {"llama.cpp-f280b269": {"status": "CACHE_METRIC_FLOOR_PRESENT", "floor": 74}}}))
    if lmx_summary is not None:
        (g / "summaries/localmaxxing.json").write_text(json.dumps(lmx_summary))
    if web_summary is not None:
        (g / "summaries/website-publication.json").write_text(json.dumps(web_summary))
    return g


def _good_new_format_with_localmaxxing(td):
    """Post-integration new-format bundle with a valid SUBMITTED disposition."""
    return _new_format_localmaxxing_bundle(
        td, "good_new_format_localmaxxing", "2026-09-10",
        {"status": "SUBMITTED", "origin": "NEW", "submission_ref": "cmtexample0000000000000",
         "actual_prompt_tokens": 330})


def _bad_new_format_missing_localmaxxing(td):
    """Post-integration new-format bundle without the disposition: R05 error."""
    return _new_format_localmaxxing_bundle(
        td, "bad_new_format_missing_localmaxxing", "2026-09-10", None)


def _bad_localmaxxing_invalid_status(td):
    """Deprecated NOT_APPLICABLE status: R06 error."""
    return _new_format_localmaxxing_bundle(
        td, "bad_localmaxxing_invalid_status", "2026-09-10",
        {"status": "NOT_APPLICABLE"})


def _good_new_format_with_website(td):
    """Post-website-integration new-format bundle with a valid WEBSITE_READY disposition."""
    return _new_format_localmaxxing_bundle(
        td, "good_new_format_website", "2026-09-12",
        {"status": "SUBMITTED", "origin": "NEW", "submission_ref": "cmtexample0000000000000",
         "actual_prompt_tokens": 330},
        {"schema": "wumbolabs-labs-publication/1", "campaign": "example-campaign",
         "disposition": "WEBSITE_READY",
         "model": {"display_name": "Example Model"},
         "artifact": {"tested": "example GGUF", "precision": "Q8_0"},
         "runtime": {"engine": "llama.cpp"},
         "hardware": {"gpu": "Example GPU"},
         "welp": {"outcome": "PASS — EXAMPLE", "classification": "READY_WITH_GUARDRAILS"},
         "context": {"envelope_complete": True},
         "quality": {"reliability_summary": "20/20 bounded"},
         "localmaxxing": {"status": "SUBMITTED", "submission_ref": "cmtexample0000000000000"},
         "canonical_evidence": {"state": "PENDING_HUMAN_GATE", "url": None,
                                "proposed_repo": "eval-example-model"},
         "website_record_slug": "example-model",
         "public_summary": "Bounded example summary."})


def _bad_new_format_missing_website(td):
    """Post-website-integration new-format bundle without the disposition: R07 error."""
    return _new_format_localmaxxing_bundle(
        td, "bad_new_format_missing_website", "2026-09-12",
        {"status": "SUBMITTED", "origin": "NEW", "submission_ref": "cmtexample0000000000000",
         "actual_prompt_tokens": 330},
        None)


def _bad_website_invalid_disposition(td):
    """Invalid website disposition value: R08 error."""
    return _new_format_localmaxxing_bundle(
        td, "bad_website_invalid_disposition", "2026-09-12",
        {"status": "SUBMITTED", "origin": "NEW", "submission_ref": "cmtexample0000000000000",
         "actual_prompt_tokens": 330},
        {"schema": "wumbolabs-labs-publication/1", "campaign": "example-campaign",
         "disposition": "PUBLISHED",
         "canonical_evidence": {"state": "PENDING_HUMAN_GATE"},
         "website_record_slug": "example-model"})


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
        rg_hist_pair = check(_historical_pre_hierarchy_pair(td))
        rg_lmx = check(_good_new_format_with_localmaxxing(td))
        rb_lmx_missing = check(_bad_new_format_missing_localmaxxing(td))
        rb_lmx_status = check(_bad_localmaxxing_invalid_status(td))
        rg_web = check(_good_new_format_with_website(td))
        rb_web_missing = check(_bad_new_format_missing_website(td))
        rb_web_status = check(_bad_website_invalid_disposition(td))
        fails = []
        for label, r in [("legacy_wlep_rejected", rg_legacy), ("current_welp_rejected", rg_welp),
                         ("welp_with_legacy_evidence_rejected", rg_mixed),
                         ("new_hierarchy_rejected", rg_new),
                         ("new_hierarchy_without_lab_record_rejected", rg_new_nolr),
                         ("new_format_localmaxxing_rejected", rg_lmx),
                         ("new_format_website_rejected", rg_web),
                         ("historical_pre_hierarchy_pair_rejected", rg_hist_pair)]:
            if not r["valid"]:
                fails.append(label + ": " + str([x for x in r["findings"] if x[0] == "error"]))
        for label, r in [("unknown_prefix_accepted", rb_unknown), ("improperly_rewritten_legacy_accepted", rb_rewritten),
                         ("ambiguous_report_pair_accepted", rb_ambig),
                         ("missing_localmaxxing_accepted", rb_lmx_missing),
                         ("invalid_localmaxxing_status_accepted", rb_lmx_status),
                         ("missing_website_accepted", rb_web_missing),
                         ("invalid_website_disposition_accepted", rb_web_status)]:
            if r["valid"]:
                fails.append(label + ": " + str([x for x in r["findings"] if x[0] == "error"]))
        if not any(f[0] == "error" and f[1] == "R02_ambiguous_report_pair" for f in rb_ambig["findings"]):
            fails.append("ambiguous_pair_missing_R02_error")
        if not any(f[0] == "warning" and f[1] == "R02_historical_report_pair" for f in rg_hist_pair["findings"]):
            fails.append("historical_pair_missing_R02_legacy_warning")
        if not any(f[0] == "warning" and f[1] == "R03_lab_record_expected" for f in rg_new_nolr["findings"]):
            fails.append("new_hierarchy_without_lab_record_missing_R03_warning")
        if not any(f[0] == "warning" and f[1] == "R04_legacy_report_naming" for f in rg_welp["findings"]):
            fails.append("legacy_report_missing_R04_warning")
        if not any(f[0] == "warning" and f[1] == "R05_localmaxxing_disposition_expected" for f in rg_new["findings"]):
            fails.append("pre_integration_new_format_missing_R05_warning")
        if not any(f[0] == "error" and f[1] == "R05_localmaxxing_disposition_required" for f in rb_lmx_missing["findings"]):
            fails.append("missing_localmaxxing_missing_R05_error")
        if not any(f[0] == "error" and f[1] == "R06_localmaxxing_status" for f in rb_lmx_status["findings"]):
            fails.append("invalid_localmaxxing_status_missing_R06_error")
        if not any(f[0] == "warning" and f[1] == "R07_website_publication_disposition_expected" for f in rg_lmx["findings"]):
            fails.append("pre_website_integration_new_format_missing_R07_warning")
        if not any(f[0] == "error" and f[1] == "R07_website_publication_disposition_required" for f in rb_web_missing["findings"]):
            fails.append("missing_website_missing_R07_error")
        if not any(f[0] == "error" and f[1] == "R08_website_disposition" for f in rb_web_status["findings"]):
            fails.append("invalid_website_disposition_missing_R08_error")
        print(json.dumps({
            "fixture_sets": 15,
            "accepted_legacy_wlep": rg_legacy["valid"],
            "accepted_current_welp": rg_welp["valid"],
            "accepted_welp_with_legacy_evidence": rg_mixed["valid"],
            "accepted_new_hierarchy": rg_new["valid"],
            "accepted_new_format_localmaxxing": rg_lmx["valid"],
            "accepted_new_format_website": rg_web["valid"],
            "accepted_historical_pre_hierarchy_pair": rg_hist_pair["valid"],
            "rejected_new_format_missing_localmaxxing": not rb_lmx_missing["valid"],
            "rejected_invalid_localmaxxing_status": not rb_lmx_status["valid"],
            "rejected_new_format_missing_website": not rb_web_missing["valid"],
            "rejected_invalid_website_disposition": not rb_web_status["valid"],
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
