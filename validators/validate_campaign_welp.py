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

Hardening era (snapshot dates >= 2026-09-24):
  R17  Evidence-bound hardening. manifest.hardening_evidence is a hash-bound
       pointer {contract: welp-evidence-bundle-0.1.0-draft, path (rooted
       relative to the campaign bundle), sha256}; the validator invokes
       harness/bundle.py evaluate_bundle(root), integrates every bundle
       finding into validity and re-derives gate/context/classification from
       raw evidence, so asserted verdicts never stand alone (no bare asserted
       PASS). Version identity is era-aware: reliability scorer /3 (via the
       bundle), classification welp-final-classification-0.4.0-draft with the
       closed dimension vocabulary, Family A 1.3.0-draft. Classification
       readiness/dimensions use closed enums and any manifest-asserted
       readiness/dimensions must equal the bundle-derived classification. The pre-2026-09-24
       manifest records (R09-R16 generation budget, deployment-lane global
       caps, context_validation/finish-accounting declarations) are not
       required from this era on: per-class setup calibration and execution
       validity are re-derived from the evidence bundle instead. New-era
       manifest fixture/scorer path records are rooted-relative and verified
       against current source bytes; historical absolute generation_evidence
       paths are unchanged. Frozen snapshots before 2026-09-24 (including the
       2026-09-23 snapshots whose Family A fixture and scorer moved on) keep
       validating against their pinned snapshot-freeze hashes.

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
HARDENING_FROM = "2026-09-24"  # evidence-bound hardening era (R17) from this snapshot date on
REASONING_PROFILES_FROM = "2026-09-25"  # reasoning-profile rules (R18-R21) from this snapshot date on
REASONING_TOPOLOGY_CONTRACT = "welp-reasoning-topology-0.1.0-draft"
REASONING_CASES = {"A", "B", "C", "D"}
REASONING_BASE_CASES = {"A", "B", "C"}
REASONING_OFF_STATUSES = {"effective", "unavailable", "ineffective", "unsupported", "not_applicable"}
REASONING_PROFILE_IDS = {"standard", "reasoning-on", "reasoning-off"}
REASONING_DISPLAY_NAMES = {"standard": "Standard", "reasoning-on": "Reasoning On",
                           "reasoning-off": "Reasoning Off"}
EFFORT_QUALIFICATION_STATUSES = {"distinct_deployment_relevant", "not_distinct", "unqualified"}
INCOMPLETE_OFF_STATUSES = {"unavailable", "ineffective", "unsupported"}
# Behavioral evidence kinds that may NEVER be shared across reasoning profiles
# (welp-reasoning-topology-0.1.0-draft, profile-specific evidence list).
BEHAVIORAL_EVIDENCE_KINDS = {
    "effective_reasoning_state", "calibration", "generation_ceiling",
    "operational_budget", "scored_outputs", "reliability", "semantic_completion",
    "safety_task_outcomes", "assistant_quality", "structured_output",
    "tool_recovery", "linux_diagnosis", "repository_repair",
    "multi_turn_correction", "document_synthesis", "controlled_context",
    "multi_document_context", "generation_performance", "latency",
    "token_consumption", "classification",
}
# Genuinely profile-invariant record kinds that MAY be shared when explicitly
# marked (welp-reasoning-topology-0.1.0-draft, profile-invariant list).
PROFILE_INVARIANT_KINDS = {
    "model_source_identity", "license", "artifact_sha256", "quant_identity",
    "architecture", "runtime_commit_build", "physical_hardware",
    "load_fit_qualification", "template_identity", "artifact_provenance",
    "context_rung_geometry",
}
# Effort-level profile ids must extend the base vocabulary mechanically:
# reasoning-<level> where <level> matches this pattern.
EFFORT_PROFILE_ID_RE = re.compile(r"^reasoning-[a-z0-9][a-z0-9-]*$")


def _reasoning_profile_id_ok(pid) -> bool:
    return pid in REASONING_PROFILE_IDS or (
        isinstance(pid, str) and EFFORT_PROFILE_ID_RE.match(pid) is not None
        and pid not in REASONING_PROFILE_IDS)
DEPLOYMENT_LANES_CONTRACT = "welp-deployment-lanes-0.1.0-draft"
EVIDENCE_BUNDLE_CONTRACT = "welp-evidence-bundle-0.1.0-draft"
CLASSIFICATION_040 = "welp-final-classification-0.4.0-draft"
FAMILY_A_13_VERSION = "1.3.0-draft"
PROFILE_DIMENSIONS = {"SEMANTIC_CAPABILITY", "BUDGET_DISCIPLINE",
                      "CONTEXT_USABILITY", "INTEGRATION_QUALITY"}
CAMPAIGN_OUTCOMES = {"COMPLETE_PASS", "COMPLETE_WITH_GAPS", "FAILED_EXECUTION", "BLOCKED"}
REQUIRED_CONTEXT_DEPTHS_PCT = [2.0, 25.0, 50.0, 75.0, 95.0]
STANDARD_RESERVE_TOKENS = 512
RELIABILITY_SCORER_V2 = "welp-reliability-scorer/2"
OUTCOMES_CONTRACT = "welp-outcomes-0.1.0-draft"
BUDGET_CONTRACT = "welp-generation-budget-0.1.0-draft"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _is_rooted_rel(path) -> bool:
    """True for a safe rooted-relative POSIX path (same discipline as the bundle loader)."""
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return False
    parts = path.split("/")
    return all(p not in ("", ".", "..") for p in parts)


def _hardening_modules():
    """Import harness/bundle.py + harness/classification.py (lazy: historical
    validation must not depend on hardening-harness import health)."""
    harness = str(REPO_ROOT / "harness")
    if harness not in sys.path:
        sys.path.insert(0, harness)
    import bundle
    import classification
    return bundle, classification


