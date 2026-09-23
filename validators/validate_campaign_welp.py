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

Methodology-revision rules (enforced for campaign snapshot dates >= 2026-09-19
only; frozen historical bundles remain valid unchanged):
  R09  CP-1 outcome/finish accounting: manifest carries outcome_semantics
       {contract: welp-outcomes-0.1.0-draft, task_outcome_triples: true} and
       phase_finish_accounting entries; COMPLETE rows with missing/unknown
       finish reasons are an error.
  R10  Fixture/scorer hash identity: manifest fixtures/scorers entries carry
       64-hex sha256; when the referenced path resolves against the WELP repo
       root, the recorded hash must match the file bytes.
  R11  campaign_outcome present and exactly COMPLETE_PASS | COMPLETE_WITH_GAPS
       | FAILED_EXECUTION | BLOCKED (welp-final-classification 0.2.0-draft).
  R12  Generation-budget policy record (welp-generation-budget contract) and
       reliability scorer v2 identity with selftest=PASS.
  R13  Context validation evidence when the context phase executed: exact
       required depth set [2,25,50,75,95], placement preflight PASS with
       max error <= 0.5 pp, and the standardized 512-token reserve.
  R14  Cache policy record: scientific_arms DISABLED_UNCACHED with a
       verification marker (cached arms must be declared separately/labeled).

Prospective real-work revision (snapshot dates >= 2026-09-23):
  R15  Deployment/prompt lanes frozen by identity and bounded calibration.
  R16  Context preflight uses Family A 1.2.0 final-token construction and
       lane-specific reserves; classification dimensions are profile-pure.

