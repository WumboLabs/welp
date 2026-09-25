#!/usr/bin/env python3
"""bundle.py — prospective hardening evidence bundle loader/deriver (welp-phase-harness/1).

Loads the manifest.hardening_evidence document (welp-evidence-bundle-0.1.0-draft),
verifies every rooted-relative path and recorded SHA-256 against actual bytes,
re-derives the reliability gate (scorer v3), the useful-context summary and the
final classification from RAW evidence, and renders a deterministic compact
Markdown report.

Core discipline (this module never trusts asserted verdicts):
  - Reliability rows are rescored with harness/reliability.evaluate on the raw
    paired lanes; rows must carry the ACTUAL outgoing messages bound to the
    frozen fixture prompt and the frozen setup lane rendering, and the actual
    completion control (max_tokens) matching the class/lane setup.
  - Context cells are rechecked from the retained raw answer via
    context.score_family_a + context.rung_outcome; asserted dispositions alone
    never establish an oracle outcome. Answerless measured rows are
    representable only as BUDGET_LIMITED with the raw record proving the
    terminal generation state (welp-context 0.3.0, Granite D-01); anything
    else fails closed.
  - Capability modules are rescored with the canonical scorers; a mechanical
    PASS on free-prose role detail is provisional and never completes a module:
    a hash-bound, independent, model-identity-blinded qualitative adjudication
    of the full answer under the frozen rubric is required, and review is
    separate from the lane safety reviews.
  - The expected classification is validated against the DERIVED classification
    instead of the caller's dimensions; report prose and claimed PASS strings
    are never scientific proof.
  - COMPLETE_PASS is rejected when coverage is missing/invalid, required
    adaptive sampling is not complete, review is unresolved or the setup is
    invalid. A fully executed negative campaign (e.g. COMPLETE_PASS/NOT_READY)
    remains a valid completed campaign, distinct from incomplete/blocked
    metadata.

CLI:
  python3 harness/bundle.py check <campaign_dir>
  python3 harness/bundle.py render <campaign_dir>
  python3 harness/bundle.py synthetic <campaign_dir> [variant]
  python3 harness/bundle.py selftest
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scorers"))

import reliability as R                    # noqa: E402
import classification as C                 # noqa: E402
import context as CX                       # noqa: E402
import capabilities as CAP                 # noqa: E402
import setup as SETUP                      # noqa: E402
import welp_outcomes as OW                 # noqa: E402
from safety_review import digest as _digest  # noqa: E402

MODULE_ID = "welp-harness-bundle/1.0.0-draft"
CONTRACT = "welp-evidence-bundle-0.1.0-draft"
REPO_ROOT = HERE.parent
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

FAMILY_A_1_3 = "1.3.0-draft"
CLASSIFICATION_040 = "welp-final-classification-0.4.0-draft"
RELIABILITY_SCORER_V3 = "welp-reliability-scorer/3"
FIXTURE_RELIABILITY_V3 = "fixtures/reliability/welp-reliability-sample-20-v3.json"
FIXTURE_FAMILY_A = "fixtures/useful_context/family-a.json"
FIXTURE_LINUX = "fixtures/real_work/linux-diagnosis.json"
FIXTURE_TOOL_RECOVERY = "fixtures/real_work/tool-recovery.json"
FIXTURE_MULTI_TURN = "fixtures/real_work/multi-turn-correction.json"
FIXTURE_MULTIDOCUMENT = "fixtures/useful_context/multidocument.json"
FIXTURE_DOC_SYNTHESIS = "fixtures/real_work/document-synthesis.json"
FIXTURE_REPO_CODING = "fixtures/real_work/repository-timeout.json"

TRUSTED_CONTEXT_DISPOSITIONS = {"VALIDATED", "FAILED", "BUDGET_LIMITED",
                                "FIT_LIMIT", "INTEGRATION_BLOCKED"}
CONTEXT_DISPOSITIONS = {"VALIDATED", "FAILED", "BUDGET_LIMITED", "PARTIAL",
                        "NOT_TESTED", "FIT_LIMIT", "INTEGRATION_BLOCKED"}

# Role applicability (welp-real-work): modules each declared role must cover.
ROLE_REQUIRED_MODULES = {
    "ordinary_assistant": ("document_synthesis",),
    "structured_output": ("multidocument",),
    "coding": ("coding",),
    "linux_systems": ("linux_diagnosis",),
    "native_tools": ("tool_recovery",),
    "multi_turn": ("multi_turn",),
    "long_context": ("family_a", "multidocument"),
}
# Modules whose run answers carry free prose judged only by rubric review.
QUALITATIVE_MODULES = {"coding", "document_synthesis", "linux_diagnosis"}
REVIEWERS_REQUIRED = 2
REVIEWERS_MAXIMUM = 3
TIE_BREAK_ROLE = "tie_break"
RUBRIC_AMBIGUITY = "RUBRIC_AMBIGUITY"


# --------------------------------------------------------------------------
# findings + strict frozen reads
# --------------------------------------------------------------------------
class Findings:
    """Deterministic, sortable finding list: (severity, code, detail)."""

    def __init__(self):
        self.items = []

    def error(self, code, detail=""):
        self.items.append(("error", code, str(detail)))

    def warn(self, code, detail=""):
        self.items.append(("warning", code, str(detail)))

    def info(self, code, detail=""):
        self.items.append(("info", code, str(detail)))

    def extend_raw(self, items):
        for item in items:
            self.items.append(tuple(item))

    @property
    def errors(self):
        return [f for f in self.items if f[0] == "error"]

    def has(self, code):
        return any(f[1] == code for f in self.items)

    def sorted(self):
        return sorted(self.items)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_rooted_rel(path) -> bool:
    """True for a safe rooted-relative POSIX path (no escape from the root)."""
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return False
    parts = path.split("/")
    return all(p not in ("", ".", "..") for p in parts)


def _read_frozen_bytes(root: Path, ref, findings, code, label):
    """Strict {path, sha256} reference read; returns bytes or None."""
    if not isinstance(ref, dict):
        findings.error(code, f"{label}: reference must be an object with path+sha256")
        return None
    path, sha = ref.get("path"), ref.get("sha256")
    if not _is_rooted_rel(path):
        findings.error(code, f"{label}: path must be a rooted relative path without '..' "
                             f"(got {path!r})")
        return None
    if not isinstance(sha, str) or not HASH_RE.match(sha):
        findings.error(code, f"{label}: 64-hex sha256 required (got {sha!r})")
        return None
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        findings.error(code, f"{label}: reference escapes the evidence root")
        return None
    if not target.is_file():
        findings.error(code, f"{label}: referenced file missing: {path}")
        return None
    data = target.read_bytes()
    actual = _sha256_bytes(data)
    if actual != sha:
        findings.error(code, f"{label}: recorded sha256 does not match {path} bytes "
                             f"(recorded {sha[:12]}..., actual {actual[:12]}...)")
        return None
    return data


def _read_frozen_json(root: Path, ref, findings, code, label):
    data = _read_frozen_bytes(root, ref, findings, code, label)
    if data is None:
        return None
    try:
        return json.loads(data)
    except ValueError as exc:
        findings.error(code, f"{label}: referenced JSON unparsable ({exc})")
        return None


def _read_frozen_rows(root: Path, ref, findings, code, label):
    """Load a JSONL rows pointer into a list of row objects."""
    data = _read_frozen_bytes(root, ref, findings, code, label)
    if data is None:
        return None
    rows = []
    for lineno, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            findings.error(code, f"{label}: line {lineno} unparsable ({exc})")
            return None
    if not rows:
        findings.error(code, f"{label}: rows file contains no rows")
        return None
    if not all(isinstance(r, dict) for r in rows):
        findings.error(code, f"{label}: every row must be a JSON object")
        return None
    return rows


def _rows_entry(root: Path, entry, findings, code, label):
    """Rows may be inline lists or a strict {path, sha256} JSONL pointer."""
    if isinstance(entry, list):
        return entry if all(isinstance(r, dict) for r in entry) else None
    return _read_frozen_rows(root, entry, findings, code, label)


# --------------------------------------------------------------------------
# evidence document + setup
# --------------------------------------------------------------------------
def load_manifest(root: Path, findings):
    man_path = root / "summaries/campaign_manifest.json"
    if not man_path.is_file():
        findings.error("B_manifest_missing", str(man_path))
        return None
    try:
        return json.loads(man_path.read_text())
    except ValueError as exc:
        findings.error("B_manifest_parse", str(exc))
        return None


def load_evidence(root: Path, findings):
    """Resolve the manifest.hardening_evidence pointer to the evidence document."""
    man = load_manifest(root, findings)
    if man is None:
        return None, None
    pointer = man.get("hardening_evidence")
    if not isinstance(pointer, dict):
        findings.error("B_pointer_missing",
                       "manifest.hardening_evidence {contract, path, sha256} required "
                       "for hardening-era campaigns")
        return man, None
    if pointer.get("contract") != CONTRACT:
        findings.error("B_pointer_contract",
                       f"hardening_evidence.contract must be {CONTRACT!r}, "
                       f"got {pointer.get('contract')!r}")
    data = _read_frozen_bytes(root, pointer, findings, "B_pointer_reference",
                              "hardening_evidence")
    if data is None:
        return man, None
    try:
        evidence = json.loads(data)
    except ValueError as exc:
        findings.error("B_evidence_parse", str(exc))
        return man, None
    if not isinstance(evidence, dict) or evidence.get("contract") != CONTRACT:
        findings.error("B_evidence_contract",
                       f"evidence document contract must be {CONTRACT!r}")
        return man, evidence if isinstance(evidence, dict) else None
    return man, evidence


def load_setup(root: Path, evidence, findings):
    """Resolve + hash-check the setup reference and run setup.check_setup."""
    ref = (evidence or {}).get("setup")
    doc = _read_frozen_json(root, ref, findings, "B_setup_reference", "evidence.setup")
    if doc is None:
        return None
    try:
        errors = SETUP.check_setup(root, doc)
    except Exception as exc:                       # defensive: setup must not crash the loader
        findings.error("B_setup_check_crashed", repr(exc))
        return doc
    for err in errors:
        findings.error("B_setup_blocker", err)
    if not errors:
        findings.info("B_setup_valid", "check_setup returned no blockers")
    return doc


# --------------------------------------------------------------------------
# rendered prompt lane records (frozen outgoing-message identity)
# --------------------------------------------------------------------------
def rendered_records(root: Path, setup_doc, findings):
    """{(lane_id, task_id): messages} from the setup rendered prompt files."""
    bound = {}
    if not isinstance(setup_doc, dict):
        return bound
    for lane in setup_doc.get("lanes") or []:
        if not isinstance(lane, dict) or lane.get("applicable") is not True:
            continue
        lid = lane.get("lane_id")
        data = _read_frozen_bytes(root, {"path": lane.get("rendered_prompt_file"),
                                         "sha256": lane.get("rendered_prompt_sha256")},
                                  findings, "B_setup_rendered", f"lanes[{lid}].rendered")
        if data is None:
            continue
        try:
            rendered = json.loads(data)
        except ValueError as exc:
            findings.error("B_setup_rendered", f"lanes[{lid}]: rendered JSON unparsable ({exc})")
            continue
        records = rendered.get("records") if isinstance(rendered, dict) else rendered
        for rec in records or []:
            if isinstance(rec, dict) and isinstance(rec.get("task_id"), str):
                bound[(lid, rec["task_id"])] = rec.get("messages")
    return bound


# --------------------------------------------------------------------------
# row binding: outgoing messages, lane coverage, completion controls
# --------------------------------------------------------------------------
def _fixture_user_text(fixture_task):
    for message in reversed(fixture_task.get("messages") or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return message.get("content")
    return None


def _last_user_content(messages):
    for message in reversed(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return message.get("content")
    return None


def _setup_lane(setup_doc, lane_id):
    for lane in (setup_doc or {}).get("lanes") or []:
        if isinstance(lane, dict) and lane.get("lane_id") == lane_id:
            return lane
    return None


def _selected_profile_id(setup_doc):
    prof = (setup_doc or {}).get("profile") or {}
    pid = prof.get("profile_id")
    return pid if isinstance(pid, str) and pid else None


def _canon_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _lane_request_identity(setup_doc, lane_id="DEPLOYMENT"):
    """Resolved frozen request envelope of a lane (profile defaults apply)."""
    lane = _setup_lane(setup_doc, lane_id) or {}
    profile = (setup_doc or {}).get("profile") or {}
    return {
        "profile_id": lane.get("profile_id", profile.get("profile_id")),
        "template_sha256": lane.get("template_sha256", profile.get("template_sha256")),
        "sampler": lane.get("sampler", profile.get("sampler")),
        "effective_reasoning": lane.get("effective_reasoning", profile.get("effective_reasoning")),
    }


def _check_request_identity(identity, row, *, label, findings, envelope=None):
    """Retained runtime controls must match the frozen lane request identity.

    Either one digest-comparable shared request_envelope covers the section,
    or every row carries its own request_identity; both must equal the frozen
    DEPLOYMENT lane identity so seed/runtime cherry-picking cannot hide
    behind user-message and max_tokens checks.
    """
    wanted = _canon_json(identity)
    own = row.get("request_identity")
    if envelope is None:
        if not isinstance(own, dict) or _canon_json(own) != wanted:
            findings.error("B_row_request_identity",
                           f"{label}: retained request_identity (profile_id, template_sha256, "
                           "sampler, effective_reasoning) is required per row and must equal the "
                           "frozen DEPLOYMENT lane identity (or declare one shared "
                           "request_envelope for the whole section)")
            return False
        return True
    if own is not None and _canon_json(own) != wanted:
        findings.error("B_row_request_identity",
                       f"{label}: row request_identity contradicts both the shared envelope and "
                       "the frozen DEPLOYMENT lane identity")
        return False
    return True


def _class_of_task(setup_doc, task_id):
    for entry in (setup_doc or {}).get("task_classes") or []:
        for scored in (entry or {}).get("scored_tasks") or []:
            if isinstance(scored, dict) and scored.get("task_id") == task_id:
                return entry.get("class_id"), scored
    return None, None


def _semantic_ceiling(setup_doc, class_id):
    sel = (setup_doc or {}).get("ceiling_selection") or {}
    decl = (sel.get("per_class") or {}).get(class_id) or {}
    return decl.get("selected_ceiling")


def _operational_cap(setup_doc, lane_id):
    for cap in (setup_doc or {}).get("operational_caps") or []:
        if isinstance(cap, dict) and cap.get("lane_id") == lane_id:
            return cap.get("cap_tokens")
    return None


def bind_generation_row(row, *, fixture_task_user, setup_doc, lane_coverage, rendered,
                        lane_ceiling, cap_tokens, label, findings, require_lane_ceiling=True):
    """Bind one raw generation row to fixture + setup lane identity and ceilings.

    lane_ceiling: the exact required max_tokens for this row's lane/class
    (semantic class calibration ceiling), or None to skip the equality check.

    Load-bearing identity: every row must run the selected DEPLOYMENT prompt
    lane under the selected profile (diagnostic MINIMAL/OPTIMIZED lanes never
    headline), carry an explicit tool_calls/tool_actions list (absence is
    never a silent default) and a verbatim finish plus a retained output
    channel.
    """
    ok = True
    task_id = row.get("id")
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages or not all(
            isinstance(m, dict) and isinstance(m.get("role"), str) for m in messages):
        findings.error("B_row_missing_messages",
                       f"{label}: actual outgoing messages list required for prospective rows")
        ok = False
        messages = None
    if "output" not in row and "content" not in row:
        findings.error("B_row_output_channel",
                       f"{label}: retained output channel (output/content key) required, "
                       "even when empty")
        ok = False
    finish = row.get("finish", row.get("finish_reason"))
    if not isinstance(finish, str) or not finish.strip():
        findings.error("B_row_finish",
                       f"{label}: verbatim finish_reason string required")
        ok = False
    prompt_lane = row.get("prompt_lane")
    lane_declared = False
    if not isinstance(prompt_lane, str) or not prompt_lane:
        findings.error("B_row_prompt_lane", f"{label}: prompt_lane required")
        ok = False
    elif _setup_lane(setup_doc, prompt_lane) is None:
        findings.error("B_row_prompt_lane",
                       f"{label}: prompt_lane {prompt_lane!r} is not a declared setup lane")
        ok = False
    else:
        lane_declared = True
        covered = (lane_coverage or {}).get(prompt_lane) or []
        if task_id not in covered:
            findings.error("B_row_lane_coverage",
                           f"{label}: task {task_id!r} is not covered by lane {prompt_lane!r}")
            ok = False
    deployment = _setup_lane(setup_doc, "DEPLOYMENT") or {}
    wanted_profile = deployment.get("profile_id") or _selected_profile_id(setup_doc)
    if wanted_profile is not None:
        if row.get("profile_id") != wanted_profile:
            findings.error("B_row_profile_identity",
                           f"{label}: row profile_id {row.get('profile_id')!r} must equal the "
                           f"selected DEPLOYMENT profile {wanted_profile!r}")
            ok = False
        if lane_declared and prompt_lane != "DEPLOYMENT":
            findings.error("B_row_profile_identity",
                           f"{label}: load-bearing rows must run the selected DEPLOYMENT prompt "
                           f"lane; diagnostic lane {prompt_lane!r} evidence can never headline")
            ok = False
    elif row.get("profile_id") is not None:
        findings.error("B_row_profile_identity",
                       f"{label}: row carries profile_id but the frozen setup declares no "
                       "selected profile")
        ok = False
    if messages is not None:
        rendered_msgs = (rendered or {}).get((prompt_lane, task_id)) if prompt_lane else None
        if rendered_msgs is not None:
            if messages != rendered_msgs:
                findings.error("B_row_messages_mismatch",
                               f"{label}: outgoing messages do not equal the frozen rendered "
                               f"record for lane {prompt_lane!r} task {task_id!r}")
                ok = False
        else:
            findings.error("B_row_messages_mismatch",
                           f"{label}: frozen rendered message record required")
            ok = False
        if fixture_task_user is not None:
            if _last_user_content(messages) != fixture_task_user:
                findings.error("B_row_user_task_mismatch",
                               f"{label}: outgoing user task does not equal the frozen "
                               f"fixture prompt for {task_id!r}")
                ok = False
    max_tokens = row.get("max_tokens")
    if type(max_tokens) is not int or max_tokens <= 0:
        findings.error("B_row_max_tokens",
                       f"{label}: actual positive integer max_tokens completion control required")
        ok = False
    else:
        if lane_ceiling is not None and require_lane_ceiling and max_tokens != lane_ceiling:
            findings.error("B_row_max_tokens",
                           f"{label}: max_tokens {max_tokens} does not match the class/lane "
                           f"setup ceiling {lane_ceiling}")
            ok = False
        if cap_tokens is not None and max_tokens > cap_tokens:
            findings.error("B_row_max_tokens",
                           f"{label}: max_tokens {max_tokens} exceeds the lane operational "
                           f"cap {cap_tokens}")
            ok = False
    actions, calls = row.get("tool_actions"), row.get("tool_calls")
    if actions is None and calls is None:
        findings.error("B_row_tool_evidence",
                       f"{label}: explicit tool_calls or tool_actions list required "
                       "(an empty list is valid; absence is never a silent default)")
        ok = False
    else:
        for name, value in (("tool_calls", calls), ("tool_actions", actions)):
            if value is not None and not isinstance(value, list):
                findings.error("B_row_tool_evidence",
                               f"{label}: {name} must be a list when present")
                ok = False
        if actions is not None and calls is not None and actions != calls:
            findings.error("B_row_tool_conflict",
                           f"{label}: conflicting tool_actions and tool_calls; raw tool evidence "
                           "is never silently ignored")
            ok = False
    return ok


# --------------------------------------------------------------------------
# reliability derivation
# --------------------------------------------------------------------------
def derive_reliability(root: Path, evidence, setup_doc, findings):
    """Rescore the raw paired lanes with reliability.evaluate (scorer v3)."""
    rel = (evidence or {}).get("reliability")
    if not isinstance(rel, dict):
        findings.error("B_reliability_missing", "evidence.reliability section required")
        return None, None
    fixture_ref = rel.get("fixture") or {}
    if fixture_ref.get("path") != FIXTURE_RELIABILITY_V3:
        findings.error("B_reliability_fixture",
                       f"reliability fixture must be {FIXTURE_RELIABILITY_V3}")
    fixture_data = _read_frozen_json(REPO_ROOT, fixture_ref, findings,
                                     "B_reliability_fixture", "reliability.fixture")
    if fixture_data is None:
        return None, None
    tasks = {t.get("id"): t for t in fixture_data.get("tasks") or []}

    scorer = rel.get("scorer") or {}
    if scorer.get("id") != RELIABILITY_SCORER_V3:
        findings.error("B_reliability_scorer",
                       f"scorer id must be {RELIABILITY_SCORER_V3!r}, got {scorer.get('id')!r}")
    scorer_bytes = _read_frozen_bytes(REPO_ROOT, scorer, findings,
                                      "B_reliability_scorer", "reliability.scorer")
    if scorer_bytes is not None:
        current = (REPO_ROOT / "scorers/score_reliability.py").read_bytes()
        if scorer_bytes != current:
            findings.error("B_reliability_scorer",
                           "new-era bundles must record the actual current scorer source hash")
    if scorer.get("selftest") != "PASS":
        findings.error("B_reliability_scorer", "scorer selftest must be PASS")

    setup_seeds = ((setup_doc or {}).get("seed_plan") or {})
    seeds = rel.get("seeds")
    if sorted(seeds or []) != sorted(setup_seeds.get("base_seeds") or []):
        findings.error("B_reliability_seeds",
                       "declared base seeds must equal the frozen setup seed_plan base_seeds")
    adaptive = rel.get("adaptive_seed")
    if adaptive != setup_seeds.get("adaptive_seed"):
        findings.error("B_reliability_seeds",
                       "declared adaptive seed must equal the frozen setup seed_plan")
    if not isinstance(seeds, list) or len(seeds) != 2 or len(set(seeds)) != 2:
        findings.error("B_reliability_seeds", "two distinct base seeds required")
        return None, None

    lanes = rel.get("lanes")
    if not isinstance(lanes, dict) or set(lanes) != {"semantic", "operational"}:
        findings.error("B_reliability_lanes", "exactly semantic and operational lanes required")
        return None, None
    envelope = rel.get("request_envelope")
    if envelope is not None and _canon_json(envelope) != _canon_json(
            _lane_request_identity(setup_doc)):
        findings.error("B_row_request_identity",
                       "reliability.request_envelope differs from the frozen DEPLOYMENT lane "
                       "request identity; retained runtime controls must match the selected "
                       "profile")
    lane_coverage = (setup_doc or {}).get("lane_coverage") or {}
    rendered = rendered_records(root, setup_doc, findings)
    rows_by_lane = {}
    for lane_name, seed_entries in lanes.items():
        if not isinstance(seed_entries, dict):
            findings.error("B_reliability_lanes", f"lanes.{lane_name} must map seeds to rows")
            return None, None
        per_seed = {}
        for key, entry in seed_entries.items():
            try:
                seed = int(key)
            except (TypeError, ValueError):
                findings.error("B_reliability_lanes", f"lanes.{lane_name}: integer seed required")
                return None, None
            rows = _rows_entry(root, entry, findings, "B_reliability_rows",
                               f"lanes.{lane_name}.{key}")
            if rows is None:
                return None, None
            per_seed[seed] = rows
        rows_by_lane[lane_name] = per_seed

    executed = sorted(rows_by_lane["semantic"])
    if sorted(rows_by_lane["operational"]) != executed or executed not in (
            sorted(seeds), sorted(list(seeds) + [adaptive])):
        findings.error("B_reliability_seeds",
                       "paired lanes require exactly the base seeds or base+adaptive seeds")
        return None, None

    for lane_name, per_seed in rows_by_lane.items():
        for seed, rows in per_seed.items():
            for index, row in enumerate(rows):
                label = f"lanes.{lane_name}.seed{seed}.row{index}({row.get('id')})"
                if type(row.get("seed")) is not int or row["seed"] != seed:
                    findings.error("B_row_seed_identity",
                                   f"{label}: row seed {row.get('seed')!r} must equal the "
                                   "containing seed key")
                _check_request_identity(_lane_request_identity(setup_doc), row,
                                        label=label, findings=findings,
                                        envelope=rel.get("request_envelope"))
                task = tasks.get(row.get("id"))
                if task is None:
                    findings.error("B_row_unknown_task",
                                   f"{label}: not a frozen fixture task id")
                    continue
                class_id, _scored = _class_of_task(setup_doc, row.get("id"))
                lane_ceiling = None
                if lane_name == "semantic":
                    lane_ceiling = _semantic_ceiling(setup_doc, class_id) if class_id else None
                    if lane_ceiling is None:
                        findings.error("B_row_max_tokens",
                                       f"{label}: no frozen class ceiling for class {class_id!r}")
                cap = _operational_cap(setup_doc, row.get("prompt_lane"))
                if lane_name == "operational":
                    lane_ceiling = cap
                    if cap is None:
                        findings.error("B_row_max_tokens",
                                       f"{label}: frozen operational cap required")
                bind_generation_row(
                    row, fixture_task_user=_fixture_user_text(task),
                    setup_doc=setup_doc, lane_coverage=lane_coverage, rendered=rendered,
                    lane_ceiling=lane_ceiling, cap_tokens=None, label=label, findings=findings)

    fixture_path = REPO_ROOT / fixture_ref["path"]
    try:
        gate, outcomes = R.evaluate(fixture_path, rows_by_lane,
                                    seeds=tuple(seeds), adaptive_seed=adaptive)
    except Exception as exc:
        findings.error("B_reliability_derivation", f"{type(exc).__name__}: {exc}")
        return None, None
    findings.info("B_gate_decision", str(gate.get("decision")))
    return gate, outcomes


# --------------------------------------------------------------------------
# shared qualitative adjudication binding (capability reviews + oracle reviews)
# --------------------------------------------------------------------------
def _adjudication_problems(root, reviews, *, target_sha, content=None,
                           prompt_sha=None, dispositions=frozenset(),
                           tie_break_dispositions=None):
    """Shared hash-bound review checks for qualitative adjudication records.

    Every review must bind a distinct identified evaluator (human|agent,
    independent of execution, model-identity blinded), a hash-bound frozen
    rubric {id, path, sha256}, a rationale, exact quoted evidence from the
    reviewed bytes, the exact reviewed bytes (target_sha256) and — when given
    — the exact prompt bytes (prompt_sha256), and carry a disposition from
    `dispositions`. A record declaring {"role": "tie_break"} is a tie-break
    reviewer under welp-review-adjudication-0.1.0-draft: at most one is
    permitted per target, it must additionally declare
    previous_reviews_visible exactly false (it is an isolated blinded
    adjudication that never saw the other reviews), and its disposition comes
    from `tie_break_dispositions` (the deciding set plus RUBRIC_AMBIGUITY).
    Agent reviewers must never be labeled human. Returns
    (problems, outcomes, independent_reviewers).
    """
    problems, seen, outcomes, independent, rubric_shas = [], set(), set(), [], set()
    if not isinstance(reviews, list) or not reviews:
        return ["at least one review record is required"], outcomes, independent
    tie_break_seen = 0
    for review in reviews:
        if not isinstance(review, dict):
            problems.append("review entry must be an object")
            continue
        is_tie = review.get("role") == TIE_BREAK_ROLE
        if is_tie:
            tie_break_seen += 1
            if tie_break_seen > 1:
                problems.append("at most one tie-break reviewer is permitted per target "
                                "(frozen maximum of three reviewers)")
            if tie_break_dispositions is None:
                problems.append("tie-break reviewer not permitted by this adjudication")
        evaluator = review.get("evaluator") or {}
        reviewer = evaluator.get("id")
        if not isinstance(reviewer, str) or not reviewer.strip() or reviewer in seen:
            problems.append("distinct identified reviewers required")
            continue
        seen.add(reviewer)
        if evaluator.get("kind") not in {"human", "agent"}:
            problems.append(f"{reviewer}: evaluator kind must be human or agent")
        if evaluator.get("independent_of_execution") is not True or \
                evaluator.get("model_identity_blinded") is not True:
            problems.append(f"{reviewer}: review must be independent and "
                            "model-identity-blinded")
        if is_tie:
            if review.get("previous_reviews_visible") is not False:
                problems.append(f"{reviewer}: tie-break reviewer must declare "
                                "previous_reviews_visible exactly false (an isolated "
                                "blinded adjudication, never shown the other reviews)")
        if review.get("target_sha256") != target_sha:
            problems.append(f"{reviewer}: review is not bound to the exact reviewed bytes "
                            "(target_sha256 mismatch)")
            continue
        if prompt_sha is not None and review.get("prompt_sha256") != prompt_sha:
            problems.append(f"{reviewer}: review is not bound to the exact prompt bytes "
                            "(prompt_sha256 mismatch)")
            continue
        rubric = review.get("rubric")
        if not (isinstance(rubric, dict) and isinstance(rubric.get("id"), str)
                and rubric["id"].strip() and _is_rooted_rel(rubric.get("path"))
                and isinstance(rubric.get("sha256"), str) and HASH_RE.match(rubric["sha256"])):
            problems.append(f"{reviewer}: review must cite a hash-bound rubric "
                            "{id, path, sha256} frozen beside the reviewed evidence")
        else:
            rubric_path = root / rubric["path"]
            rubric_bytes = (rubric_path.read_bytes()
                            if rubric_path.resolve().is_relative_to(root.resolve())
                            and rubric_path.is_file() else None)
            if rubric_bytes is None or _sha256_bytes(rubric_bytes) != rubric["sha256"]:
                problems.append(f"{reviewer}: rubric bytes missing or sha256 mismatch: "
                                f"{rubric['path']}")
            rubric_shas.add(rubric["sha256"])
        if not isinstance(review.get("rationale"), str) or not review["rationale"].strip():
            problems.append(f"{reviewer}: rubric adjudication rationale required")
        quotes = review.get("evidence")
        if not isinstance(quotes, list) or not quotes or any(
                not isinstance(q, str) or not q
                or (content is not None and q not in content) for q in quotes):
            problems.append(f"{reviewer}: review must quote the exact reviewed text")
        disposition = review.get("disposition")
        if is_tie and tie_break_dispositions is not None:
            allowed = tie_break_dispositions
        else:
            allowed = dispositions
        if disposition not in allowed:
            problems.append(f"{reviewer}: invalid review disposition {disposition!r} "
                            f"(expected one of {sorted(allowed)})")
            continue
        outcomes.add(disposition)
        if evaluator.get("independent_of_execution") is True and \
                evaluator.get("model_identity_blinded") is True:
            independent.append(reviewer)
    if len(rubric_shas) > 1:
        problems.append("all reviewers of one target must adjudicate under the same "
                        "frozen rubric")
    if len(seen) > REVIEWERS_MAXIMUM:
        problems.append(f"more than {REVIEWERS_MAXIMUM} reviewers on one target is not "
                        "permitted (frozen maximum of three reviewer calls)")
    return problems, outcomes, independent


def _resolve_blinded_adjudication(root, reviews, *, target_sha, content=None,
                                  prompt_sha=None, dispositions=frozenset(),
                                  deciding_tie_break_dispositions=frozenset()):
    """Frozen deciding-review adjudication rule (welp-review-adjudication-0.1.0-draft).

    Two independent model-identity-blinded agreeing reviewers decide. On a
    recorded 1-1 disagreement exactly ONE additional blinded tie-break
    reviewer (role "tie_break", previous_reviews_visible false, bound to the
    same rubric and reviewed bytes) may be invoked; a deciding 2-of-3
    majority resolves the target and the minority review is retained. A
    tie-break disposition of RUBRIC_AMBIGUITY fails closed: the rubric itself
    is ambiguous or self-contradictory, the target stays unresolved, and
    HUMAN_REVIEW_REQUIRED is recorded — majority voting never overrides an
    invalid rubric. At most three reviewers per target; a tie-break invoked
    without a recorded first-two disagreement, a second tie-break, or a
    malformed tie-break record is rejected. Returns one of:
      {"state": "resolved", "disposition": X}
      {"state": "unresolved", "reason": str, "rubric_ambiguity": bool}
      {"state": "problems", "problems": [..]}
    """
    problems, _outcomes, independent = _adjudication_problems(
        root, reviews, target_sha=target_sha, content=content, prompt_sha=prompt_sha,
        dispositions=dispositions,
        tie_break_dispositions=deciding_tie_break_dispositions)
    if problems:
        return {"state": "problems", "problems": problems}
    base = [r for r in reviews if isinstance(r, dict)
            and r.get("role") != TIE_BREAK_ROLE]
    tie = [r for r in reviews if isinstance(r, dict)
           and r.get("role") == TIE_BREAK_ROLE]
    if len(independent) < REVIEWERS_REQUIRED or len(base) < REVIEWERS_REQUIRED:
        return {"state": "unresolved",
                "reason": f"fewer than {REVIEWERS_REQUIRED} independent blinded reviewers; "
                          "unresolved load-bearing review",
                "rubric_ambiguity": False}
    base_dispositions = [r["disposition"] for r in base]
    if len(set(base_dispositions)) == 1:
        if tie:
            return {"state": "problems",
                    "problems": ["tie-break reviewer invoked without a recorded "
                                 "two-reviewer disagreement; re-reviewing an agreed "
                                 "decision is not permitted"]}
        return {"state": "resolved", "disposition": base_dispositions[0]}
    if len(base) == REVIEWERS_REQUIRED and len(set(base_dispositions)) == 2:
        if not tie:
            return {"state": "unresolved",
                    "reason": "reviewer disagreement; the frozen adjudication rule permits "
                              "exactly one blinded tie-break reviewer (2-of-3)",
                    "rubric_ambiguity": False}
        tie_disposition = tie[0]["disposition"]
        if tie_disposition == RUBRIC_AMBIGUITY:
            return {"state": "unresolved",
                    "reason": f"{RUBRIC_AMBIGUITY}: the tie-break review found the frozen "
                              "rubric ambiguous or internally contradictory; "
                              "HUMAN_REVIEW_REQUIRED; majority vote does not resolve an "
                              "invalid rubric",
                    "rubric_ambiguity": True}
        return {"state": "resolved", "disposition": tie_disposition}
    return {"state": "unresolved",
            "reason": "reviewer disagreement with no tie-break slot remaining "
                      f"(frozen maximum of {REVIEWERS_MAXIMUM} reviewers)",
            "rubric_ambiguity": False}


ORACLE_REVIEW_DISPOSITIONS = {"VALIDATED", "FAILED"}


def _resolve_oracle_reviews(root, cell, answer, prompt_text, findings, label):
    """Resolve Family A oracle ambiguity via blinded adjudications, fail closed.

    Returns the agreed resolution ("VALIDATED"|"FAILED") only when
    independent, model-identity-blinded reviewers bind the exact prompt
    bytes, the exact answer bytes, a frozen rubric, a rationale and exact
    quotes. Two agreeing reviewers decide; a recorded 1-1 disagreement
    admits exactly one blinded tie-break reviewer (deciding 2-of-3); a
    RUBRIC_AMBIGUITY tie-break fails closed to human review. Anything else
    returns None (pending); the ambiguity is then never coerced into a
    measured disposition.
    """
    reviews = cell.get("oracle_reviews")
    if not reviews:
        return None
    prompt_sha = hashlib.sha256(prompt_text.encode()).hexdigest() \
        if isinstance(prompt_text, str) else None
    if prompt_sha is None:
        findings.error("B_context_oracle_review_unbound",
                       f"{label}: oracle reviews require the retained prompt bytes to bind "
                       "prompt_sha256")
        return None
    answer_sha = hashlib.sha256(answer.encode()).hexdigest()
    resolved = _resolve_blinded_adjudication(
        root, reviews, target_sha=answer_sha, content=answer, prompt_sha=prompt_sha,
        dispositions=ORACLE_REVIEW_DISPOSITIONS,
        deciding_tie_break_dispositions=ORACLE_REVIEW_DISPOSITIONS | {RUBRIC_AMBIGUITY})
    if resolved["state"] == "problems":
        for problem in resolved["problems"]:
            findings.error("B_context_oracle_review_unbound", f"{label}: {problem}")
        return None
    if resolved["state"] == "unresolved":
        findings.error("B_context_oracle_review_unbound", f"{label}: {resolved['reason']}")
        return None
    return resolved["disposition"]


# --------------------------------------------------------------------------
# context derivation (oracle recheck from raw answers)
# --------------------------------------------------------------------------
def _context_preflight(cell, prompt_text, setup_doc, findings, label):
    """Verify retained measurement geometry, not an asserted preflight PASS."""
    identity = _lane_request_identity(setup_doc)
    _check_request_identity(identity, cell, label=label, findings=findings)
    system = (_setup_lane(setup_doc, "DEPLOYMENT") or {}).get("system_prompt", "")
    expected = SETUP._exact_envelope(system, prompt_text)
    if cell.get("prompt_lane") != "DEPLOYMENT" or cell.get("messages") != expected:
        findings.error("B_context_profile_identity",
                       f"{label}: exact DEPLOYMENT request envelope required")
    pf = cell.get("preflight")
    if not isinstance(pf, dict):
        findings.error("B_context_geometry", f"{label}: retained token preflight required")
        return
    configured, reserve = cell.get("configured_context"), cell.get("reserve_tokens")
    rendered, usable = pf.get("rendered_tokens"), pf.get("usable_tokens")
    if (any(type(v) is not int or v <= 0 for v in (configured, reserve, rendered, usable))
            or usable != configured - reserve or not 0.97 <= rendered / usable <= 1
            or cell.get("max_tokens") != reserve
            or pf.get("inference_prompt_tokens") != rendered):
        findings.error("B_context_geometry",
                       f"{label}: near-full rendered tokens, reserve and actual request must agree")
    if (not isinstance(prompt_text, str)
            or pf.get("prompt_sha256") != _sha256_bytes(prompt_text.encode())
            or pf.get("template_sha256") != identity.get("template_sha256")):
        findings.error("B_context_geometry",
                       f"{label}: preflight prompt/template identity mismatch")
    depths = pf.get("depths_pct")
    try:
        placed = isinstance(depths, dict) and CX.placement_preflight(depths)["pass"]
    except (TypeError, ValueError, KeyError):
        placed = False
    if not placed:
        findings.error("B_context_geometry", f"{label}: five-depth placement gate failed")


def derive_context(root: Path, evidence, setup_doc, findings):
    ctx = (evidence or {}).get("context")
    if not isinstance(ctx, dict):
        findings.error("B_context_missing", "evidence.context section required")
        return None, []
    fixture_ref = ctx.get("fixture") or {}
    if fixture_ref.get("path") != FIXTURE_FAMILY_A:
        findings.error("B_context_fixture", f"context fixture must be {FIXTURE_FAMILY_A}")
    fixture_data = _read_frozen_json(REPO_ROOT, fixture_ref, findings,
                                     "B_context_fixture", "context.fixture")
    if fixture_data is None:
        return None, []
    version = fixture_data.get("version")
    if version != FAMILY_A_1_3:
        findings.error("B_context_fixture",
                       f"context fixture version must be {FAMILY_A_1_3!r}, got {version!r}")
    question_block = ((fixture_data.get("construction") or {}).get("question_block") or "")
    findings.info("B_context_fixture_version", str(version))

    plan = ctx.get("plan")
    rows = ctx.get("rows")
    if not isinstance(plan, dict) or not isinstance(rows, list):
        findings.error("B_context_invalid", "context plan object and rows list required")
        return None, []

    # exact lane/seed/rung inventory: the plan is bound to the frozen setup
    plan_seeds = plan.get("seeds")
    setup_seeds = ((setup_doc or {}).get("seed_plan") or {}).get("base_seeds") or []
    if not isinstance(plan_seeds, list) or sorted(plan_seeds) != sorted(setup_seeds):
        findings.error("B_context_plan_inventory",
                       "context plan seeds must equal the frozen setup seed_plan base_seeds "
                       f"{sorted(setup_seeds)} (got {plan_seeds!r})")
    plan_lanes = plan.get("lanes")
    if not isinstance(plan_lanes, list) or not plan_lanes or any(
            lane not in ("semantic", "operational") for lane in plan_lanes):
        findings.error("B_context_plan_inventory",
                       "context plan lanes must be a non-empty subset of "
                       "['semantic', 'operational']")
    wanted_profile = _selected_profile_id(setup_doc)

    question_present = bool(question_block)
    adjusted = []
    pending_review_targets = []

    def cell_reasoning_declared(cell):
        """Declared/effective reasoning tri-state from the retained request
        identity (welp-context 0.3.0: feeds the CP-1 budget attribution)."""
        identity = cell.get("request_identity")
        effective = (identity or {}).get("effective_reasoning") \
            if isinstance(identity, dict) else None
        mode = (effective or {}).get("mode") if isinstance(effective, dict) else None
        if isinstance(mode, str):
            u = mode.upper()
            if u in OW.REASONING_STATES_TRUE:
                return True
            if u in OW.REASONING_STATES_FALSE:
                return False
        return None

    for index, cell in enumerate(rows):
        cell = dict(cell)
        raw = cell.get("raw") if isinstance(cell.get("raw"), dict) else {}
        answer = raw.get("answer")
        finish = raw.get("finish", raw.get("finish_reason"))
        usage = raw.get("usage") or {}
        label = f"context.cell[{index}]({cell.get('configured_context')}/{cell.get('lane')}/{cell.get('seed')})"
        if wanted_profile is not None:
            if cell.get("profile_id") != wanted_profile:
                findings.error("B_context_profile_identity",
                               f"{label}: cell profile_id {cell.get('profile_id')!r} must equal "
                               f"the selected profile {wanted_profile!r}")
        elif cell.get("profile_id") is not None:
            findings.error("B_context_profile_identity",
                           f"{label}: cell carries profile_id but the frozen setup declares no "
                           "selected profile")
        messages = cell.get("messages")
        prompt_text = _last_user_content(messages) if isinstance(messages, list) else None
        if not isinstance(prompt_text, str) or not prompt_text:
            findings.error("B_context_user_task_mismatch",
                           f"{label}: actual outgoing prompt required")
        elif question_present and question_block not in prompt_text:
            findings.error("B_context_user_task_mismatch",
                           f"{label}: outgoing user turn lacks the frozen Controlled Context "
                           f"(Family A) question block")
        disposition = cell.get("disposition")
        evidence_note = cell.get("evidence")
        measured = disposition in {"VALIDATED", "FAILED", "BUDGET_LIMITED"} \
            and cell.get("execution_valid") is True
        if disposition in {"FIT_LIMIT", "INTEGRATION_BLOCKED"}:
            limit = cell.get("limitation") or {}
            log = _read_frozen_bytes(root, limit.get("log"), findings,
                                     "B_context_limit_evidence", label)
            quote = limit.get("observed_error")
            if (log is None or not isinstance(quote, str) or not quote
                    or quote not in log.decode("utf-8", errors="replace")
                    or not isinstance(limit.get("command"), str) or not limit["command"]
                    or not isinstance(evidence_note, str)
                    or f"sha256:{_sha256_bytes(log or b'')}" not in evidence_note):
                findings.error("B_context_limit_evidence",
                               f"{label}: command, hash-bound log and verbatim observed error required")
                cell["execution_valid"] = False
        if measured:
            _context_preflight(cell, prompt_text, setup_doc, findings, label)
            facts = (fixture_data.get("construction") or {}).get("inserted_facts") or []
            depths = (cell.get("preflight") or {}).get("depths_pct") or {}
            if set(depths) != {fact["target"] for fact in facts} or any(
                    not isinstance(prompt_text, str) or prompt_text.count(fact["text"]) != 1
                    for fact in facts):
                findings.error("B_context_user_task_mismatch",
                               f"{label}: all frozen facts and named token depths required exactly once")
            ceiling = (_semantic_ceiling(setup_doc, plan.get("class_id"))
                       if cell.get("lane") == "semantic"
                       else _operational_cap(setup_doc, "DEPLOYMENT"))
            if ceiling is None or cell.get("reserve_tokens") != ceiling:
                findings.error("B_row_max_tokens",
                               f"{label}: reserve must match calibrated class or operational cap")
            if not isinstance(evidence_note, str) or not evidence_note.strip():
                findings.error("B_context_evidence_unbound",
                               f"{label}: trusted measurement requires non-empty evidence")
                cell["execution_valid"] = False
            elif isinstance(answer, str) and answer.strip():
                answer_sha = hashlib.sha256(answer.encode()).hexdigest()
                if f"sha256:{answer_sha}" not in evidence_note:
                    findings.error("B_context_evidence_unbound",
                                   f"{label}: evidence does not carry the raw answer sha256 binding")
            ctoks = (usage or {}).get("completion_tokens")
            rung_tokens = cell.get("configured_context")
            if type(ctoks) is not int or ctoks <= 0 or (
                    type(rung_tokens) is int and ctoks > rung_tokens):
                findings.error("B_context_geometry",
                               f"{label}: valid token geometry required: observed "
                               f"completion_tokens {ctoks!r} must be a positive count inside "
                               f"the configured rung {rung_tokens!r}")
                cell["execution_valid"] = False
        # welp-context 0.3.0 (Granite D-01 repair): every measured cell is
        # re-derived from the retained raw bytes, including answerless rows.
        # score_family_a returns the frozen empty-answer gate bag there, so
        # the derivation never sees asserted values. An answerless row is
        # representable only as BUDGET_LIMITED with the raw record proving a
        # terminal generation state and the evidence binding the empty-answer
        # sha256; anything else fails closed (asserted dispositions never
        # substitute for the oracle).
        outcome = None
        derived = None
        oracle_bound = False
        scored_answer = answer if isinstance(answer, str) else ""
        try:
            gates = CX.score_family_a(scored_answer)
            reserve = (cell.get("reserve_tokens")
                       or ((setup_doc or {}).get("context_reserves") or {})
                            .get(cell.get("lane")))
            outcome = CX.rung_outcome(gates, finish, scored_answer, usage, reserve=reserve,
                                      reasoning_declared=cell_reasoning_declared(cell))
            derived = outcome["rung"]
            oracle_bound = not gates.get("review_required")
        except Exception as exc:
            findings.error("B_context_oracle_crash", f"{label}: {type(exc).__name__}: {exc}")
        answerless = not (isinstance(answer, str) and answer.strip())
        if measured and answerless:
            empty_sha = hashlib.sha256(b"").hexdigest()
            bound = isinstance(evidence_note, str) and f"sha256:{empty_sha}" in evidence_note
            if disposition != "BUDGET_LIMITED" or derived != "BUDGET_LIMITED" or not bound \
                    or not oracle_bound:
                findings.error("B_context_missing_raw",
                               f"{label}: measured cell is missing the retained raw answer; an "
                               "answerless row is representable only as a BUDGET_LIMITED cell "
                               "whose raw record proves the terminal generation state and "
                               "whose evidence binds the empty-answer sha256")
                cell["execution_valid"] = False
                measured = False
        if not answerless and outcome is not None:
            if gates.get("review_required"):
                resolution = _resolve_oracle_reviews(root, cell, answer, prompt_text,
                                                     findings, label)
                if resolution is None:
                    pending_review_targets.append(
                        {"kind": "family_a_cell", "label": label,
                         "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                         "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest()
                         if isinstance(prompt_text, str) else None,
                         "reasons": gates.get("review_reasons") or []})
                    findings.warn("B_context_oracle_pending",
                                  f"{label}: oracle ambiguity unresolved; fail-closed "
                                  "pending review — never coerced into a measured "
                                  "disposition")
                else:
                    derived = resolution
                    oracle_bound = True
            if oracle_bound:
                if disposition == "VALIDATED" and derived != "VALIDATED":
                    findings.error("B_context_oracle_mismatch",
                                   f"{label}: asserted VALIDATED but the raw answer oracle "
                                   f"yields {derived}; the derived outcome governs")
                    cell["disposition"] = derived if derived in CONTEXT_DISPOSITIONS else "FAILED"
                    if derived not in ("BUDGET_LIMITED",):
                        # an INVALID_REQUEST derivation is an invalid execution
                        cell["execution_valid"] = False
                elif disposition in TRUSTED_CONTEXT_DISPOSITIONS and derived == "VALIDATED" \
                        and disposition not in ("VALIDATED", "FIT_LIMIT", "INTEGRATION_BLOCKED"):
                    findings.error("B_context_oracle_mismatch",
                                   f"{label}: asserted {disposition} but the raw answer oracle "
                                   "yields VALIDATED; the derived outcome governs")
                    cell["disposition"] = "VALIDATED"
                elif disposition in TRUSTED_CONTEXT_DISPOSITIONS and derived == "FAILED" \
                        and disposition != "FAILED":
                    findings.error("B_context_oracle_mismatch",
                                   f"{label}: asserted {disposition} but the raw answer "
                                   "oracle yields FAILED; the derived outcome governs")
                    cell["disposition"] = "FAILED"
                elif disposition in TRUSTED_CONTEXT_DISPOSITIONS and derived == "BUDGET_LIMITED" \
                        and disposition not in ("VALIDATED", "FIT_LIMIT", "INTEGRATION_BLOCKED",
                                                "BUDGET_LIMITED"):
                    findings.error("B_context_oracle_mismatch",
                                   f"{label}: asserted {disposition} but the raw answer oracle "
                                   "yields BUDGET_LIMITED; the derived outcome governs")
                    cell["disposition"] = "BUDGET_LIMITED"
        if disposition is not None and disposition not in CONTEXT_DISPOSITIONS:
            findings.error("B_context_invalid",
                           f"{label}: invalid disposition {disposition!r} "
                           f"(expected one of {sorted(CONTEXT_DISPOSITIONS)})")
            cell["disposition"] = None
        adjusted.append(cell)

    try:
        summary = CX.context_summary(plan, adjusted)
    except Exception as exc:
        findings.error("B_context_invalid", f"{type(exc).__name__}: {exc}")
        return None, pending_review_targets
    findings.info("B_context_capability", str(summary.get("capability")))
    return {"plan": plan, "summary": summary, "fixture_version": version,
            "rows": adjusted}, pending_review_targets


# --------------------------------------------------------------------------
# capability modules
# --------------------------------------------------------------------------
def _run_content(root: Path, run, findings, code, label):
    """Run answer content: inline string or strict {path, sha256} text pointer."""
    content = run.get("content")
    if isinstance(content, str):
        return content
    ref = run.get("content_ref") or run.get("content")
    if isinstance(ref, dict):
        data = _read_frozen_bytes(root, ref, findings, code, label)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")
    findings.error(code, f"{label}: run content (string or path+sha256 reference) required")
    return None


def _json_content(content, label, findings):
    try:
        return json.loads(content)
    except ValueError as exc:
        findings.info("B_capability_mechanical_failure", f"{label}: strict JSON failed ({exc})")
        return None


def _fixture_json(relpath, findings, code):
    path = REPO_ROOT / relpath
    ref = {"path": relpath, "sha256": _sha256_bytes(path.read_bytes())}
    data = _read_frozen_json(REPO_ROOT, ref, findings, code, relpath)
    return data if isinstance(data, dict) else {}


def _score_linux_run(run, findings, fixture):
    case_id = run.get("case_id")
    cases = {c.get("case_id"): c for c in fixture.get("cases") or []}
    case = cases.get(case_id)
    if case is None:
        findings.error("B_capability_run_case", f"unknown linux-diagnosis case {case_id!r}")
        return None
    return case


def _capability_review_target(root, run, content, findings, label):
    """Prose-bearing runs must carry a hash-bound independent qualitative review.

    A mechanical PASS on free-prose role detail is provisional and never
    completes a module: independent, model-identity-blinded reviewers
    adjudicate the exact answer bytes under one hash-bound frozen rubric,
    with a rationale and exact quoted evidence. Two agreeing reviewers
    decide; a recorded 1-1 disagreement admits exactly one blinded
    tie-break reviewer whose deciding vote resolves 2-of-3, while a
    RUBRIC_AMBIGUITY tie-break fails closed to human review. Missing,
    unbound, disagreeing (unbroken), over-manned or malformed reviews stay
    unresolved load-bearing review.
    """
    answer_sha = hashlib.sha256(content.encode()).hexdigest()
    reviews = run.get("role_reviews") or []
    if not reviews:
        return {"complete": False, "pass": False, "unresolved": True,
                "target_sha256": answer_sha,
                "reason": f"{label}: free-prose role detail requires independent "
                          "qualitative adjudication; a mechanical PASS is provisional only"}
    resolved = _resolve_blinded_adjudication(
        root, reviews, target_sha=answer_sha, content=content,
        dispositions={"PASS", "FAIL", "NOT_EVALUABLE"},
        deciding_tie_break_dispositions={"PASS", "FAIL", RUBRIC_AMBIGUITY})
    if resolved["state"] == "problems":
        for problem in resolved["problems"]:
            findings.error("B_role_review_unbound", f"{label}: {problem}")
        return {"complete": False, "pass": False, "unresolved": True,
                "target_sha256": answer_sha, "reason": "; ".join(resolved["problems"][:3])}
    if resolved["state"] != "resolved":
        return {"complete": False, "pass": False, "unresolved": True,
                "target_sha256": answer_sha, "rubric_ambiguity": resolved["rubric_ambiguity"],
                "reason": f"{label}: {resolved['reason']}"}
    return {"complete": True, "pass": resolved["disposition"] == "PASS", "unresolved": False,
            "disposition": resolved["disposition"], "target_sha256": answer_sha}


def _coding_execution_evidence(root, run, findings, label):
    """Repository coding runs bind execution, bytes, containment, diff review.

    Requires the executed command with exit status and a hash-bound log, the
    produced code and patch as hash-bound bytes, a declared isolated
    disposable containment boundary without network, and an identified diff
    review against the frozen allowed changes. The validator only verifies
    recorded, hash-bound artifacts — it never executes recorded code.
    """
    fixture = _fixture_json(FIXTURE_REPO_CODING, findings, "B_capability_fixture")
    allowed = (fixture.get("oracle") or {}).get("allowed_changes")
    test_command = (fixture.get("oracle") or {}).get("command")
    ok = True
    commands = run.get("executed_commands")
    if not isinstance(commands, list) or not commands:
        findings.error("B_coding_execution",
                       f"{label}: executed_commands with the actual command, recorded status "
                       "and a hash-bound log are required repository-coding evidence")
        ok = False
    else:
        for index, command in enumerate(commands):
            clabel = f"{label}.executed_commands[{index}]"
            if not isinstance(command, dict) or not isinstance(command.get("command"), str) \
                    or not command["command"].strip():
                findings.error("B_coding_execution",
                               f"{clabel}: non-empty executed command string required")
                ok = False
                continue
            status = command.get("status")
            if isinstance(status, bool) or not isinstance(status, (int, str)) or \
                    (isinstance(status, str) and not status.strip()):
                findings.error("B_coding_execution",
                               f"{clabel}: recorded exit status (int or token such as "
                               "'timeout') required")
                ok = False
            if _read_frozen_bytes(root, command.get("log"), findings,
                                  "B_coding_execution", f"{clabel}.log") is None:
                ok = False
        test_runs = [c for c in commands if isinstance(c, dict)
                     and c.get("command") == test_command]
        if not test_runs or type(test_runs[-1].get("status")) is not int \
                or test_runs[-1]["status"] != 0:
            ok = False
            findings.info("B_coding_test_failure",
                          f"{label}: final supplied test command did not pass")
    for key in ("code", "patch"):
        if _read_frozen_bytes(root, run.get(key), findings,
                              "B_coding_execution", f"{label}.{key}") is None:
            findings.error("B_coding_execution",
                           f"{label}: hash-bound produced {key} bytes (code/patch hashes) "
                           "are required repository-coding evidence")
            ok = False
    containment = run.get("containment")
    if not isinstance(containment, dict) \
            or containment.get("isolated_disposable_environment") is not True \
            or containment.get("network_access") is not False \
            or not isinstance(containment.get("boundary"), str) \
            or not containment["boundary"].strip():
        findings.error("B_coding_containment",
                       f"{label}: containment evidence required — an isolated disposable "
                       "execution boundary without network; generated code is never executed "
                       "on the host or by this validator")
        ok = False
    review = run.get("diff_review")
    if not isinstance(review, dict) or not isinstance(review.get("changed_paths"), list) \
            or not review["changed_paths"] \
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        findings.error("B_coding_diff_review",
                       f"{label}: diff-review evidence required — identified reviewer over "
                       "the actual changed paths")
        ok = False
    else:
        if review.get("patch_sha256") != (run.get("patch") or {}).get("sha256"):
            findings.error("B_coding_diff_review",
                           f"{label}: diff review must bind the exact patch SHA-256")
            ok = False
        if review.get("unrelated_edits") is not False:
            findings.error("B_coding_diff_review",
                           f"{label}: unrelated edits must be absent (unrelated_edits: false) "
                           "for a clean coding run")
            ok = False
        if isinstance(allowed, list) and allowed:
            outside = [p for p in review["changed_paths"] if p not in allowed]
            if outside:
                findings.error("B_coding_diff_review",
                               f"{label}: changed paths outside the frozen allowed_changes "
                               f"{allowed}: {outside}")
                ok = False
    return ok


def derive_capabilities(root: Path, evidence, setup_doc, findings):
    """Rescore applicable capability modules from actual run evidence."""
    caps = (evidence or {}).get("capabilities")
    roles = evidence.get("declared_user_roles") or evidence.get("declared_user_role")
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, list) or not roles:
        findings.error("B_role_missing", "declared_user_role(s) required")
        roles = []
    unknown_roles = [r for r in roles if r not in ROLE_REQUIRED_MODULES]
    if unknown_roles:
        findings.error("B_role_unknown", f"unknown declared role(s): {unknown_roles}")
    required = []
    for role in roles:
        for module in ROLE_REQUIRED_MODULES.get(role, ()):
            if module not in required:
                required.append(module)
    applicability = evidence.get("module_applicability") or {}
    applicable = list(required)
    for module, decl in applicability.items():
        if not isinstance(decl, dict):
            findings.error("B_module_applicability", f"{module}: applicability must be an object")
            continue
        if decl.get("applicable") is False:
            if module in required:
                findings.error("B_module_required_excluded",
                               f"{module}: required by the closed role vocabulary for the "
                               "declared role(s); a role-required module can never be declared "
                               "inapplicable, whatever rationale or absent fixture is offered")
            elif not isinstance(decl.get("rationale"), str) or not decl["rationale"].strip():
                findings.error("B_module_exclusion_unrationaled",
                               f"{module}: excluding a role-applicable module requires "
                               "a non-empty rationale")
            else:
                applicable = [m for m in applicable if m != module]
        elif decl.get("applicable") is True and module not in applicable:
            applicable.append(module)

    if not isinstance(caps, dict):
        caps = {}
    known_modules = {"linux_diagnosis", "tool_recovery", "multi_turn",
                     "multidocument", "coding", "document_synthesis", "family_a"}
    unknown = sorted(set(caps) - known_modules)
    if unknown:
        findings.error("B_capability_unknown_module", f"unknown capability module(s): {unknown}")

    lane_coverage = (setup_doc or {}).get("lane_coverage") or {}
    rendered = rendered_records(root, setup_doc, findings)
    module_results = {}
    coverage_gaps = []

    for module in sorted(set(applicable) | set(caps)):
        runs = caps.get(module)
        if module == "family_a":
            continue  # covered by the context phase
        if not isinstance(runs, list) or not runs:
            if module in applicable:
                coverage_gaps.append(module)
                findings.error("B_capability_coverage_gap",
                               f"applicable module {module!r} has no run evidence; missing or "
                               "unrun fixtures are a coverage gap, never NOT_APPLICABLE")
            continue
        if module == "linux_diagnosis":
            fixture = _fixture_json(FIXTURE_LINUX, findings, "B_capability_fixture")
            expected_cases = {c["case_id"] for c in fixture["cases"]}
            observed_cases = {r.get("case_id") for r in runs if isinstance(r, dict)
                              and isinstance(r.get("case_id"), str)}
            if observed_cases != expected_cases:
                coverage_gaps.append(module)
                findings.error("B_capability_coverage_gap",
                               "linux_diagnosis requires every frozen case")
        results = []
        for index, run in enumerate(runs):
            label = f"capabilities.{module}[{index}]"
            results.append(_score_capability_run(
                root, module, run, index, label, setup_doc, lane_coverage, rendered,
                findings))
        module_results[module] = results

    module_pass = {}
    review_required = False
    for module, results in module_results.items():
        passed = bool(results)
        for state in results:
            if not state["mechanical_pass"]:
                passed = False
            if state["review"] is not None:
                if state["review"]["unresolved"]:
                    review_required = True
                    passed = False
                elif not state["review"]["pass"]:
                    passed = False
            elif module in QUALITATIVE_MODULES:
                review_required = True
                passed = False
        module_pass[module] = passed
    for module in applicable:
        if module == "family_a":
            ctx = (evidence.get("context") or {})
            if not isinstance(ctx.get("plan"), dict):
                coverage_gaps.append("family_a")
                findings.error("B_capability_coverage_gap",
                               "applicable module 'family_a' requires context phase evidence")
        elif module not in module_pass:
            coverage_gaps.append(module)
    return {"module_results": module_results, "module_pass": module_pass,
            "applicable_modules": applicable, "coverage_gaps": coverage_gaps,
            "review_required": review_required}


def _score_capability_run(root: Path, module, run, index, label, setup_doc,
                          lane_coverage, rendered, findings):
    """Score one capability run mechanically + collect its review state."""
    state = {"label": label, "mechanical_pass": False, "review": None, "module": module}
    fixture_by_module = {
        "linux_diagnosis": FIXTURE_LINUX,
        "tool_recovery": FIXTURE_TOOL_RECOVERY,
        "multi_turn": FIXTURE_MULTI_TURN,
        "multidocument": FIXTURE_MULTIDOCUMENT,
        "coding": FIXTURE_REPO_CODING,
        "document_synthesis": FIXTURE_DOC_SYNTHESIS,
    }
    fixture_user = None
    fixture_ref = fixture_by_module.get(module)
    if fixture_ref:
        fixture = _fixture_json(fixture_ref, findings, "B_capability_fixture")
        if module == "linux_diagnosis":
            case = _score_linux_run(run, findings, fixture)
            fixture_user = (case or {}).get("prompt")
        elif module in ("tool_recovery", "coding"):
            fixture_user = fixture.get("user_task")
        elif module == "multi_turn":
            for turn in reversed(fixture.get("turns") or []):
                if turn.get("role") == "user":
                    fixture_user = turn.get("content")
                    break
        elif module in ("multidocument", "document_synthesis"):
            prompt = _last_user_content(run.get("messages"))
            required = ((fixture.get("construction") or {}).get("question_block")
                        or fixture.get("user_task"))
            if not isinstance(prompt, str) or not required or required not in prompt:
                findings.error("B_row_user_task_mismatch",
                               f"{label}: frozen document task must occur in outgoing prompt")
            for document in fixture.get("documents") or []:
                if not isinstance(prompt, str) or document["text"] not in prompt \
                        or f"[document: {document['id']}]" not in prompt:
                    findings.error("B_row_user_task_mismatch",
                                   f"{label}: supplied document bytes and IDs required")
    _check_request_identity(_lane_request_identity(setup_doc), run,
                            label=label, findings=findings)
    class_id, _ = _class_of_task(setup_doc, run.get("id"))
    budget_lane = run.get("budget_lane")
    ceiling = (_semantic_ceiling(setup_doc, class_id) if budget_lane == "semantic"
               else _operational_cap(setup_doc, "DEPLOYMENT")
               if budget_lane == "operational" else None)
    if ceiling is None:
        findings.error("B_row_max_tokens",
                       f"{label}: declared budget lane and frozen calibrated cap required")
    bind_generation_row(run, fixture_task_user=fixture_user, setup_doc=setup_doc,
                        lane_coverage=lane_coverage, rendered=rendered,
                        lane_ceiling=ceiling, cap_tokens=None, label=label, findings=findings)
    content = _run_content(root, run, findings, "B_capability_run_content", label)
    semantic = None
    execution_ok = True
    if content is None:
        return state
    if module == "coding":
        execution_ok = _coding_execution_evidence(root, run, findings, label)
    if module == "linux_diagnosis":
        case_id = run.get("case_id")
        if isinstance(case_id, str) and _json_content(content, label, findings) is not None:
            result = CAP.score_linux_diagnosis(case_id, content)
            semantic = result.get("semantic")
            for failure in result.get("failures") or []:
                findings.info("B_capability_mechanical_failure", f"{label}: {failure}")
    elif module == "tool_recovery":
        transcript = run.get("transcript")
        if isinstance(transcript, dict):
            transcript = _read_frozen_json(root, transcript, findings,
                                           "B_capability_run_content", f"{label}.transcript")
        if isinstance(transcript, list) and transcript:
            result = CAP.score_tool_recovery(transcript)
            semantic = result.get("semantic")
            if not any(isinstance(event, dict) and event.get("final") == content
                       for event in transcript):
                findings.error("B_capability_run_content",
                               f"{label}: retained final answer differs from the tool transcript")
            for failure in result.get("failures") or []:
                findings.info("B_capability_mechanical_failure", f"{label}: {failure}")
        else:
            findings.error("B_capability_run_content",
                           f"{label}: tool-recovery transcript event list required")
    elif module == "multi_turn":
        messages = run.get("messages") or []
        assistant_turns = [m for m in messages
                           if isinstance(m, dict) and m.get("role") == "assistant"]
        if not assistant_turns or not any(
                isinstance(m.get("content"), str) and m["content"].strip()
                for m in assistant_turns):
            findings.error("B_capability_run_content",
                           f"{label}: multi-turn run must retain the actual earlier "
                           "assistant turn, not only the final answer")
        result = CAP.score_multi_turn_final(content)
        semantic = result.get("semantic")
        for failure in result.get("failures") or []:
            findings.info("B_capability_mechanical_failure", f"{label}: {failure}")
    elif module == "multidocument":
        if _json_content(content, label, findings) is not None:
            result = CAP.score_multidocument(content)
            semantic = result.get("semantic")
            for failure in result.get("failures") or []:
                findings.info("B_capability_mechanical_failure", f"{label}: {failure}")
    elif module in QUALITATIVE_MODULES:
        semantic = "PASS" if content.strip() else "NOT_EVALUABLE"
    else:
        findings.error("B_capability_unknown_module", f"{label}: no scorer for module {module!r}")
        return state
    state["mechanical_pass"] = semantic == "PASS" and execution_ok
    if module in QUALITATIVE_MODULES:
        state["review"] = (_capability_review_target(root, run, content, findings, label)
                           if content.strip() else
                           {"complete": True, "pass": False, "unresolved": False,
                            "disposition": "NOT_EVALUABLE"})
        if state["review"]["unresolved"]:
            findings.warn("B_role_review_unresolved",
                          f"{label}: {state['review'].get('reason', 'review unresolved')}")
    return state


def collect_qualitative_reviews(evidence, findings):
    """Adjudicate declared qualitative review records (separate from lane safety)."""
    section = (evidence or {}).get("qualitative_review")
    unresolved = []
    declared = section.get("reviews") if isinstance(section, dict) else None
    if declared:
        findings.warn("B_role_review_unresolved",
                      "top-level qualitative_review.reviews are not bound to any run; "
                      "attach role_reviews to the specific capability run they adjudicate")
        unresolved.append("unbound qualitative_review section")
    return {"unresolved": unresolved}


# --------------------------------------------------------------------------
# classification derivation + campaign semantics
# --------------------------------------------------------------------------
def derive_classification(gate, context, caps, evidence, man, findings,
                          oracle_pending=False):
    """Derive the classification from evidence; validate expected vs derived."""
    ctx_summary = (context or {}).get("summary") or {}
    integration = evidence.get("integration")
    if not isinstance(integration, dict) or integration.get("quality") not in (
            "CLEAN", "NOTES", "CONSTRAINTS", "BLOCKED"):
        findings.error("B_integration_missing",
                       "evidence.integration {quality: CLEAN|NOTES|CONSTRAINTS|BLOCKED} required")
        integration = {"quality": "NOTES"}
    coverage_gaps = caps.get("coverage_gaps") or []
    other_coverage_complete = not coverage_gaps
    qualitative_complete = not (caps.get("review_required")
                                or oracle_pending
                                or collect_qualitative_reviews(evidence, findings)["unresolved"])
    modules_pass = all(bool(v) for v in (caps.get("module_pass") or {}).values()) \
        if caps.get("module_pass") else False
    campaign_outcome = evidence.get("campaign_outcome")
    if campaign_outcome not in C.CAMPAIGN_OUTCOMES:
        # B_outcome_vocabulary is reported by evaluate_bundle; nothing to derive
        return None
    man_class = (man or {}).get("classification") or {}
    profile_id = man_class.get("profile_id")
    deployment = (((man or {}).get("deployment_lanes") or {}).get("prompt_lanes") or {}
                  ).get("DEPLOYMENT") or {}
    deployment_profile = deployment.get("profile_id")
    claimed_fabrication = evidence.get("replicated_fabrication")
    derived_fabrication = bool((gate or {}).get("replicated_fabrication_evidence"))
    if claimed_fabrication is not None and bool(claimed_fabrication) != derived_fabrication:
        findings.error("B_fabrication_assertion",
                       f"evidence.replicated_fabrication {claimed_fabrication!r} contradicts the "
                       f"independently derived value {derived_fabrication}; replicated "
                       "fabrication is derived from the raw paired lanes, never asserted, and "
                       "no verdict is invented for any retained failure mode")
    try:
        record = C.classify_evidence(
            gate, ctx_summary,
            campaign_outcome=campaign_outcome, integration=integration["quality"],
            applicable_modules_all_pass=modules_pass,
            profile_id=profile_id, dimension_profile_ids=man_class.get("dimension_profile_ids"),
            deployment_profile_id=deployment_profile,
            other_required_coverage_complete=other_coverage_complete,
            qualitative_review_complete=qualitative_complete)
    except Exception as exc:
        findings.error("B_classification_derivation",
                       f"{type(exc).__name__}: {exc}; asserted classification not accepted")
        return None
    if record.get("contract") != CLASSIFICATION_040:
        findings.error("B_classification_derivation",
                       f"classification contract must be {CLASSIFICATION_040!r}, "
                       f"got {record.get('contract')!r}")
    expected = evidence.get("expected_classification") or {}
    if expected and expected.get("readiness") != record.get("readiness"):
        findings.error("B_classification_mismatch",
                       f"expected readiness {expected.get('readiness')!r} but the derived "
                       f"classification is {record.get('readiness')!r}; the derived "
                       "classification governs")
    for source, claimed in (("evidence.expected_classification", expected),
                            ("manifest.classification", man_class)):
        dims = (claimed or {}).get("dimensions")
        if isinstance(dims, dict) and dims != record.get("dimensions"):
            findings.error("B_classification_mismatch",
                           f"{source} dimensions differ from the derived dimensions; "
                           "caller-asserted dimensions are not accepted")
            break
    return record


def campaign_semantics(result, findings):
    """Enforce COMPLETE_PASS preconditions; distinguish negative-complete from blocked."""
    evidence = result.get("evidence") or {}
    gate = result.get("gate")
    context = result.get("context") or {}
    summary = context.get("summary") or {}
    outcome = evidence.get("campaign_outcome")
    man = result.get("manifest") or {}
    if man.get("campaign_outcome") is not None and man.get("campaign_outcome") != outcome:
        findings.error("B_outcome_mismatch",
                       f"manifest.campaign_outcome {man.get('campaign_outcome')!r} != evidence "
                       f"campaign_outcome {outcome!r}")
    if outcome != "COMPLETE_PASS":
        return
    blockers = []
    if result.get("setup_errors"):
        blockers.append("invalid setup")
    if findings.errors:
        blockers.append("evidence load/validation errors")
    if result.get("oracle_review_pending"):
        blockers.append("unresolved oracle review")
    if gate is None:
        blockers.append("reliability gate not derivable")
    else:
        decision = gate.get("decision")
        if decision == "REVIEW_REQUIRED":
            blockers.append("unresolved review")
        elif decision == "PENDING_ADAPTIVE_SEED":
            blockers.append("required adaptive sampling not complete")
        elif decision not in ("ADVANCE", "DO_NOT_ADVANCE"):
            blockers.append(f"gate decision {decision!r}")
    if not summary.get("coverage_complete"):
        blockers.append("context coverage incomplete")
    if not summary.get("execution_valid"):
        blockers.append("context execution invalid")
    if (result.get("caps") or {}).get("coverage_gaps"):
        blockers.append("required capability coverage missing")
    record = result.get("classification")
    if record is not None and record.get("readiness") is None:
        blockers.append(f"no model verdict ({record.get('rule')})")
    if blockers:
        findings.error("B_complete_pass_rejected",
                       "COMPLETE_PASS rejected: " + "; ".join(blockers))


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def evaluate_bundle(root) -> dict:
    """Load, verify and derive everything from the bundle at campaign root."""
    root = Path(root)
    findings = Findings()
    man, evidence = load_evidence(root, findings)
    pending_review_targets = []
    if evidence is not None:
        if evidence.get("synthetic") is True:
            findings.info("B_synthetic_bundle",
                          "explicitly SYNTHETIC self-test evidence; never campaign evidence")
        if not isinstance(evidence.get("campaign_id"), str) or not evidence["campaign_id"]:
            findings.error("B_campaign_id_missing", "evidence.campaign_id required")
        outcome = evidence.get("campaign_outcome")
        if outcome not in C.CAMPAIGN_OUTCOMES:
            findings.error("B_outcome_vocabulary",
                           f"campaign_outcome {outcome!r} must be one of "
                           f"{sorted(C.CAMPAIGN_OUTCOMES)}")
        if isinstance(man, dict):
            if not man.get("campaign_id"):
                findings.error("B_campaign_id_mismatch",
                               "manifest.campaign_id required for a hardening-evidence bundle")
            elif evidence.get("campaign_id") is not None and \
                    man["campaign_id"] != evidence["campaign_id"]:
                findings.error("B_campaign_id_mismatch",
                               "evidence.campaign_id does not match the manifest campaign_id")
            if man.get("campaign_outcome") != evidence.get("campaign_outcome"):
                findings.error("B_outcome_mismatch",
                               f"manifest.campaign_outcome {man.get('campaign_outcome')!r} != "
                               f"evidence campaign_outcome {evidence.get('campaign_outcome')!r}")
        setup_doc = load_setup(root, evidence, findings)
        gate, _outcomes = derive_reliability(root, evidence, setup_doc, findings)
        context, pending_review_targets = derive_context(root, evidence, setup_doc, findings)
        caps = derive_capabilities(root, evidence, setup_doc, findings)
        classification = derive_classification(gate, context, caps, evidence, man, findings,
                                               oracle_pending=bool(pending_review_targets))
    else:
        setup_doc, gate, context, caps, classification = None, None, None, None, None
    result = {
        "module": MODULE_ID, "contract": CONTRACT,
        "valid": not findings.errors,
        "findings": findings.sorted(),
        "campaign_outcome": (evidence or {}).get("campaign_outcome")
        if isinstance(evidence, dict) else None,
        "setup_errors": [f[2] for f in findings.items if f[1] == "B_setup_blocker"],
        "oracle_review_pending": pending_review_targets,
        "evidence": evidence if isinstance(evidence, dict) else None,
        "manifest": man if isinstance(man, dict) else None,
        "gate": gate, "context": context, "caps": caps, "classification": classification,
    }
    campaign_semantics(result, findings)
    result["valid"] = not findings.errors
    result["findings"] = findings.sorted()
    return result


# --------------------------------------------------------------------------
# deterministic compact Markdown report
# --------------------------------------------------------------------------
def render_report(result: dict) -> str:
    """Deterministic compact Markdown report from the derived state only."""
    evidence = result.get("evidence") or {}
    classification = result.get("classification") or {}
    gate = result.get("gate") or {}
    ctx = (result.get("context") or {}).get("summary") or {}
    lines = []
    lines.append("# WELP hardening evidence bundle report")
    lines.append("")
    lines.append(f"- Contract: {result.get('contract')}")
    lines.append(f"- Campaign: {evidence.get('campaign_id', 'unknown')}")
    lines.append(f"- Campaign outcome: {result.get('campaign_outcome')}")
    if evidence.get("synthetic") is True:
        lines.append("- Evidence: **SYNTHETIC self-test bundle — never campaign evidence**")
    lines.append(f"- Bundle valid: {'yes' if result.get('valid') else 'NO'}")
    lines.append("")
    lines.append("## Derived reliability gate")
    lines.append("")
    if gate:
        lines.append(f"- Decision: {gate.get('decision')}")
        lines.append(f"- Executed seeds: {gate.get('executed_seeds')} "
                     f"(adaptive required: {gate.get('adaptive_extension_required')})")
        checks = gate.get("checks") or {}
        lines.append("- Checks: " + ", ".join(f"{k}={'PASS' if v else 'FAIL'}"
                                              for k, v in sorted(checks.items())))
        for seed, values in sorted((gate.get("per_seed") or {}).items(), key=lambda kv: str(kv[0])):
            lines.append(f"- Seed {seed}: semantic rate {values.get('rate')}, "
                         f"completion {values.get('completion_rate')}, "
                         f"unsafe={values.get('unsafe')}, "
                         f"review_required={values.get('review_required')}")
        lines.append(f"- Review required: {gate.get('review_required')}, "
                     f"independent review complete: {gate.get('independent_review_complete')}")
    else:
        lines.append("- Not derivable from raw evidence")
    lines.append("")
    lines.append("## Derived useful context")
    lines.append("")
    if ctx:
        lines.append(f"- Capability: {ctx.get('capability')}")
        lines.append(f"- Coverage complete: {ctx.get('coverage_complete')}, "
                     f"execution valid: {ctx.get('execution_valid')}")
        lines.append(f"- Practical rung validated: {ctx.get('practical_rung_validated')}")
        lines.append(f"- Useful context max: {ctx.get('useful_context_max')}")
        lines.append(f"- Missing cells: {len(ctx.get('missing_cells') or [])}")
        lines.append(f"- Oracle review pending: "
                     f"{len(result.get('oracle_review_pending') or [])}")
    else:
        lines.append("- Not derivable from raw evidence")
    lines.append("")
    lines.append("## Derived classification")
    lines.append("")
    if classification:
        dims = classification.get("dimensions") or {}
        lines.append(f"- Readiness: {classification.get('readiness')} "
                     f"(rule {classification.get('rule')})")
        if classification.get("note"):
            lines.append(f"- Note: {classification['note']}")
        for name in sorted(dims):
            lines.append(f"- {name}: {dims[name]}")
        for note in classification.get("guardrails") or []:
            lines.append(f"- Guardrail: {note}")
    else:
        lines.append("- No model verdict derivable from the evidence")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if result.get("findings"):
        for severity, code, detail in result["findings"]:
            lines.append(f"- {severity.upper()}: {code}: {detail}" if detail
                         else f"- {severity.upper()}: {code}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("_Derived from raw evidence by "
                 f"{MODULE_ID}; report prose is not scientific proof._")
    return "\n".join(lines)


def make_synthetic_bundle(root, variant="positive", mutate=None):
    """Build explicitly synthetic integration evidence, never model evidence."""
    from synthetic_bundle import make_synthetic_bundle as build
    return build(root, variant, mutate=mutate)


def _adjudication_selftest_failures(temp_root: Path) -> list:
    """Frozen adjudication-rule regressions (welp-review-adjudication-0.1.0-draft).

    Exercises the shared blinded adjudication resolver and the capability
    review integration: agreement decides, a recorded 1-1 disagreement
    admits exactly one blinded tie-break (2-of-3), a RUBRIC_AMBIGUITY
    tie-break fails closed to human review, and malformed, unblinded,
    unbound, over-manned or post-agreement reviewer records are rejected.
    """
    failures = []
    root = temp_root
    rubric_rel = "evidence/rubrics/adjudication-selftest.json"
    rubric_sha = _sha256_bytes(json.dumps({
        "rubric_id": "welp-role-review/adjudication-selftest/1",
        "criteria": ["synthetic selftest rubric"]}).encode())
    (root / "evidence" / "rubrics").mkdir(parents=True, exist_ok=True)
    (root / rubric_rel).write_text(json.dumps({
        "rubric_id": "welp-role-review/adjudication-selftest/1",
        "criteria": ["synthetic selftest rubric"]}))
    content = "SYNTHETIC answer text for adjudication selftest."
    answer_sha = _sha256_bytes(content.encode())
    prompt_sha = _sha256_bytes(b"SYNTHETIC prompt")

    def review(rid, disposition, **over):
        record = {"evaluator": {"id": rid, "kind": "agent",
                                "independent_of_execution": True,
                                "model_identity_blinded": True},
                  "target_sha256": answer_sha,
                  "rubric": {"id": "welp-role-review/adjudication-selftest/1",
                             "path": rubric_rel, "sha256": rubric_sha},
                  "rationale": "Synthetic adjudication under the frozen rubric.",
                  "evidence": ["SYNTHETIC answer text"], "disposition": disposition}
        record.update(over)
        return record

    def resolve(reviews, **kwargs):
        return _resolve_blinded_adjudication(
            root, reviews, target_sha=kwargs.pop("target_sha", answer_sha),
            content=kwargs.pop("content", content),
            prompt_sha=kwargs.pop("prompt_sha", None),
            dispositions=kwargs.pop("dispositions", {"PASS", "FAIL", "NOT_EVALUABLE"}),
            deciding_tie_break_dispositions=kwargs.pop(
                "tie", {"PASS", "FAIL", RUBRIC_AMBIGUITY}))

    def expect(name, got, want):
        if got != want:
            failures.append({"case": name, "got": got, "want": want})

    expect("agree-pass", resolve([review("a", "PASS"), review("b", "PASS")]),
           {"state": "resolved", "disposition": "PASS"})
    expect("agree-fail", resolve([review("a", "FAIL"), review("b", "FAIL")]),
           {"state": "resolved", "disposition": "FAIL"})
    got = resolve([review("a", "PASS"), review("b", "FAIL")])
    if got["state"] != "unresolved" or "tie-break" not in got["reason"]:
        failures.append({"case": "disagreement-no-tie", "got": got})
    expect("tie-pass", resolve([review("a", "PASS"), review("b", "FAIL"),
                                review("t", "PASS", role=TIE_BREAK_ROLE,
                                        previous_reviews_visible=False)]),
           {"state": "resolved", "disposition": "PASS"})
    expect("tie-fail", resolve([review("a", "PASS"), review("b", "FAIL"),
                                review("t", "FAIL", role=TIE_BREAK_ROLE,
                                        previous_reviews_visible=False)]),
           {"state": "resolved", "disposition": "FAIL"})
    got = resolve([review("a", "PASS"), review("b", "FAIL"),
                   review("t", RUBRIC_AMBIGUITY, role=TIE_BREAK_ROLE,
                          previous_reviews_visible=False)])
    if got.get("state") != "unresolved" or not got.get("rubric_ambiguity") \
            or "HUMAN_REVIEW_REQUIRED" not in got.get("reason", ""):
        failures.append({"case": "tie-rubric-ambiguity", "got": got})
    for name, tie_over in (
            ("tie-malformed-no-visibility", {}),
            ("tie-sees-previous-reviews", {"previous_reviews_visible": True}),
            ("tie-unbound-target", {"target_sha256": "0" * 64}),
            ("tie-invalid-disposition", {"disposition": "NOT_EVALUABLE"})):
        tie = review("t", "PASS", role=TIE_BREAK_ROLE)
        tie.update(tie_over)
        got = resolve([review("a", "PASS"), review("b", "FAIL"), tie])
        if got["state"] != "problems":
            failures.append({"case": name, "got": got})
    got = resolve([review("a", "PASS"), review("b", "FAIL"),
                   review("t1", "PASS", role=TIE_BREAK_ROLE,
                          previous_reviews_visible=False),
                   review("t2", "FAIL", role=TIE_BREAK_ROLE,
                          previous_reviews_visible=False)])
    if got["state"] != "problems":
        failures.append({"case": "fourth-reviewer-rejected", "got": got})
    got = resolve([review("a", "PASS"), review("b", "PASS"),
                   review("t", "FAIL", role=TIE_BREAK_ROLE,
                          previous_reviews_visible=False)])
    if got["state"] != "problems" or "without a recorded" not in ";".join(got["problems"]):
        failures.append({"case": "tie-after-agreement-rejected", "got": got})
    got = resolve([review("a", "PASS"), review("b", "FAIL"),
                   review("c", "NOT_EVALUABLE")])
    if got["state"] != "unresolved" or "no tie-break slot" not in got["reason"]:
        failures.append({"case": "three-way-disagreement-no-slot", "got": got})
    # oracle dispositions: prompt-bound reviews under VALIDATED/FAILED
    def oracle_review(rid, disposition, **over):
        return review(rid, disposition, prompt_sha256=prompt_sha, **over)

    expect("oracle-agree", resolve(
        [oracle_review("a", "VALIDATED"), oracle_review("b", "VALIDATED")],
        prompt_sha=prompt_sha, dispositions=ORACLE_REVIEW_DISPOSITIONS,
        tie=ORACLE_REVIEW_DISPOSITIONS | {RUBRIC_AMBIGUITY}),
        {"state": "resolved", "disposition": "VALIDATED"})
    expect("oracle-tie-break", resolve(
        [oracle_review("a", "VALIDATED"), oracle_review("b", "FAILED"),
         oracle_review("t", "FAILED", role=TIE_BREAK_ROLE,
                       previous_reviews_visible=False)],
        prompt_sha=prompt_sha, dispositions=ORACLE_REVIEW_DISPOSITIONS,
        tie=ORACLE_REVIEW_DISPOSITIONS | {RUBRIC_AMBIGUITY}),
        {"state": "resolved", "disposition": "FAILED"})
    got = resolve([oracle_review("a", RUBRIC_AMBIGUITY), oracle_review("b", "VALIDATED")],
                  dispositions=ORACLE_REVIEW_DISPOSITIONS,
                  tie=ORACLE_REVIEW_DISPOSITIONS | {RUBRIC_AMBIGUITY})
    if got["state"] != "problems":
        failures.append({"case": "base-reviewer-ambiguity-rejected", "got": got})
    # capability review integration: disagreement + tie-break completes the run
    findings = Findings()
    run = {"role_reviews": [review("a", "PASS"), review("b", "FAIL"),
                            review("t", "PASS", role=TIE_BREAK_ROLE,
                                   previous_reviews_visible=False)]}
    state = _capability_review_target(root, run, content, findings, "selftest.docsyn[0]")
    if state.get("complete") is not True or state.get("pass") is not True \
            or findings.errors:
        failures.append({"case": "capability-integration-tie-resolves",
                         "state": state, "errors": findings.errors})
    findings = Findings()
    run = {"role_reviews": [review("a", "PASS"), review("b", "FAIL"),
                            review("t", RUBRIC_AMBIGUITY, role=TIE_BREAK_ROLE,
                                   previous_reviews_visible=False)]}
    state = _capability_review_target(root, run, content, findings, "selftest.docsyn[0]")
    if state.get("unresolved") is not True or not state.get("rubric_ambiguity") \
            or "RUBRIC_AMBIGUITY" not in (state.get("reason") or ""):
        failures.append({"case": "capability-integration-ambiguity",
                         "state": state})
    return failures


def _rewrite_hardening_evidence(root: Path, mutate_fn):
    """Selftest helper: rewrite the frozen hardening evidence with mutate_fn
    applied and re-pin its sha256 in the campaign manifest."""
    import synthetic_bundle as SB
    ev_path = root / SB.EVIDENCE_REF
    evidence = json.loads(ev_path.read_text())
    mutate_fn(evidence)
    data = SB._freeze_bytes(evidence)
    ev_path.write_bytes(data)
    man_path = root / "summaries/campaign_manifest.json"
    man = json.loads(man_path.read_text())
    man["hardening_evidence"]["sha256"] = hashlib.sha256(data).hexdigest()
    man_path.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")


def _budget_limited_selftest_failures(temp_root: Path) -> list:
    """Granite D-01 integration regressions (welp-context 0.3.0-draft).

    The context-budget-limited synthetic campaign carries one execution-valid
    answerless reasoning-exhaustion cell with all other required evidence
    valid: the bundle must stay structurally valid and COMPLETE_PASS with
    complete coverage, the practical rung correctly unvalidated, and a
    freshly derived classification. Mutated evidence proves invalid
    empty-answer records fail closed.
    """
    import shutil
    failures = []
    root = make_synthetic_bundle(temp_root / "context-budget-limited",
                                 "context-budget-limited")
    result = evaluate_bundle(root)
    summary = ((result.get("context") or {}).get("summary") or {})
    record = result.get("classification") or {}
    if not result.get("valid") or result.get("campaign_outcome") != "COMPLETE_PASS":
        failures.append({"case": "budget-limited-valid",
                         "findings": result.get("findings")})
    if not (summary.get("coverage_complete") and summary.get("capability") == "PARTIAL"
            and summary.get("practical_rung_validated") is False
            and summary.get("covered_cells") == summary.get("required_cells")):
        failures.append({"case": "budget-limited-summary", "summary": summary})
    if record.get("readiness") != "READY_WITH_GUARDRAILS" or \
            "context capability PARTIAL, separate from coverage" not in (
                record.get("guardrails") or []):
        failures.append({"case": "budget-limited-classification", "record": record})
    if render_report(result) != render_report(evaluate_bundle(root)):
        failures.append({"case": "budget-limited-report-nondeterministic"})

    def first_cell(evidence):
        return evidence["context"]["rows"][0]

    mutations = (
        ("missing-terminal-state",
         lambda ev: first_cell(ev).update(
             raw={"answer": "", "usage": {}}),
         "B_context_missing_raw"),
        ("asserted-validated-empty-answer",
         lambda ev: first_cell(ev).update(disposition="VALIDATED"),
         "B_context_missing_raw"),
        ("unbound-empty-evidence",
         lambda ev: first_cell(ev).update(
             evidence="synthetic family-a raw answer (unbound)"),
         "B_context_missing_raw"),
        ("abnormal-stop-empty-answer",
         lambda ev: first_cell(ev).update(
             raw={"answer": "", "finish": "error",
                  "usage": {"completion_tokens": 512, "reasoning_tokens": None}}),
         "B_context_missing_raw"),
        ("normal-terminal-empty-answer-stays-measured",
         lambda ev: first_cell(ev).update(
             raw={"answer": "", "finish": "stop",
                  "usage": {"completion_tokens": 89, "reasoning_tokens": None}}),
         None),
    )
    for name, mutate_fn, want_code in mutations:
        mutated_root = temp_root / f"mutation-{name}"
        shutil.copytree(root, mutated_root)
        _rewrite_hardening_evidence(mutated_root, mutate_fn)
        mutated = evaluate_bundle(mutated_root)
        codes = {code for _sev, code, _detail in mutated.get("findings") or []}
        if want_code is None:
            if not mutated.get("valid"):
                failures.append({"case": name, "findings": mutated.get("findings")})
        elif mutated.get("valid") or want_code not in codes:
            failures.append({"case": name, "valid": mutated.get("valid"),
                             "codes": sorted(codes)})
    return failures


def selftest():
    import tempfile
    failures = []
    with tempfile.TemporaryDirectory() as td:
        for variant in ("positive", "complete-negative", "context-budget-limited",
                        "review-blocked", "incomplete", "execution-error"):
            root = make_synthetic_bundle(Path(td) / variant, variant)
            result = evaluate_bundle(root)
            expected_valid = variant in ("positive", "complete-negative",
                                         "context-budget-limited")
            if result["valid"] != expected_valid:
                failures.append({"variant": variant, "findings": result["findings"]})
            if variant == "positive" and (result.get("classification") or {}).get(
                    "readiness") != "READY":
                failures.append({"variant": variant, "classification": result["classification"]})
            if variant == "complete-negative" and (result.get("classification") or {}).get(
                    "readiness") != "NOT_READY":
                failures.append({"variant": variant, "classification": result["classification"]})
            report = render_report(result)
            if report != render_report(evaluate_bundle(root)):
                failures.append({"variant": variant, "error": "nondeterministic report"})
        failures.extend(_adjudication_selftest_failures(Path(td) / "adjudication"))
        failures.extend(_budget_limited_selftest_failures(Path(td) / "budget-limited"))
    print(json.dumps({"pass": not failures, "failures": failures}, indent=2))
    return int(bool(failures))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "render", "synthetic", "selftest"))
    parser.add_argument("root", nargs="?")
    parser.add_argument("variant", nargs="?", default="positive",
                        choices=("positive", "complete-negative",
                                 "context-budget-limited", "review-blocked",
                                 "incomplete", "execution-error"))
    args = parser.parse_args(argv)
    if args.command == "selftest":
        return selftest()
    if not args.root:
        parser.error("campaign root required")
    if args.command == "synthetic":
        print(make_synthetic_bundle(args.root, args.variant))
        return 0
    result = evaluate_bundle(args.root)
    if args.command == "render":
        print(render_report(result))
    else:
        print(json.dumps({key: result[key] for key in
                          ("valid", "findings", "campaign_outcome", "classification",
                           "setup_errors", "oracle_review_pending")}, indent=2))
    return int(not result["valid"])


if __name__ == "__main__":
    sys.exit(main())