def _check_hardening(root: Path, m: dict, bad, warn, ok):
    """R17 — hardening-era (snapshot date >= 2026-09-24) evidence-bound checks.

    The manifest binds its hardening evidence with a hash-addressed pointer;
    the validator re-derives the reliability gate, context summary and final
    classification from raw evidence via harness/bundle.py evaluate_bundle and
    integrates every bundle finding into validity. Asserted verdicts (expected
    classification, report prose, claimed PASS strings) never stand alone.
    """
    pointer = m.get("hardening_evidence")
    if not isinstance(pointer, dict):
        bad("R17_hardening_evidence_required",
            "manifest.hardening_evidence {contract: welp-evidence-bundle-0.1.0-draft, "
            "path, sha256} required for hardening-era campaigns")
    else:
        if pointer.get("contract") != EVIDENCE_BUNDLE_CONTRACT:
            bad("R17_hardening_evidence_contract",
                f"hardening_evidence.contract must be {EVIDENCE_BUNDLE_CONTRACT!r}, "
                f"got {pointer.get('contract')!r}")
        he_path = pointer.get("path")
        if not _is_rooted_rel(he_path):
            bad("R17_hardening_evidence_path",
                f"hardening_evidence.path must be a rooted relative path without "
                f"'..' (got {he_path!r})")
        elif not HASH.match(str(pointer.get("sha256", ""))):
            bad("R17_hardening_evidence_hash",
                f"hardening_evidence.sha256 must be 64-hex (got {pointer.get('sha256')!r})")
        else:
            target = root / he_path
            if not target.resolve().is_relative_to(root.resolve()):
                bad("R17_hardening_evidence_path",
                    f"hardening_evidence.path escapes the campaign bundle: {he_path}")
            elif not target.is_file():
                bad("R17_hardening_evidence_reference",
                    f"referenced evidence file missing: {he_path}")
            else:
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual != pointer["sha256"]:
                    bad("R17_hardening_evidence_hash",
                        f"hardening_evidence.sha256 does not match {he_path} bytes")
                else:
                    ok("R17_hardening_evidence", he_path)

    try:
        bundle_mod, classification_mod = _hardening_modules()
    except Exception as exc:
        bad("R17_bundle_harness_unavailable",
            f"harness/bundle.py could not be imported: {type(exc).__name__}: {exc}")
        return
    try:
        bresult = bundle_mod.evaluate_bundle(root)
    except Exception as exc:
        bad("R17_bundle_evaluate_crashed", f"{type(exc).__name__}: {exc}")
        return
    for severity, code, detail in bresult.get("findings") or []:
        if severity == "error":
            bad(f"R17_bundle_{code}", detail)
        elif severity == "warning":
            warn(f"R17_bundle_{code}", detail)
        else:
            ok(f"R17_bundle_{code}", detail)
    if not bresult.get("valid"):
        bad("R17_bundle_invalid",
            "harness/bundle.py evaluate_bundle rejected the hardening evidence "
            "(see R17_bundle_* findings); derived evidence governs asserted verdicts")

    # ---- version identity: Family A 1.3.0 for the hardening era ----
    famver = (bresult.get("context") or {}).get("fixture_version")
    if isinstance(famver, str) and famver:
        if famver != FAMILY_A_13_VERSION:
            bad("R17_context_family_a_version",
                f"hardening-era Family A fixture must be {FAMILY_A_13_VERSION}, got {famver!r}")
        else:
            ok("R17_context_family_a_version", famver)
    ctxv = m.get("context_validation")
    if isinstance(ctxv, dict) and ctxv.get("family_a_version") is not None:
        if ctxv.get("family_a_version") != FAMILY_A_13_VERSION:
            bad("R17_context_family_a_version",
                f"manifest.context_validation.family_a_version must be {FAMILY_A_13_VERSION} "
                f"for hardening-era campaigns, got {ctxv.get('family_a_version')!r}")
        else:
            ok("R17_context_family_a_version_declared", str(ctxv["family_a_version"]))

    # ---- identity fields aligned with the manifest schema required list ----
    missing_identity = []
    if not str(m.get("campaign_id") or "").strip():
        missing_identity.append("campaign_id")
    model = m.get("model")
    if not isinstance(model, dict):
        missing_identity.append("model")
    else:
        missing_identity += [f"model.{key}" for key in ("repo", "revision", "file")
                             if not str(model.get(key) or "").strip()]
        if not HASH.match(str(model.get("sha256", ""))):
            missing_identity.append("model.sha256")
    runtime = m.get("runtime")
    if not isinstance(runtime, dict):
        missing_identity.append("runtime")
    else:
        missing_identity += [f"runtime.{key}" for key in ("name", "build", "commit")
                             if not str(runtime.get(key) or "").strip()]
    if not str(m.get("publication_status") or "").strip():
        missing_identity.append("publication_status")
    serving = m.get("serving_profile")
    if not isinstance(serving, dict):
        missing_identity.append("serving_profile")
    else:
        missing_identity += [f"serving_profile.{key}" for key in ("requested", "effective")
                             if not isinstance(serving.get(key), dict)]
    if missing_identity:
        bad("R17_identity_fields_required",
            "hardening-era manifests record the schema identity fields; missing: "
            + ", ".join(missing_identity))
    else:
        ok("R17_identity_fields", str(m.get("campaign_id")))

    cout = m.get("campaign_outcome")
    if cout in CAMPAIGN_OUTCOMES:
        ok("R17_campaign_outcome", cout)
    else:
        bad("R17_campaign_outcome_required",
            f"campaign_outcome must be one of {sorted(CAMPAIGN_OUTCOMES)}")

    # ---- closed classification enums; asserted verdict must match derivation ----
    cls = m.get("classification")
    derived = bresult.get("classification")
    if isinstance(cls, dict):
        contract = cls.get("contract")
        if contract is not None and contract != CLASSIFICATION_040:
            bad("R17_classification_contract",
                f"hardening-era classification contract must be {CLASSIFICATION_040!r}, "
                f"got {contract!r}")
        readiness = cls.get("readiness")
        dims = cls.get("dimensions")
        if readiness is not None and readiness not in classification_mod.READINESS:
            bad("R17_classification_enum",
                f"readiness {readiness!r} is outside the closed classification vocabulary "
                f"{sorted(classification_mod.READINESS)}")
        if dims is not None:
            if not isinstance(dims, dict) or not dims:
                bad("R17_classification_enum",
                    "classification.dimensions must be a non-empty object when present")
            else:
                unknown = sorted(set(dims) - set(classification_mod.DIMENSIONS))
                if unknown:
                    bad("R17_classification_enum",
                        f"unknown classification dimensions: {unknown}")
                for name, value in sorted(dims.items()):
                    if name in classification_mod.DIMENSIONS and value not in classification_mod.DIMENSIONS[name]:
                        bad("R17_classification_enum",
                            f"{name}: {value!r} is outside the closed vocabulary "
                            f"{sorted(classification_mod.DIMENSIONS[name])}")
        asserted_cls = readiness is not None or (isinstance(dims, dict) and bool(dims))
        if asserted_cls:
            if isinstance(derived, dict):
                if readiness is not None and derived.get("readiness") != readiness:
                    bad("R17_classification_mismatch",
                        f"manifest.classification.readiness {readiness!r} != bundle-derived "
                        f"{derived.get('readiness')!r}; the derived classification governs")
                ddim = derived.get("dimensions")
                if isinstance(dims, dict) and isinstance(ddim, dict) and dims != ddim:
                    bad("R17_classification_mismatch",
                        "manifest.classification.dimensions differ from the bundle-derived "
                        "dimensions; the derived classification governs")
            else:
                bad("R17_classification_unverified",
                    "manifest.classification asserts readiness/dimensions but no "
                    "classification could be derived from hardening_evidence; "
                    "a bare asserted verdict is never accepted")

    # ---- new-era path discipline: fixture/scorer path records are rooted
    # relative and hash-verified against current source (historical absolute
    # generation_evidence paths keep their own M09/M10 rules) ----
    for section in ("fixtures", "scorers"):
        items = m.get(section)
        if items is None:
            continue
        if not isinstance(items, dict):
            bad(f"R17_{section}_record", f"manifest.{section} must be an object when present")
            continue
        for name, meta in sorted(items.items()):
            if not isinstance(meta, dict) or not HASH.match(str(meta.get("sha256", ""))):
                bad(f"R17_{section}_hash", f"{name}: 64-hex sha256 required")
                continue
            path = meta.get("path")
            if path is None:
                continue
            if not _is_rooted_rel(str(path)):
                bad(f"R17_{section}_path",
                    f"{name}: hardening-era path records must be rooted relative, got {path!r}")
                continue
            candidate = REPO_ROOT / str(path)
            if not candidate.is_file():
                bad(f"R17_{section}_path", f"{name}: referenced file missing: {path}")
                continue
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual != meta["sha256"]:
                bad(f"R17_{section}_hash_mismatch",
                    f"{name}: recorded sha256 does not match current {path} bytes")
            else:
                ok(f"R17_{section}_hash_verified", name)