Usage: validate_campaign_welp.py <campaign_dir> | selftest
"""
import hashlib
import json, os, re, sys, tempfile
from pathlib import Path
from validate_publication import evidence_errors

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
METHODOLOGY_REVISION_FROM = "2026-09-19"  # CP-1..CP-12 outcome/budget semantics from this snapshot date on
REAL_WORK_REVISION_FROM = "2026-09-23"
DEPLOYMENT_LANES_CONTRACT = "welp-deployment-lanes-0.1.0-draft"
PROFILE_DIMENSIONS = {"SEMANTIC_CAPABILITY", "BUDGET_DISCIPLINE",
                      "CONTEXT_USABILITY", "INTEGRATION_QUALITY"}
CAMPAIGN_OUTCOMES = {"COMPLETE_PASS", "COMPLETE_WITH_GAPS", "FAILED_EXECUTION", "BLOCKED"}
REQUIRED_CONTEXT_DEPTHS_PCT = [2.0, 25.0, 50.0, 75.0, 95.0]
STANDARD_RESERVE_TOKENS = 512
RELIABILITY_SCORER_V2 = "welp-reliability-scorer/2"
OUTCOMES_CONTRACT = "welp-outcomes-0.1.0-draft"
BUDGET_CONTRACT = "welp-generation-budget-0.1.0-draft"
REPO_ROOT = Path(__file__).resolve().parent.parent


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
                    if ev_state == "PUBLISHED" and not evidence.get("url") and evidence.get("repo") != "WumboLabs/evaluations":
                        bad("R08_website_evidence_url_missing",
                            "legacy PUBLISHED evidence requires its canonical evidence URL")
                    if ev_state == "PENDING_HUMAN_GATE" and evidence.get("url"):
                        bad("R08_website_evidence_url_pending_conflict",
                            "canonical_evidence.state PENDING_HUMAN_GATE must not claim a canonical URL")
                else:
                    bad("R08_website_evidence_state",
                        f"invalid canonical_evidence.state {ev_state!r}; expected one of {sorted(WEBSITE_EVIDENCE_STATES)}")
                for detail in evidence_errors(web):
                    bad("R08_website_publication_contract", detail)
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

    # ---- Methodology-revision rules R09-R14 (snapshot date >= 2026-09-19) ----
    revision_era = bool(mdate and mdate.group(1) >= METHODOLOGY_REVISION_FROM)
    if revision_era:
        # R09 CP-1 outcome/finish accounting
        os_ = m.get("outcome_semantics")
        if isinstance(os_, dict) and os_.get("contract") == OUTCOMES_CONTRACT and os_.get("task_outcome_triples") is True:
            ok("R09_outcome_semantics", OUTCOMES_CONTRACT)
        else:
            bad("R09_outcome_semantics_required",
                f"manifest.outcome_semantics must declare {{contract: {OUTCOMES_CONTRACT}, task_outcome_triples: true}}")
        pfa = m.get("phase_finish_accounting")
        if isinstance(pfa, list) and pfa:
            for entry in pfa:
                if not isinstance(entry, dict) or not entry.get("phase"):
                    bad("R09_finish_accounting_entry", f"malformed entry: {entry!r}")
                    continue
                missing = entry.get("complete_missing_finish", 0)
                if missing:
                    bad("R09_finish_accounting",
                        f"phase {entry['phase']}: {missing} COMPLETE rows with missing/unknown finish_reason")
                else:
                    ok("R09_finish_accounting", str(entry.get("phase")))
        else:
            bad("R09_finish_accounting_required",
                "manifest.phase_finish_accounting must list per-phase finish accounting")

        # R10 fixture/scorer hash identity
        for section in ("fixtures", "scorers"):
            items = m.get(section) or {}
            if not isinstance(items, dict) or not items:
                bad(f"R10_{section}_required", f"manifest.{section} must record hash identity")
                continue
            for name, meta in items.items():
                if not isinstance(meta, dict) or not HASH.match(str(meta.get("sha256", ""))):
                    bad(f"R10_{section}_hash", f"{name}: 64-hex sha256 required")
                    continue
                ok(f"R10_{section}_hash", name)
                path = meta.get("path")
                if path:
                    candidate = REPO_ROOT / str(path)
                    if candidate.is_file():
                        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
                        if actual != meta["sha256"]:
                            if mdate and mdate.group(1) < REAL_WORK_REVISION_FROM:
                                frozen = REPO_ROOT / "snapshot-freeze" / sid / "manifest.json"
                                if frozen.is_file():
                                    groups = json.loads(frozen.read_text()).get("frozen_artifact_sha256", {})
                                    recorded = groups.get(section, {}).get(str(path))
                                else:
                                    recorded = None
                                if recorded == meta["sha256"]:
                                    warn(f"R10_{section}_historical_hash",
                                         f"{name}: matches frozen snapshot, not changed current source")
                                else:
                                    bad(f"R10_{section}_hash_mismatch",
                                        f"{name}: neither current source nor frozen snapshot matches")
                            else:
                                bad(f"R10_{section}_hash_mismatch",
                                    f"{name}: recorded sha256 does not match {path} bytes")
                        else:
                            ok(f"R10_{section}_hash_verified", name)

        # R11 campaign execution outcome
        cout = m.get("campaign_outcome")
        if cout in CAMPAIGN_OUTCOMES:
            ok("R11_campaign_outcome", cout)
        else:
            bad("R11_campaign_outcome_required",
                f"campaign_outcome must be one of {sorted(CAMPAIGN_OUTCOMES)}")

        # R12 budget policy + reliability scorer v2 selftest
        gb = m.get("generation_budget")
        if isinstance(gb, dict) and gb.get("contract") == BUDGET_CONTRACT:
            ok("R12_generation_budget", BUDGET_CONTRACT)
        else:
            bad("R12_generation_budget_required",
                f"manifest.generation_budget must declare {{contract: {BUDGET_CONTRACT}}}")
        scorers = m.get("scorers") or {}
        rel = scorers.get(RELIABILITY_SCORER_V2) if isinstance(scorers, dict) else None
        if isinstance(rel, dict) and rel.get("selftest") == "PASS":
            ok("R12_reliability_scorer_v2_selftest", RELIABILITY_SCORER_V2)
        else:
            bad("R12_reliability_scorer_v2_selftest_required",
                f"scorers['{RELIABILITY_SCORER_V2}'] with selftest=PASS required "
                "before live reliability use")

        # R13 context validation evidence (only when the context phase executed)
        phases = m.get("phases_executed") or []
        ctxv = m.get("context_validation")
        if "context" in phases or ctxv is not None:
            if not isinstance(ctxv, dict):
                bad("R13_context_validation_required",
                    "context phase executed: manifest.context_validation required")
            else:
                depths = ctxv.get("depths_pct")
                if depths != REQUIRED_CONTEXT_DEPTHS_PCT:
                    bad("R13_context_depth_set",
                        f"depths_pct must be exactly {REQUIRED_CONTEXT_DEPTHS_PCT}, got {depths!r}")
                else:
                    ok("R13_context_depth_set", "2/25/50/75/95")
                if (ctxv.get("placement_preflight_pass") is True
                        and isinstance(ctxv.get("max_placement_error_pp"), (int, float))
                        and ctxv["max_placement_error_pp"] <= 0.5):
                    ok("R13_context_placement_preflight", str(ctxv["max_placement_error_pp"]))
                else:
                    bad("R13_context_placement_preflight",
                        "placement_preflight_pass=true with max_placement_error_pp <= 0.5 required")
                if mdate and mdate.group(1) >= REAL_WORK_REVISION_FROM:
                    lanes = ctxv.get("lane_reserves")
                    deployment = m.get("deployment_lanes")
                    budgets = deployment.get("budgets") if isinstance(deployment, dict) else {}
                    budgets = budgets if isinstance(budgets, dict) else {}
                    if (isinstance(lanes, dict)
                            and lanes.get("semantic") == budgets.get("semantic_ceiling")
                            and lanes.get("operational") == budgets.get("operational_ceiling")
                            and type(lanes.get("semantic")) is int
                            and type(lanes.get("operational")) is int
                            and lanes["semantic"] > 0 and lanes["operational"] > 0
                            and ctxv.get("family_a_version") == "1.2.0-draft"
                            and ctxv.get("construction") == "final-rendered-token-solver"
                            and ctxv.get("inference_tokens_match_preflight") is True
                            and any(isinstance(v, dict) and
                                    v.get("path") == "fixtures/useful_context/family-a.json"
                                    for v in (m.get("fixtures") or {}).values())):
                        ok("R16_context_lane_preflight", "Family A 1.2; lane-specific reserves")
                    else:
                        bad("R16_context_lane_preflight",
                            "Family A 1.2 final-token solver, lane reserves and matching inference tokens required")
                elif ctxv.get("reserve_tokens") == STANDARD_RESERVE_TOKENS:
                    ok("R13_context_reserve", str(STANDARD_RESERVE_TOKENS))
                else:
                    bad("R13_context_reserve",
                        f"historical reserve {STANDARD_RESERVE_TOKENS} required")
        else:
            warn("R13_context_not_executed",
                 "context phase not in phases_executed; if the campaign stopped early this is expected — record the stop reason")

        # R14 cache policy
        cp = m.get("cache_policy")
        if isinstance(cp, dict) and cp.get("scientific_arms") == "DISABLED_UNCACHED" and cp.get("verification"):
            ok("R14_cache_policy", str(cp.get("verification")))
        else:
            bad("R14_cache_policy_required",
                "cache_policy {scientific_arms: DISABLED_UNCACHED, verification: <probe/telemetry evidence>} required")

        if mdate and mdate.group(1) >= REAL_WORK_REVISION_FROM:
            lanes = m.get("deployment_lanes")
            prompt = lanes.get("prompt_lanes") if isinstance(lanes, dict) else None
            budget = lanes.get("budgets") if isinstance(lanes, dict) else None
            if (isinstance(lanes, dict) and lanes.get("contract") == DEPLOYMENT_LANES_CONTRACT
                    and isinstance(prompt, dict) and {"MINIMAL", "DEPLOYMENT"} <= set(prompt)
                    and all(isinstance(v, dict) and HASH.fullmatch(str(v.get("sha256", "")))
                            and v.get("profile_id") for v in prompt.values())
                    and isinstance(budget, dict) and type(budget.get("semantic_ceiling")) is int
                    and budget["semantic_ceiling"] in (512, 1024, 2048, 4096, 8192)
                    and budget.get("calibration_predeclared") is True
                    and type(budget.get("operational_ceiling")) is int
                    and budget["operational_ceiling"] > 0):
                ok("R15_deployment_lanes", DEPLOYMENT_LANES_CONTRACT)
            else:
                bad("R15_deployment_lanes", "frozen prompt identities and bounded calibrated/operational ceilings required")
            classification = m.get("classification")
            if m.get("campaign_outcome") not in {"BLOCKED", "FAILED_EXECUTION"}:
                if (isinstance(classification, dict)
                        and classification.get("contract") == "welp-final-classification-0.3.0-draft"
                        and classification.get("profile_id")
                        and isinstance(classification.get("dimension_profile_ids"), dict)
                        and set(classification["dimension_profile_ids"]) == PROFILE_DIMENSIONS
                        and set(classification["dimension_profile_ids"].values())
                            == {classification["profile_id"]}):
                    ok("R16_classification_profile", classification["profile_id"])
                else:
                    bad("R16_classification_profile", "all classification dimensions must share the selected profile")
            elif classification and classification.get("readiness") is not None:
                if not (m.get("campaign_outcome") == "BLOCKED"
                        and classification.get("readiness") == "INTEGRATION_BLOCKED"
                        and classification.get("integration_evidence")):
                    bad("R16_blocked_verdict", "blocked/failed execution cannot assert model readiness without demonstrated integration evidence")
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
                                "proposed_repo": "WumboLabs/evaluations"},
         "identity": {"model_id": "example-model", "profile_id": "example-model-q8",
                      "event_id": "example-evaluation", "event_type": "initial-evaluation"},
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


# ---------------- methodology-revision era fixtures (R09-R14) ----------------

REVISION_SNAPSHOT = "welp-next-snapshot-2026-09-19-methodology-revision"


def _sha256_of(relpath):
    return hashlib.sha256((REPO_ROOT / relpath).read_bytes()).hexdigest()


def _revision_manifest(**overrides):
    m = {
        "model": {"sha256": "a" * 64},
        "protocol_snapshot": {"id": REVISION_SNAPSHOT},
        "serving_profile": {"effective": {"slot_count": 1},
                            "gate_baseline_reasoning_state": "REASONING_OFF",
                            "reasoning_requested": "REASONING_OFF",
                            "reasoning_effective": "REASONING_OFF"},
        "phase2_harness_version": "welp-phase-harness/1.0.0-draft",
        "contracts": {"welp-outcomes": {}, "welp-generation-budget": {},
                      "welp-reliability": {}, "welp-final-classification": {}},
        "generation_evidence": [{"path": "/workspace/camp/results/reliability_raw_seed42.jsonl",
                                 "status": "COMPLETE", "sha256": "b" * 64, "rows": 20}],
        "outcome_semantics": {"contract": OUTCOMES_CONTRACT, "task_outcome_triples": True},
        "phase_finish_accounting": [
            {"phase": "reliability", "complete_rows": 38, "complete_missing_finish": 0},
            {"phase": "useful_context", "complete_rows": 2, "complete_missing_finish": 0},
        ],
        "fixtures": {
            "welp-reliability-sample-20": {
                "path": "fixtures/reliability/welp-reliability-sample-20-v2.json",
                "sha256": _sha256_of("fixtures/reliability/welp-reliability-sample-20-v2.json")},
        },
        "scorers": {
            RELIABILITY_SCORER_V2: {
                "path": "scorers/score_reliability.py",
                "sha256": _sha256_of("scorers/score_reliability.py"),
                "selftest": "PASS"},
        },
        "campaign_outcome": "COMPLETE_WITH_GAPS",
        "generation_budget": {"contract": BUDGET_CONTRACT, "lanes_declared": True},
        "phases_executed": ["performance", "quality", "reliability", "context"],
        "context_validation": {"depths_pct": REQUIRED_CONTEXT_DEPTHS_PCT,
                               "placement_preflight_pass": True,
                               "max_placement_error_pp": 0.16,
                               "reserve_tokens": STANDARD_RESERVE_TOKENS},
        "cache_policy": {"scientific_arms": "DISABLED_UNCACHED",
                         "verification": "CACHE_METRIC_FLOOR_PRESENT; cached_tokens telemetry recorded"},
    }
    m.update(overrides)
    return m


def _revision_bundle(td, name, manifest_overrides=None, drop=(), with_web=True):
    g = Path(td) / name
    g.mkdir(parents=True)
    (g / "REPORT.md").write_text("Artifact role: PRIMARY SCIENTIFIC REPORT\nStatus: CURRENT\n")
    (g / "WELP-LAB-RECORD.md").write_text(
        "Artifact role: WELP LAB RECORD\nPrimary scientific report: REPORT.md\n")
    (g / "WELP-CONFORMANCE.md").write_text("ok\n")
    (g / "protocol-findings.md").write_text("PF-01\n")
    (g / "summaries").mkdir(parents=True)
    man = _revision_manifest()
    for k in drop:
        man.pop(k, None)
    if manifest_overrides:
        man.update(manifest_overrides)
    (g / "summaries/campaign_manifest.json").write_text(json.dumps(man))
    (g / "summaries/toolchain_preflight.json").write_text(json.dumps({
        "preflight": "welp-preflight",
        "protocol": {"snapshot_id": REVISION_SNAPSHOT, "welp_status": "DRAFT"},
        "publication": {"localmaxxing_auth_status": "READY"}}))
    (g / "summaries/localmaxxing.json").write_text(json.dumps(
        {"status": "SUBMITTED", "origin": "NEW",
         "submission_ref": "cmtexample0000000000000", "actual_prompt_tokens": 330}))
    if with_web:
        (g / "summaries/website-publication.json").write_text(json.dumps(
            {"schema": "wumbolabs-labs-publication/1", "campaign": "example",
             "disposition": "WEBSITE_READY",
             "canonical_evidence": {"state": "PENDING_HUMAN_GATE"},
             "website_record_slug": "example-model",
             "identity": {"model_id": "example", "profile_id": "example-q",
                          "event_id": "example-e", "event_type": "initial-evaluation"}}))
    return g


def _good_methodology_revision_bundle(td):
    return _revision_bundle(td, "good_methodology_revision")


def _bad_revision_missing_outcomes(td):
    return _revision_bundle(td, "bad_revision_missing_outcomes",
                            drop=("outcome_semantics", "phase_finish_accounting"))


def _bad_revision_finish_accounting(td):
    return _revision_bundle(td, "bad_revision_finish_accounting",
                            manifest_overrides={"phase_finish_accounting": [
                                {"phase": "reliability", "complete_rows": 38,
                                 "complete_missing_finish": 2}]})


def _bad_revision_hash_mismatch(td):
    return _revision_bundle(td, "bad_revision_hash_mismatch",
                            manifest_overrides={"fixtures": {
                                "welp-reliability-sample-20": {
                                    "path": "fixtures/reliability/welp-reliability-sample-20-v2.json",
                                    "sha256": "0" * 64}}})


def _bad_revision_context_depths(td):
    return _revision_bundle(td, "bad_revision_context_depths",
                            manifest_overrides={"context_validation": {
                                "depths_pct": [2.0, 25.0, 50.0, 75.0],
                                "placement_preflight_pass": True,
                                "max_placement_error_pp": 0.16,
                                "reserve_tokens": 640}})


def _bad_revision_cache_policy(td):
    return _revision_bundle(td, "bad_revision_cache_policy",
                            manifest_overrides={"cache_policy": {
                                "scientific_arms": "CACHED_OK"}})


def _good_revision_context_deferred(td):
    """Early-stop campaign that never reached context: R13 warns, stays valid."""
    return _revision_bundle(td, "good_revision_context_deferred",
                            manifest_overrides={"phases_executed": ["quality", "reliability"]},
                            drop=("context_validation",))




def _prospective_bundle(td, name, mutate=None):
    manifest = _revision_manifest()
    manifest["protocol_snapshot"] = {
        "id": "welp-next-snapshot-2026-09-23-real-hardware-real-testing"}
    manifest["fixtures"]["welp-useful-context-family-a"] = {
        "path": "fixtures/useful_context/family-a.json",
        "sha256": _sha256_of("fixtures/useful_context/family-a.json")}
    manifest["context_validation"] = {
        "depths_pct": REQUIRED_CONTEXT_DEPTHS_PCT,
        "placement_preflight_pass": True, "max_placement_error_pp": 0.16,
        "family_a_version": "1.2.0-draft",
        "construction": "final-rendered-token-solver",
        "inference_tokens_match_preflight": True,
        "lane_reserves": {"semantic": 4096, "operational": 1024}}
    manifest["deployment_lanes"] = {
        "contract": DEPLOYMENT_LANES_CONTRACT,
        "prompt_lanes": {
            "MINIMAL": {"profile_id": "profile-a", "sha256": "a" * 64},
            "DEPLOYMENT": {"profile_id": "profile-a", "sha256": "b" * 64}},
        "budgets": {"semantic_ceiling": 4096, "operational_ceiling": 1024,
                    "calibration_predeclared": True}}
    manifest["classification"] = {
        "contract": "welp-final-classification-0.3.0-draft",
        "profile_id": "profile-a",
        "dimension_profile_ids": {key: "profile-a" for key in PROFILE_DIMENSIONS}}
    if mutate:
        mutate(manifest)
    return _revision_bundle(td, name, manifest_overrides=manifest)
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
        rg_rev = check(_good_methodology_revision_bundle(td))
        rb_rev_outcomes = check(_bad_revision_missing_outcomes(td))
        rb_rev_finish = check(_bad_revision_finish_accounting(td))
        rb_rev_hash = check(_bad_revision_hash_mismatch(td))
        rb_rev_depths = check(_bad_revision_context_depths(td))
        rb_rev_cache = check(_bad_revision_cache_policy(td))
        rg_rev_deferred = check(_good_revision_context_deferred(td))
        rg_pro = check(_prospective_bundle(td, "good_prospective"))
        rb_pro_prompt = check(_prospective_bundle(
            td, "bad_prospective_prompt", lambda m: m["deployment_lanes"].pop("prompt_lanes")))
        rb_pro_context = check(_prospective_bundle(
            td, "bad_prospective_context", lambda m: m["context_validation"].update(
                {"construction": "word-fraction"})))
        rb_pro_reserve = check(_prospective_bundle(
            td, "bad_prospective_reserve", lambda m: m["context_validation"][
                "lane_reserves"].update({"semantic": 512})))
        rb_pro_profile = check(_prospective_bundle(
            td, "bad_prospective_profile", lambda m: m["classification"][
                "dimension_profile_ids"].update({"BUDGET_DISCIPLINE": "other-profile"})))
        fails = []
        for label, r in [("legacy_wlep_rejected", rg_legacy), ("current_welp_rejected", rg_welp),
                         ("welp_with_legacy_evidence_rejected", rg_mixed),
                         ("new_hierarchy_rejected", rg_new),
                         ("new_hierarchy_without_lab_record_rejected", rg_new_nolr),
                         ("new_format_localmaxxing_rejected", rg_lmx),
                         ("new_format_website_rejected", rg_web),
                         ("historical_pre_hierarchy_pair_rejected", rg_hist_pair),
                         ("methodology_revision_rejected", rg_rev),
                         ("revision_context_deferred_rejected", rg_rev_deferred)]:
            if not r["valid"]:
                fails.append(label + ": " + str([x for x in r["findings"] if x[0] == "error"]))
        for label, r in [("unknown_prefix_accepted", rb_unknown), ("improperly_rewritten_legacy_accepted", rb_rewritten),
                         ("ambiguous_report_pair_accepted", rb_ambig),
                         ("missing_localmaxxing_accepted", rb_lmx_missing),
                         ("invalid_localmaxxing_status_accepted", rb_lmx_status),
                         ("missing_website_accepted", rb_web_missing),
                         ("invalid_website_disposition_accepted", rb_web_status),
                         ("revision_missing_outcomes_accepted", rb_rev_outcomes),
                         ("revision_finish_accounting_accepted", rb_rev_finish),
                         ("revision_hash_mismatch_accepted", rb_rev_hash),
                         ("revision_context_depths_accepted", rb_rev_depths),
                         ("revision_cache_policy_accepted", rb_rev_cache)]:
            if r["valid"]:
                fails.append(label + ": " + str([x for x in r["findings"] if x[0] == "error"]))
        if not rg_pro["valid"]:
            fails.append("prospective bundle rejected: " + str(
                [x for x in rg_pro["findings"] if x[0] == "error"]))
        for label, record, rule in [
            ("prompt", rb_pro_prompt, "R15_deployment_lanes"),
            ("context", rb_pro_context, "R16_context_lane_preflight"),
            ("reserve", rb_pro_reserve, "R16_context_lane_preflight"),
            ("profile", rb_pro_profile, "R16_classification_profile"),
        ]:
            if record["valid"] or not any(
                    x[0] == "error" and x[1] == rule for x in record["findings"]):
                fails.append(f"prospective {label} failed to reject {rule}")
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
        # Methodology-revision rule assertions
        for rule in ("R09_outcome_semantics", "R09_finish_accounting", "R10_fixtures_hash",
                     "R10_fixtures_hash_verified", "R10_scorers_hash_verified",
                     "R11_campaign_outcome", "R12_generation_budget",
                     "R12_reliability_scorer_v2_selftest", "R13_context_depth_set",
                     "R13_context_placement_preflight", "R13_context_reserve", "R14_cache_policy"):
            if not any(f[1] == rule for f in rg_rev["findings"]):
                fails.append(f"revision bundle missing {rule} finding")
        for label, r, rule in [
            ("missing_outcomes", rb_rev_outcomes, "R09_outcome_semantics_required"),
            ("finish_accounting", rb_rev_finish, "R09_finish_accounting"),
            ("hash_mismatch", rb_rev_hash, "R10_fixtures_hash_mismatch"),
            ("context_depths", rb_rev_depths, "R13_context_depth_set"),
            ("cache_policy", rb_rev_cache, "R14_cache_policy_required"),
        ]:
            if not any(f[0] == "error" and f[1] == rule for f in r["findings"]):
                fails.append(f"revision_{label}_missing_{rule}_error")
        if not any(f[0] == "warning" and f[1] == "R13_context_not_executed" for f in rg_rev_deferred["findings"]):
            fails.append("revision_context_deferred_missing_R13_warning")
        print(json.dumps({
            "fixture_sets": 26,
            "accepted_legacy_wlep": rg_legacy["valid"],
            "accepted_current_welp": rg_welp["valid"],
            "accepted_welp_with_legacy_evidence": rg_mixed["valid"],
            "accepted_new_hierarchy": rg_new["valid"],
            "accepted_new_format_localmaxxing": rg_lmx["valid"],
            "accepted_new_format_website": rg_web["valid"],
            "accepted_historical_pre_hierarchy_pair": rg_hist_pair["valid"],
            "accepted_methodology_revision": rg_rev["valid"],
            "accepted_methodology_revision_context_deferred": rg_rev_deferred["valid"],
            "rejected_new_format_missing_localmaxxing": not rb_lmx_missing["valid"],
            "rejected_invalid_localmaxxing_status": not rb_lmx_status["valid"],
            "rejected_new_format_missing_website": not rb_web_missing["valid"],
            "rejected_invalid_website_disposition": not rb_web_status["valid"],
            "rejected_unknown_prefix": not rb_unknown["valid"],
            "improperly_rewritten_legacy_passed": rb_rewritten["valid"],
            "rejected_ambiguous_report_pair": not rb_ambig["valid"],
            "new_hierarchy_without_lab_record_valid_with_warning": rg_new_nolr["valid"],
            "rejected_revision_missing_outcomes": not rb_rev_outcomes["valid"],
            "rejected_revision_finish_accounting": not rb_rev_finish["valid"],
            "rejected_revision_hash_mismatch": not rb_rev_hash["valid"],
            "rejected_revision_context_depths": not rb_rev_depths["valid"],
            "rejected_revision_cache_policy": not rb_rev_cache["valid"],
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