def _check_reasoning_profiles(root: Path, m: dict, web, bad, warn, ok):
    """R18-R21 — reasoning-profile rules (welp-reasoning-topology-0.1.0-draft).

    R18  Reasoning topology + profile identity record: every new-era manifest
         carries a hash-bound reasoning_topology qualification and the event's
         reasoning_profile identity. Topology/profile consistency: case A =>
         standard; case B => reasoning-on with an explicit incomplete-OFF
         record; case C => reasoning-on or reasoning-off with both profiles
         required in the group; case D => base_case + additional_effort_levels
         and no unqualified promoted profile. A Reasoning Off profile under a
         case-B topology (requested OFF measured ineffective) is rejected —
         no fake Reasoning Off profile.
    R19  Profile evidence binding + invariant-only sharing: the setup document
         and the hardening evidence document carry the event's reasoning
         profile identity; explicitly marked profile_invariant_evidence entries
         are validated as hash-bound and genuinely profile-invariant; a
         behavioral-evidence kind in profile_invariant_evidence is rejected
         (cross-profile contamination fails closed); reuse provenance entries
         carry class/source identity/hash.
    R20  No model-level averaging: the website publication export of a
         multi-profile group never carries a flattened model-level verdict
         field; per-profile entries keep independent readiness values.
    R21  Group completeness: a case-C event whose required sibling profile
         event is pending records an incomplete MODEL characterization
         (warning — the event itself may still be a validly completed
         campaign; the group completeness gate applies at publication).
    """
    top = m.get("reasoning_topology")
    prof = m.get("reasoning_profile")

    # ---- R18 topology + profile identity ----
    if not isinstance(top, dict):
        bad("R18_reasoning_topology_required",
            f"manifest.reasoning_topology ({REASONING_TOPOLOGY_CONTRACT} qualification) required "
            "for campaigns under snapshots dated "
            f"{REASONING_PROFILES_FROM} or later")
    else:
        if top.get("contract") != REASONING_TOPOLOGY_CONTRACT:
            bad("R18_topology_contract",
                f"reasoning_topology.contract must be {REASONING_TOPOLOGY_CONTRACT!r}, "
                f"got {top.get('contract')!r}")
        case = top.get("case")
        if case not in REASONING_CASES:
            bad("R18_topology_case", f"reasoning_topology.case must be one of "
                f"{sorted(REASONING_CASES)}, got {case!r}")
            case = None
        off_status = top.get("off_control_status")
        if off_status not in REASONING_OFF_STATUSES:
            bad("R18_off_control_status",
                f"reasoning_topology.off_control_status must be one of "
                f"{sorted(REASONING_OFF_STATUSES)}, got {off_status!r}")
        ev = top.get("evidence")
        if (not isinstance(ev, dict)
                or not _is_rooted_rel(ev.get("path"))
                or not HASH.match(str(ev.get("sha256", "")))):
            bad("R18_topology_evidence_reference",
                "reasoning_topology.evidence must be a rooted {path, sha256} pointer to the "
                "frozen qualification record")
        else:
            target = root / ev["path"]
            if not target.is_file():
                bad("R18_topology_evidence_missing",
                    f"reasoning_topology evidence file missing: {ev['path']}")
            else:
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual != ev["sha256"]:
                    bad("R18_topology_evidence_hash",
                        f"reasoning_topology evidence sha256 does not match {ev['path']} bytes")
                else:
                    ok("R18_topology_evidence", ev["path"])
                    try:
                        record = json.loads(target.read_text())
                    except Exception as exc:
                        record = None
                        bad("R18_topology_evidence_parse", str(exc))
                    if isinstance(record, dict):
                        if record.get("case") != case:
                            bad("R18_topology_case_mismatch",
                                f"qualification record case {record.get('case')!r} differs from "
                                f"manifest case {case!r}")
                        if isinstance(record.get("off_control"), dict) and \
                                record["off_control"].get("status") not in REASONING_OFF_STATUSES:
                            bad("R18_topology_off_control_record",
                                "qualification record off_control.status invalid")
        if case == "D":
            if top.get("base_case") not in REASONING_BASE_CASES:
                bad("R18_topology_base_case",
                    "reasoning_topology.base_case (A|B|C) required when case is D")
            levels = top.get("additional_effort_levels")
            if not isinstance(levels, list) or not levels:
                bad("R18_topology_effort_levels",
                    "reasoning_topology.additional_effort_levels required when case is D")
            else:
                for entry in levels:
                    q = entry.get("qualification") if isinstance(entry, dict) else None
                    status = q.get("status") if isinstance(q, dict) else None
                    if status not in EFFORT_QUALIFICATION_STATUSES:
                        bad("R18_effort_qualification",
                            f"effort level entry lacks a valid qualification status: {entry!r}")
                    elif status == "distinct_deployment_relevant":
                        ok("R18_effort_qualification", str(entry.get("level")))
        if case is not None and off_status in REASONING_OFF_STATUSES:
            # topology/profile consistency
            if case == "A" and off_status != "not_applicable":
                bad("R18_topology_off_consistency",
                    "case A (no reasoning mode) requires off_control_status not_applicable")
            if case == "B" and off_status not in INCOMPLETE_OFF_STATUSES:
                bad("R18_topology_off_consistency",
                    "case B requires off_control_status unavailable|ineffective|unsupported")
            if case in ("C", "D") and off_status == "not_applicable":
                bad("R18_topology_off_consistency",
                    f"case {case} requires a recorded OFF-control status, not not_applicable")
    if not isinstance(prof, dict):
        bad("R18_reasoning_profile_required",
            "manifest.reasoning_profile (this event's Reasoning Profile identity) required "
            f"for campaigns under snapshots dated {REASONING_PROFILES_FROM} or later")
    else:
        pid = prof.get("profile")
        if not _reasoning_profile_id_ok(pid):
            bad("R18_profile_id",
                f"reasoning_profile.profile must be standard|reasoning-on|reasoning-off "
                f"(or a qualified reasoning-<level>), got {pid!r}")
        dname = prof.get("display_name")
        if not isinstance(dname, str) or not dname.strip():
            bad("R18_profile_display_name", "reasoning_profile.display_name required")
        elif pid in REASONING_DISPLAY_NAMES and dname != REASONING_DISPLAY_NAMES[pid]:
            bad("R18_profile_display_name",
                f"display_name for {pid!r} must be {REASONING_DISPLAY_NAMES[pid]!r}")
        if prof.get("publisher_default") not in (True, False):
            bad("R18_profile_publisher_default",
                "reasoning_profile.publisher_default must be a boolean")
        group = prof.get("group")
        if not isinstance(group, dict) or not str(group.get("group_id") or "").strip():
            bad("R18_profile_group",
                "reasoning_profile.group {group_id, required_profiles} required")
        else:
            req = group.get("required_profiles")
            if not isinstance(req, list) or not req or not all(
                    isinstance(x, str) and _reasoning_profile_id_ok(x) for x in req):
                bad("R18_profile_group_required_profiles",
                    "group.required_profiles must list valid profile ids")
            else:
                if isinstance(top, dict) and top.get("case") == "C" and \
                        set(req) != {"reasoning-on", "reasoning-off"}:
                    bad("R18_group_case_c",
                        "a case-C reasoning group requires exactly the two profiles "
                        "reasoning-on and reasoning-off")
                if pid in req:
                    ok("R18_profile_group", f"{group.get('group_id')} / {pid}")
                else:
                    bad("R18_profile_group_membership",
                        f"this event's profile {pid!r} is not in its group.required_profiles")
        # no fake Reasoning Off under an ineffective/unavailable/unsupported OFF control
        if isinstance(top, dict) and pid == "reasoning-off" and \
                top.get("off_control_status") in INCOMPLETE_OFF_STATUSES | {"not_applicable"}:
            bad("R19_fake_reasoning_off",
                f"reasoning-off profile declared but topology OFF control is "
                f"{top.get('off_control_status')!r}: a requested-but-ineffective OFF control "
                "never creates a Reasoning Off profile")
        # topology/profile direction consistency
        if isinstance(top, dict):
            if top.get("case") == "A" and pid != "standard":
                bad("R18_topology_profile_consistency",
                    f"case A requires the standard profile, got {pid!r}")
            if top.get("case") == "B" and pid != "reasoning-on":
                bad("R18_topology_profile_consistency",
                    f"case B requires the reasoning-on profile, got {pid!r}")
            if top.get("case") == "C" and pid not in ("reasoning-on", "reasoning-off"):
                bad("R18_topology_profile_consistency",
                    f"case C requires reasoning-on or reasoning-off, got {pid!r}")
        # an effort-level profile must be prospectively qualified (case D)
        if pid not in REASONING_PROFILE_IDS:
            if not isinstance(top, dict) or top.get("case") != "D":
                bad("R18_effort_profile_unqualified",
                    f"effort-level profile {pid!r} requires topology case D with a "
                    "prospective qualification record")
            else:
                qualified = [
                    e for e in top.get("additional_effort_levels") or []
                    if isinstance(e, dict)
                    and _reasoning_profile_id_ok("reasoning-" + str(e.get("level", "")).lower())
                    and "reasoning-" + str(e.get("level", "")).lower() == pid
                    and isinstance(e.get("qualification"), dict)
                    and e["qualification"].get("status") == "distinct_deployment_relevant"]
                if not qualified:
                    bad("R18_effort_profile_unqualified",
                        f"effort-level profile {pid!r} has no qualified "
                        "distinct_deployment_relevant qualification record; unqualified "
                        "levels never become full profiles")
        # publisher default consistency
        if isinstance(top, dict) and prof.get("publisher_default") is True and \
                isinstance(top.get("publisher_default_profile"), str) and \
                top["publisher_default_profile"] and \
                top["publisher_default_profile"] != pid:
            bad("R18_publisher_default_mismatch",
                f"reasoning_profile.publisher_default true but topology "
                f"publisher_default_profile is {top['publisher_default_profile']!r}")

    # ---- R19 profile evidence binding + invariant-only sharing ----
    bind = None  # (where, doc) pairs to bind-check
    setup_ref = None
    if isinstance(prof, dict) and isinstance(prof.get("profile"), str):
        bind = prof["profile"]
    # setup document binding
    he = m.get("hardening_evidence")
    if isinstance(bind, str) and isinstance(he, dict) and _is_rooted_rel(he.get("path")):
        try:
            evdoc = json.loads((root / he["path"]).read_text())
        except Exception:
            evdoc = None
        if isinstance(evdoc, dict):
            setup_ptr = evdoc.get("setup")
            if isinstance(setup_ptr, dict) and _is_rooted_rel(setup_ptr.get("path")):
                try:
                    setup_doc = json.loads((root / setup_ptr["path"]).read_text())
                except Exception:
                    setup_doc = None
                if isinstance(setup_doc, dict):
                    s_rp = setup_doc.get("reasoning_profile")
                    if not isinstance(s_rp, dict) or s_rp.get("profile") != bind:
                        bad("R19_setup_reasoning_profile",
                            f"setup document must bind this event's reasoning profile "
                            f"{bind!r} (setup.reasoning_profile.profile)")
                    else:
                        ok("R19_setup_reasoning_profile", bind)
                # evidence document identity binding
                e_rp = evdoc.get("reasoning_profile")
                if not isinstance(e_rp, dict) or e_rp.get("profile") != bind:
                    bad("R19_evidence_reasoning_profile",
                        f"hardening evidence document must bind this event's reasoning "
                        f"profile {bind!r} (evidence.reasoning_profile.profile)")
                else:
                    ok("R19_evidence_reasoning_profile", bind)
                # reuse provenance records, when present
                for entry in evdoc.get("evidence_reuse") or []:
                    if not isinstance(entry, dict):
                        bad("R19_reuse_provenance", f"malformed reuse entry: {entry!r}")
                        continue
                    missing = [k for k in ("class", "source_event_id", "source_path",
                                           "source_sha256", "target")
                               if not str(entry.get(k) or "").strip()]
                    if entry.get("class") not in ("REUSE", "REVALIDATE", "RE-DERIVED",
                                                  "MUST_RERUN", "INCOMPARABLE"):
                        bad("R19_reuse_provenance",
                            f"reuse entry class must be REUSE|REVALIDATE|RE-DERIVED|MUST_RERUN|"
                            f"INCOMPARABLE, got {entry.get('class')!r}")
                    elif missing:
                        bad("R19_reuse_provenance",
                            f"reuse entry missing {', '.join(missing)}: {entry.get('target')!r}")
                    elif not HASH.match(str(entry.get("source_sha256"))):
                        bad("R19_reuse_provenance",
                            f"reuse entry source_sha256 must be 64-hex: {entry.get('target')!r}")
                    else:
                        ok("R19_reuse_provenance", str(entry.get("target")))
    # profile-invariant evidence list
    inv = m.get("profile_invariant_evidence")
    if inv is not None:
        if not isinstance(inv, list):
            bad("R19_profile_invariant_list",
                "profile_invariant_evidence must be a list when present")
        else:
            for entry in inv:
                if not isinstance(entry, dict):
                    bad("R19_profile_invariant_entry", f"malformed entry: {entry!r}")
                    continue
                kind = entry.get("kind")
                if entry.get("shared_across_profiles") is not True:
                    bad("R19_profile_invariant_marking",
                        f"{kind!r}: shared_invariant entries must set shared_across_profiles=true")
                if kind in BEHAVIORAL_EVIDENCE_KINDS:
                    bad("R19_cross_profile_contamination",
                        f"{kind!r} is behavioral evidence and can never be shared across "
                        "reasoning profiles")
                elif kind not in PROFILE_INVARIANT_KINDS:
                    bad("R19_profile_invariant_kind",
                        f"{kind!r} is not a declared profile-invariant evidence kind")
                path, sha = entry.get("path"), entry.get("sha256")
                if not _is_rooted_rel(path) or not HASH.match(str(sha or "")):
                    bad("R19_profile_invariant_reference",
                        f"{kind!r}: rooted {{path, sha256}} reference required")
                else:
                    target = root / path
                    if not target.is_file():
                        bad("R19_profile_invariant_reference",
                            f"{kind!r}: referenced file missing: {path}")
                    else:
                        actual = hashlib.sha256(target.read_bytes()).hexdigest()
                        if actual != sha:
                            bad("R19_profile_invariant_hash",
                                f"{kind!r}: sha256 does not match {path} bytes")
                        else:
                            ok("R19_profile_invariant_evidence", str(kind))

    # ---- R20 no model-level averaging ----
    if isinstance(web, dict):
        for key in ("model_level_verdict", "model_level_readiness", "averaged_verdict",
                    "combined_score", "average_score"):
            if key in web:
                bad("R20_model_level_averaging",
                    f"website publication export carries prohibited flattened field "
                    f"{key!r}: reasoning-profile verdicts are never averaged or merged")
        rp_entries = web.get("reasoning_profiles")
        if rp_entries is not None:
            if not isinstance(rp_entries, list) or not rp_entries or not all(
                    isinstance(e, dict) and str(e.get("profile") or "").strip()
                    and str(e.get("display_name") or "").strip()
                    and str(e.get("event_id") or "").strip()
                    for e in rp_entries):
                bad("R20_reasoning_profiles_entries",
                    "reasoning_profiles entries must each carry profile, display_name, "
                    "event_id and this profile's readiness")
            else:
                verdicts = {e.get("profile"): e.get("readiness") for e in rp_entries}
                ok("R20_independent_verdicts",
                   f"{len(verdicts)} per-profile verdicts preserved without averaging"
                   + ("" if len(set(verdicts.values())) > 1
                      else " (identical values remain independently recorded)"))
                if isinstance(prof, dict) and prof.get("profile") not in verdicts \
                        and verdicts:
                    warn("R20_own_profile_absent",
                         f"reasoning_profiles summary does not list this event's profile "
                         f"{prof.get('profile')!r}")

    # ---- R21 group completeness (case C sibling pending) ----
    if isinstance(prof, dict) and isinstance(top, dict) and top.get("case") == "C":
        group = prof.get("group") or {}
        siblings = group.get("sibling_events") or []
        pending = [s for s in siblings if isinstance(s, dict) and s.get("state") == "pending"]
        required = set(group.get("required_profiles") or [])
        covered = {prof.get("profile")} | {
            s.get("profile") for s in siblings if isinstance(s, dict)}
        if required and not required.issubset(covered):
            bad("R21_group_declaration_incomplete",
                f"case-C group must declare every required profile; missing "
                f"{sorted(required - covered)}")
        elif pending:
            warn("R21_model_characterization_incomplete",
                 f"case-C sibling profile event(s) pending: "
                 f"{[s.get('profile') for s in pending]}; the MODEL characterization is "
                 "incomplete under the reasoning-profiles methodology until the linked "
                 "sibling profile event completes (publication gate)")
        else:
            ok("R21_group_complete", "case-C group fully covered by completed events")


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

    # ---- Methodology-revision rules R09-R16 (snapshot date >= 2026-09-19,
    # pre-hardening; hardening-era snapshots run R17 instead) ----
    hardening_era = bool(mdate and mdate.group(1) >= HARDENING_FROM)
    revision_era = bool(mdate and mdate.group(1) >= METHODOLOGY_REVISION_FROM
                        and not hardening_era)
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
                # Only hash-verify references that resolve inside the repo root
                # (absolute or escaping paths are never read).
                if path and _is_rooted_rel(str(path)):
                    candidate = REPO_ROOT / str(path)
                    if candidate.is_file():
                        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
                        if actual != meta["sha256"]:
                            # Frozen-hash compatibility covers every snapshot before
                            # the 2026-09-24 hardening era, including the 2026-09-23
                            # snapshots (whose Family A fixture and reliability scorer
                            # moved on afterwards). Retained evidence is verified
                            # against the snapshot's pinned immutable frozen hash —
                            # never against an arbitrary recorded value.
                            if mdate and mdate.group(1) < HARDENING_FROM:
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
            correction_era = (sid != "welp-next-snapshot-2026-09-23-real-hardware-real-testing")
            classification_contract = ("welp-final-classification-0.3.1-draft"
                                       if correction_era else "welp-final-classification-0.3.0-draft")
            deployment = prompt.get("DEPLOYMENT") if isinstance(prompt, dict) else None
            deployment_profile = deployment.get("profile_id") if isinstance(deployment, dict) else None
            if m.get("campaign_outcome") not in {"BLOCKED", "FAILED_EXECUTION"}:
                if (isinstance(classification, dict)
                        and classification.get("contract") == classification_contract
                        and classification.get("profile_id")
                        and (not correction_era or classification["profile_id"] == deployment_profile)
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

    # ---- Hardening era R17 (snapshot date >= 2026-09-24): evidence-bound ----
    if hardening_era:
        _check_hardening(root, m, bad, warn, ok)

    # ---- Reasoning-profile rules R18-R21 (snapshot date >= 2026-09-25) ----
    if mdate and mdate.group(1) >= REASONING_PROFILES_FROM:
        _check_reasoning_profiles(root, m, web, bad, warn, ok)

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


def _corrected_bundle(td, name, mutate=None):
    def correction(m):
        m["protocol_snapshot"]["id"] = "welp-next-snapshot-2026-09-23-profile-identity-clarification"
        m["classification"]["contract"] = "welp-final-classification-0.3.1-draft"
        if mutate:
            mutate(m)
    return _prospective_bundle(td, name, correction)


def _retained_realwork_bundle(td, name):
    """Retained 2026-09-23 bundle pinned to its frozen snapshot hashes.

    Regression fixture for pre-hardening frozen-hash compatibility: the working
    tree moved on after the freeze (Family A bumped to 1.3.0-draft, reliability
    scorer updated), so a retained bundle records the hashes from its immutable
    snapshot-freeze manifest — not an arbitrary value, and not today's bytes.
    The bundle must stay valid with R10 historical-hash warnings.
    """
    frozen_sid = "welp-next-snapshot-2026-09-23-real-hardware-real-testing"
    frozen = json.loads((REPO_ROOT / "snapshot-freeze" / frozen_sid
                         / "manifest.json").read_text())
    groups = frozen.get("frozen_artifact_sha256", {})

    def pin_frozen(m):
        for section in ("fixtures", "scorers"):
            recorded = groups.get(section, {})
            for meta in (m.get(section) or {}).values():
                rec = recorded.get(str(meta.get("path")))
                if rec:
                    meta["sha256"] = rec

    return _prospective_bundle(td, name, pin_frozen)


# ---------------- hardening-era fixtures (R17, snapshot >= 2026-09-24) ----------------

def _synthetic_hardening_bundle(td, variant):
    """Build a BundleRecovery synthetic hardening bundle; returns its campaign root.

    Exercises the FULL validator (check), not just harness/bundle.py: the
    synthetic builder emits the whole campaign shell plus the hash-bound
    hardening_evidence document, so positive/complete-negative must pass every
    rule and the negative variants must be rejected through the integrated
    bundle findings.
    """
    bundle_mod, _classification_mod = _hardening_modules()
    dest = Path(td) / ("synthetic_" + variant.replace("-", "_"))
    dest.mkdir(parents=True, exist_ok=True)
    return Path(bundle_mod.make_synthetic_bundle(dest, variant=variant))


def _mutated_synthetic_bundle(td, variant, mutate):
    """Synthetic bundle whose campaign manifest is additionally mutated."""
    g = _synthetic_hardening_bundle(td, variant)
    man_path = g / "summaries/campaign_manifest.json"
    man = json.loads(man_path.read_text())
    mutate(man)
    man_path.write_text(json.dumps(man))
    return g


def _reasoning_mutated_bundle(td, base_variant, name, manifest_mut=None,
                              docs_mut=None, web_mut=None, sibling_pending=False):
    """Reasoning-profile synthetic sibling with controlled post-build edits.

    Builds the base sibling, then applies optional mutations to the manifest,
    the frozen documents (topology record / setup / evidence — re-binding every
    affected hash in dependency order), or the website export. Selftest-only:
    real campaigns freeze these documents once and never edit them.
    """
    g = _synthetic_hardening_bundle(td, base_variant)
    man_path = g / "summaries/campaign_manifest.json"
    man = json.loads(man_path.read_text())
    ev_path = g / man["hardening_evidence"]["path"]
    ev = json.loads(ev_path.read_text())
    setup_path = g / ev["setup"]["path"]
    setup_doc = json.loads(setup_path.read_text())
    top_ref = (man.get("reasoning_topology") or {}).get("evidence")
    top_path = g / top_ref["path"] if top_ref else None
    top = json.loads(top_path.read_text()) if top_path and top_path.is_file() else None
    if docs_mut is not None:
        docs_mut(man, setup_doc, ev, top)
        if top_path is not None and top is not None:
            top_path.write_text(json.dumps(top, indent=2, sort_keys=True))
            top_ref["sha256"] = hashlib.sha256(top_path.read_bytes()).hexdigest()
        setup_path.write_text(json.dumps(setup_doc, indent=2, sort_keys=True))
        ev["setup"]["sha256"] = hashlib.sha256(setup_path.read_bytes()).hexdigest()
        ev_path.write_text(json.dumps(ev, indent=2, sort_keys=True))
        man["hardening_evidence"]["sha256"] = \
            hashlib.sha256(ev_path.read_bytes()).hexdigest()
    if web_mut is not None:
        web_path = g / "summaries/website-publication.json"
        web = json.loads(web_path.read_text())
        web_mut(web)
        web_path.write_text(json.dumps(web, indent=2, sort_keys=True))
    if manifest_mut is not None:
        manifest_mut(man)
    if sibling_pending:
        for s in man["reasoning_profile"]["group"]["sibling_events"]:
            s["state"] = "pending"
    man_path.write_text(json.dumps(man, indent=2, sort_keys=True))
    return g


def _set_standard_topology(man, setup_doc, ev, top):
    """Rewrite the sibling into a complete case-A Standard-profile event."""
    top.update({"case": "A",
                "off_control_status": "not_applicable",
                "off_control": {"status": "not_applicable", "control": None,
                                "evidence": None},
                "publisher_default_profile": "standard"})
    man["reasoning_topology"] = {
        **man["reasoning_topology"],
        "case": "A", "off_control_status": "not_applicable",
        "publisher_default_profile": "standard",
    }
    man["reasoning_profile"] = {
        "profile": "standard", "display_name": "Standard",
        "publisher_default": True,
        "group": {"group_id": man["reasoning_profile"]["group"]["group_id"],
                  "required_profiles": ["standard"], "sibling_events": []}}
    setup_doc["reasoning_profile"] = {"profile": "standard",
                                      "display_name": "Standard",
                                      "group_id": man["reasoning_profile"]["group"]["group_id"]}
    ev["reasoning_profile"] = {"profile": "standard", "display_name": "Standard"}


def _bad_pointer_absolute(td):
    """hardening_evidence.path outside the campaign bundle: R17 path error."""
    return _mutated_synthetic_bundle(
        td, "positive",
        lambda m: m["hardening_evidence"].update({"path": "/etc/hardening-evidence.json"}))


def _bad_pointer_hash(td):
    """hardening_evidence.sha256 not matching the evidence bytes: R17 hash error."""
    return _mutated_synthetic_bundle(
        td, "positive",
        lambda m: m["hardening_evidence"].update({"sha256": "0" * 64}))


def _bad_asserted_classification(td):
    """Bare asserted PASS on a negative-completed bundle: derived classification governs."""
    def assert_ready(m):
        m["classification"] = {
            "contract": CLASSIFICATION_040, "readiness": "READY",
            "dimensions": {"SEMANTIC_CAPABILITY": "STRONG", "BUDGET_DISCIPLINE": "GOOD",
                           "CONTEXT_USABILITY": "VALIDATED", "INTEGRATION_QUALITY": "CLEAN"}}
    return _mutated_synthetic_bundle(td, "complete-negative", assert_ready)


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
        rg_corrected = check(_corrected_bundle(td, "good_corrected"))
        rb_corrected_profile = check(_corrected_bundle(
            td, "bad_corrected_profile", lambda m: m["classification"].update({
                "profile_id": "other-profile",
                "dimension_profile_ids": {key: "other-profile" for key in PROFILE_DIMENSIONS}})))
        rg_retained = check(_retained_realwork_bundle(td, "good_retained_realwork"))

        # ---- R17 hardening era: full-validator runs over synthetic bundles ----
        rg_pos = rg_neg = rb_review = rb_incomplete = rb_exec = None
        rb_pointer_abs = rb_pointer_hash = rb_asserted = None
        synth_errors = []
        try:
            rg_pos = check(_synthetic_hardening_bundle(td, "positive"))
            rg_neg = check(_synthetic_hardening_bundle(td, "complete-negative"))
            rb_review = check(_synthetic_hardening_bundle(td, "review-blocked"))
            rb_incomplete = check(_synthetic_hardening_bundle(td, "incomplete"))
            rb_exec = check(_synthetic_hardening_bundle(td, "execution-error"))
            rb_pointer_abs = check(_bad_pointer_absolute(td))
            rb_pointer_hash = check(_bad_pointer_hash(td))
            rb_asserted = check(_bad_asserted_classification(td))
        except Exception as exc:
            synth_errors.append("hardening synthetic bundles unavailable: "
                                f"{type(exc).__name__}: {exc}")
        fails = []
        fails.extend(synth_errors)

        # Historical + prospective positive cases must be accepted.
        for label, r in [("legacy_wlep_rejected", rg_legacy), ("current_welp_rejected", rg_welp),
                         ("welp_with_legacy_evidence_rejected", rg_mixed),
                         ("new_hierarchy_rejected", rg_new),
                         ("new_hierarchy_without_lab_record_rejected", rg_new_nolr),
                         ("new_format_localmaxxing_rejected", rg_lmx),
                         ("new_format_website_rejected", rg_web),
                         ("historical_pre_hierarchy_pair_rejected", rg_hist_pair),
                         ("methodology_revision_rejected", rg_rev),
                         ("revision_context_deferred_rejected", rg_rev_deferred),
                         ("retained_realwork_rejected", rg_retained),
                         ("hardening_positive_rejected", rg_pos),
                         ("hardening_complete_negative_rejected", rg_neg)]:
            if r is not None and not r["valid"]:
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
                         ("revision_cache_policy_accepted", rb_rev_cache),
                         ("hardening_review_blocked_accepted", rb_review),
                         ("hardening_incomplete_accepted", rb_incomplete),
                         ("hardening_execution_error_accepted", rb_exec),
                         ("hardening_pointer_absolute_accepted", rb_pointer_abs),
                         ("hardening_pointer_hash_accepted", rb_pointer_hash),
                         ("hardening_bare_asserted_classification_accepted", rb_asserted)]:
            if r is not None and r["valid"]:
                fails.append(label + ": " + str([x for x in r["findings"] if x[0] == "error"]))
        if not rg_pro["valid"]:
            fails.append("prospective bundle rejected: " + str(
                [x for x in rg_pro["findings"] if x[0] == "error"]))
        if not rg_corrected["valid"]:
            fails.append("corrected bundle rejected: " + str(
                [x for x in rg_corrected["findings"] if x[0] == "error"]))
        for label, record, rule in [
            ("prompt", rb_pro_prompt, "R15_deployment_lanes"),
            ("context", rb_pro_context, "R16_context_lane_preflight"),
            ("reserve", rb_pro_reserve, "R16_context_lane_preflight"),
            ("profile", rb_pro_profile, "R16_classification_profile"),
            ("deployment profile", rb_corrected_profile, "R16_classification_profile"),
        ]:
            if record["valid"] or not any(
                    x[0] == "error" and x[1] == rule for x in record["findings"]):
                fails.append(f"prospective {label} failed to reject {rule}")
        # ---- R17 hardening-era assertions ----
        if rg_retained is not None and not any(
                f[0] == "warning" and f[1] in ("R10_fixtures_historical_hash",
                                               "R10_scorers_historical_hash")
                for f in rg_retained["findings"]):
            fails.append("retained_realwork_missing_frozen_hash_warning")
        if rg_pos is not None:
            if not any(f[0] == "info" and f[1] == "R17_context_family_a_version"
                       for f in rg_pos["findings"]):
                fails.append("hardening_positive_missing_family_a_version_check")
            if not any(f[0] == "info" and f[1] == "R17_hardening_evidence"
                       for f in rg_pos["findings"]):
                fails.append("hardening_positive_missing_pointer_check")
            if not any(f[1] == "R17_identity_fields" for f in rg_pos["findings"]):
                fails.append("hardening_positive_missing_identity_fields_check")
        for label, record in [("review_blocked", rb_review), ("incomplete", rb_incomplete),
                              ("execution_error", rb_exec)]:
            if record is not None and not any(
                    f[0] == "error" and f[1].startswith("R17_bundle_")
                    for f in record["findings"]):
                fails.append(f"hardening_{label}_missing_integrated_bundle_error")
        if rb_pointer_abs is not None and not any(
                f[0] == "error" and f[1] == "R17_hardening_evidence_path"
                for f in rb_pointer_abs["findings"]):
            fails.append("pointer_absolute_missing_R17_path_error")
        if rb_pointer_hash is not None and not any(
                f[0] == "error" and f[1] == "R17_hardening_evidence_hash"
                for f in rb_pointer_hash["findings"]):
            fails.append("pointer_hash_missing_R17_hash_error")
        if rb_asserted is not None and not any(
                f[0] == "error" and f[1] == "R17_classification_mismatch"
                for f in rb_asserted["findings"]):
            fails.append("bare_asserted_classification_missing_R17_mismatch_error")

        # ---- R18-R21 reasoning-profile era: sibling pairs + mutations ----
        rg_ron = rg_roff = rg_roffneg = rg_standard = rg_case_b = None
        rg_invariant = rg_pending = rg_effort_ok = rg_web_profiles = None
        rb_fake_off = rb_contam = rb_missing_top = rb_effort_bad = None
        rb_averaging = None
        try:
            rg_ron = check(_synthetic_hardening_bundle(td, "reasoning-on-positive"))
            rg_roff = check(_synthetic_hardening_bundle(td, "reasoning-off-positive"))
            rg_roffneg = check(_synthetic_hardening_bundle(td, "reasoning-off-negative"))
            rg_standard = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "case_a_standard",
                docs_mut=_set_standard_topology))
            rg_case_b = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "case_b_no_off",
                docs_mut=lambda m, s, e, t: (
                    t.update({"case": "B", "off_control_status": "ineffective",
                              "off_control": {"status": "ineffective",
                                              "control": "enable_thinking=false",
                                              "evidence": None}}),
                    m["reasoning_topology"].update(
                        {"case": "B", "off_control_status": "ineffective"}),
                    m["reasoning_profile"].update({"publisher_default": True}),
                    m["reasoning_profile"]["group"].update(
                        {"required_profiles": ["reasoning-on"], "sibling_events": []}),
                    s["reasoning_profile"].update({"profile": "reasoning-on"}),
                    e["reasoning_profile"].update({"profile": "reasoning-on"}))))
            rg_invariant = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "invariant_shared",
                manifest_mut=lambda m: m["profile_invariant_evidence"].append({
                    "kind": "license", "shared_across_profiles": True,
                    "note": "MIT license text shared across sibling profiles",
                    "path": "evidence/profile-invariant/artifact-identity.json",
                    "sha256": hashlib.sha256(
                        (_synthetic_hardening_bundle(
                            td, "reasoning-on-positive")
                         / "evidence/profile-invariant/artifact-identity.json")
                        .read_bytes()).hexdigest()})))
            rg_pending = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "sibling_pending",
                sibling_pending=True))
            rg_effort_ok = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "effort_unqualified_level",
                manifest_mut=lambda m: m["reasoning_topology"].update({
                    "case": "D", "base_case": "C",
                    "additional_effort_levels": [
                        {"level": "high", "control": "reasoning_effort",
                         "qualification": {"status": "unqualified",
                                           "evidence": None,
                                           "measured_differences": {}}}]})))
            rg_web_profiles = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "web_profiles",
                web_mut=lambda w: w.update({"reasoning_profiles": [
                    {"profile": "reasoning-on", "display_name": "Reasoning On",
                     "publisher_default": True,
                     "event_id": "welp-synthetic-reasoning-on-2026-09-25",
                     "readiness": "READY"},
                    {"profile": "reasoning-off", "display_name": "Reasoning Off",
                     "publisher_default": False,
                     "event_id": "welp-synthetic-reasoning-off-2026-09-25",
                     "readiness": "NOT_READY"}]})))
            rb_fake_off = check(_reasoning_mutated_bundle(
                td, "reasoning-off-positive", "fake_reasoning_off",
                manifest_mut=lambda m: m["reasoning_topology"].update({
                    "case": "B", "off_control_status": "ineffective"})))
            rb_contam = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "cross_profile_contamination",
                manifest_mut=lambda m: m["profile_invariant_evidence"].append({
                    "kind": "reliability", "shared_across_profiles": True,
                    "note": "illegitimate behavioral sharing",
                    "path": "evidence/profile-invariant/artifact-identity.json",
                    "sha256": "0" * 64})))
            rb_missing_top = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "missing_topology",
                manifest_mut=lambda m: m.pop("reasoning_topology")))
            rb_effort_bad = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "effort_unpromoted",
                manifest_mut=lambda m: (
                    m["reasoning_topology"].update({
                        "case": "D", "base_case": "C",
                        "additional_effort_levels": [
                            {"level": "high", "control": "reasoning_effort",
                             "qualification": {"status": "not_distinct",
                                               "evidence": None,
                                               "measured_differences": {}}}]}),
                    m["reasoning_profile"].update({"profile": "reasoning-high"}),
                    m["reasoning_profile"].update({"display_name": "Reasoning High"}),
                    m["reasoning_profile"]["group"].update(
                        {"required_profiles": ["reasoning-on", "reasoning-off",
                                               "reasoning-high"]}))))
            rb_averaging = check(_reasoning_mutated_bundle(
                td, "reasoning-on-positive", "averaged_verdict",
                web_mut=lambda w: w.update({"model_level_verdict": "READY_WITH_GUARDRAILS"})))
        except Exception as exc:
            fails.append(f"reasoning-profile synthetic bundles unavailable: "
                         f"{type(exc).__name__}: {exc}")

        # A/C: topology-consistent events accepted (Standard, Reasoning On, Reasoning Off)
        for label, r in [("reasoning_on_rejected", rg_ron),
                         ("reasoning_off_rejected", rg_roff),
                         ("reasoning_off_negative_rejected", rg_roffneg),
                         ("case_a_standard_rejected", rg_standard),
                         ("case_b_reasoning_on_rejected", rg_case_b),
                         ("invariant_shared_rejected", rg_invariant),
                         ("web_two_profiles_rejected", rg_web_profiles)]:
            if r is not None and not r["valid"]:
                fails.append(label + ": " + str(
                    [x for x in r["findings"] if x[0] == "error"]))
        # D: requested-OFF-but-effective-ON never yields a fake Reasoning Off
        if rb_fake_off is not None and not any(
                f[0] == "error" and f[1] == "R19_fake_reasoning_off"
                for f in rb_fake_off["findings"]):
            fails.append("fake_reasoning_off_not_rejected")
        # F: behavioral evidence in the invariant list is contamination
        if rb_contam is not None and not any(
                f[0] == "error" and f[1] == "R19_cross_profile_contamination"
                for f in rb_contam["findings"]):
            fails.append("cross_profile_contamination_not_rejected")
        # J: a new-era manifest without the topology record is rejected
        if rb_missing_top is not None and not any(
                f[0] == "error" and f[1] == "R18_reasoning_topology_required"
                for f in rb_missing_top["findings"]):
            fails.append("missing_topology_not_rejected")
        # I: unqualified effort levels never become full profiles; qualification first
        if rg_effort_ok is not None and any(
                f[0] == "error" and f[1].startswith("R18_effort")
                for f in rg_effort_ok["findings"]):
            fails.append("unqualified_but_unpromoted_effort_level_rejected")
        if rb_effort_bad is not None and not any(
                f[0] == "error" and f[1] == "R18_effort_profile_unqualified"
                for f in rb_effort_bad["findings"]):
            fails.append("unqualified_promoted_effort_profile_not_rejected")
        # H: differing sibling verdicts are preserved (no averaging)
        ron_ready = (rg_ron is not None and
                     (rg_ron.get("classification") or {}).get("readiness"))
        if rg_ron is not None:
            man_ron = json.loads((
                Path(td) / "synthetic_reasoning_on_positive"
                / "summaries/campaign_manifest.json").read_text())
            man_roffneg = json.loads((
                Path(td) / "synthetic_reasoning_off_negative"
                / "summaries/campaign_manifest.json").read_text())
            verdicts = (man_ron["classification"].get("readiness"),
                        man_roffneg["classification"].get("readiness"))
            if verdicts[0] == verdicts[1]:
                fails.append(f"differing_verdicts_expected_got_{verdicts}")
        # E: independent calibration — sibling setups are distinct documents
        if rg_ron is not None and rg_roff is not None:
            on_man = json.loads((Path(td) / "synthetic_reasoning_on_positive"
                                 / "summaries/campaign_manifest.json").read_text())
            off_man = json.loads((Path(td) / "synthetic_reasoning_off_positive"
                                  / "summaries/campaign_manifest.json").read_text())
            on_b = on_man["deployment_lanes"]["budgets"]
            off_b = off_man["deployment_lanes"]["budgets"]
            if on_b == off_b:
                fails.append("sibling_calibration_not_independent")
            if on_man["reasoning_profile"]["group"]["group_id"] != \
                    off_man["reasoning_profile"]["group"]["group_id"]:
                fails.append("sibling_group_ids_differ")
        # J: pending sibling keeps the event valid but records model
        # characterization incompleteness (warning, never silent)
        if rg_pending is None or not rg_pending["valid"]:
            fails.append("pending_sibling_event_invalidated")
        elif not any(f[0] == "warning" and f[1] == "R21_model_characterization_incomplete"
                     for f in rg_pending["findings"]):
            fails.append("pending_sibling_missing_R21_warning")
        # H/K: averaging is rejected; per-profile entries accepted
        if rb_averaging is not None and not any(
                f[0] == "error" and f[1] == "R20_model_level_averaging"
                for f in rb_averaging["findings"]):
            fails.append("model_level_averaging_not_rejected")
        if rg_web_profiles is not None and any(
                f[0] == "error" and f[1].startswith("R20")
                for f in rg_web_profiles["findings"]):
            fails.append("two_profile_website_export_rejected")
        # L: historical one-profile events carry no R18 findings
        if rg_pos is not None and any(
                f[1].startswith(("R18_", "R19_", "R20_", "R21_"))
                for f in rg_pos["findings"]):
            fails.append("historical_bundle_hit_reasoning_profile_rules")
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
            "fixture_sets": 38,
            "accepted_legacy_wlep": rg_legacy["valid"],
            "accepted_current_welp": rg_welp["valid"],
            "accepted_welp_with_legacy_evidence": rg_mixed["valid"],
            "accepted_new_hierarchy": rg_new["valid"],
            "accepted_new_format_localmaxxing": rg_lmx["valid"],
            "accepted_new_format_website": rg_web["valid"],
            "accepted_historical_pre_hierarchy_pair": rg_hist_pair["valid"],
            "accepted_methodology_revision": rg_rev["valid"],
            "accepted_methodology_revision_context_deferred": rg_rev_deferred["valid"],
            "accepted_retained_realwork_2026_09_23": rg_retained["valid"],
            "accepted_hardening_positive": bool(rg_pos and rg_pos["valid"]),
            "accepted_hardening_complete_negative": bool(rg_neg and rg_neg["valid"]),
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
            "rejected_hardening_review_blocked": bool(rb_review and not rb_review["valid"]),
            "rejected_hardening_incomplete": bool(rb_incomplete and not rb_incomplete["valid"]),
            "rejected_hardening_execution_error": bool(rb_exec and not rb_exec["valid"]),
            "rejected_hardening_pointer_absolute": bool(rb_pointer_abs and not rb_pointer_abs["valid"]),
            "rejected_hardening_pointer_hash": bool(rb_pointer_hash and not rb_pointer_hash["valid"]),
            "rejected_hardening_bare_asserted_classification": bool(rb_asserted and not rb_asserted["valid"]),
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
