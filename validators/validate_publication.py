#!/usr/bin/env python3
"""Validate current publication identity/citations without rewriting legacy exports.

Usage: validate_publication.py FILE... | selftest
Full structural schemas remain in schemas/. This stdlib validator enforces
cross-field citation and profile-path invariants not expressible there.
"""
import copy
import json
from pathlib import Path
import re
import sys

REPO = "WumboLabs/evaluations"
ID = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
SHA = re.compile(r"^[0-9a-f]{40}$")
PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


def evidence_errors(document):
    errors = []
    evidence = document.get("canonical_evidence", {})
    if not isinstance(evidence, dict):
        return ["canonical_evidence must be an object"]
    current = evidence.get("repo") == REPO or evidence.get("proposed_repo") == REPO or "path" in evidence
    state = evidence.get("state")
    if state not in ("PUBLISHED", "PENDING_HUMAN_GATE"):
        errors.append("invalid canonical evidence state")
    if state == "PENDING_HUMAN_GATE":
        if evidence.get("url") or "commit" in evidence or "path" in evidence:
            errors.append("pending evidence cannot claim a published citation")
    elif state == "PUBLISHED":
        if current:
            if evidence.get("repo") != REPO:
                errors.append("current evidence repo must be WumboLabs/evaluations")
            if not SHA.fullmatch(str(evidence.get("commit", ""))):
                errors.append("current evidence needs a full 40-character commit SHA")
            path = evidence.get("path", "")
            if not isinstance(path, str) or not PATH.fullmatch(path):
                errors.append("current evidence needs a safe relative path")
            expected = f"https://github.com/{REPO}/blob/{evidence.get('commit')}/{path}"
            if evidence.get("url") not in (None, expected):
                errors.append("canonical URL disagrees with immutable repo/commit/path")
        elif not evidence.get("url"):
            errors.append("legacy published evidence requires its original URL")
    identity = document.get("identity")
    if current and not isinstance(identity, dict):
        errors.append("current publication requires scientific identity")
    if identity is not None:
        if not isinstance(identity, dict):
            return errors + ["identity must be an object"]
        for key in ("model_id", "profile_id", "event_id"):
            if not ID.fullmatch(str(identity.get(key, ""))):
                errors.append(f"invalid or missing identity.{key}")
        if not isinstance(identity.get("event_type"), str) or not identity["event_type"].strip():
            errors.append("identity.event_type is required")
        shared = identity.get("shared_event_id")
        related = identity.get("related_model_ids")
        if shared is not None or related is not None:
            if not ID.fullmatch(str(shared)):
                errors.append("shared event requires shared_event_id")
            if not isinstance(related, list) or len(related) < 2 or any(not isinstance(x, str) or not ID.fullmatch(x) for x in related) or len(related) != len(set(related)):
                errors.append("shared event requires at least two distinct model IDs")
            elif identity.get("model_id") not in related:
                errors.append("display attribution must be among related models")
        related_profiles = identity.get("related_profile_ids")
        if related_profiles is not None and (not isinstance(related_profiles, list) or not related_profiles or any(not isinstance(x, str) or not ID.fullmatch(x) for x in related_profiles) or len(related_profiles) != len(set(related_profiles))):
            errors.append("related profile IDs must be non-empty and unique")
    return errors


def profile_errors(document):
    errors = []
    for key in ("model_id", "profile_id"):
        if not ID.fullmatch(str(document.get(key, ""))):
            errors.append(f"invalid or missing {key}")
    for key in ("model_display_name", "profile_display_name", "runtime_family", "artifact", "repository", "current_status"):
        if not isinstance(document.get(key), str) or not document[key].strip():
            errors.append(f"missing {key}")
    if document.get("schema") == "wumbolabs-eval-profile/2":
        if document.get("repository") != REPO:
            errors.append("current profile repository must be WumboLabs/evaluations")
        expected = f"models/{document.get('model_id')}/profiles/{document.get('profile_id')}"
        if document.get("profile_path") != expected:
            errors.append("profile_path disagrees with model/profile identity")
        events = document.get("event_ids")
        if not isinstance(events, list) or any(not isinstance(x, str) or not ID.fullmatch(x) for x in events) or len(events) != len(set(events)):
            errors.append("event_ids must contain unique event IDs")
    elif document.get("schema") == "wumbolabs-eval-profile/1":
        if not document.get("first_event"):
            errors.append("legacy first_event is required")
    else:
        errors.append("unknown profile schema")
    return errors


def selftest():
    current = {"canonical_evidence": {"state": "PUBLISHED", "repo": REPO, "commit": "a" * 40, "path": "models/example/events/run/REPORT.md"}, "identity": {"model_id": "example", "profile_id": "example-q4", "event_id": "run", "event_type": "initial-evaluation"}}
    cases = [("current immutable citation", current, True), ("historical URL without identity", {"canonical_evidence": {"state": "PUBLISHED", "url": "https://github.com/WumboLabs/eval-example"}}, True)]
    for label, key, value in [("short SHA", "commit", "aaaaaaa"), ("branch instead of SHA", "commit", "main"), ("wrong repo", "repo", "WumboLabs/eval-example"), ("absolute path", "path", "/REPORT.md"), ("traversal", "path", "models/../REPORT.md"), ("encoded traversal", "path", "models/%2e%2e/REPORT.md"), ("URL mismatch", "url", "https://example.com")]:
        item = copy.deepcopy(current)
        item["canonical_evidence"][key] = value
        cases.append((label, item, False))
    missing = copy.deepcopy(current)
    del missing["identity"]
    cases.append(("missing identity", missing, False))
    shared = copy.deepcopy(current)
    shared["identity"].update(shared_event_id="comparison", related_model_ids=["example", "other"])
    cases.append(("shared comparison", shared, True))
    duplicate = copy.deepcopy(shared)
    duplicate["identity"]["related_model_ids"] = ["example", "example"]
    cases.append(("duplicate related model", duplicate, False))
    pending = copy.deepcopy(current)
    pending["canonical_evidence"]["state"] = "PENDING_HUMAN_GATE"
    cases.append(("pending published citation", pending, False))
    pending_current = {"canonical_evidence": {"state": "PENDING_HUMAN_GATE", "proposed_repo": REPO}, "identity": current["identity"]}
    cases.append(("pending current identity", pending_current, True))
    pending_missing = copy.deepcopy(pending_current)
    del pending_missing["identity"]
    cases.append(("pending current missing identity", pending_missing, False))
    cases.append(("historical pending without identity", {"canonical_evidence": {"state": "PENDING_HUMAN_GATE", "proposed_repo": "WumboLabs/eval-example"}}, True))
    results = [{"case": name, "pass": (not evidence_errors(item)) == valid} for name, item, valid in cases]
    print(json.dumps({"pass": all(x["pass"] for x in results), "cases": results}, indent=2))
    return 0 if all(x["pass"] for x in results) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    results = []
    for name in sys.argv[1:]:
        item = json.loads(Path(name).read_text())
        errors = profile_errors(item) if item.get("schema", "").startswith("wumbolabs-eval-profile/") else evidence_errors(item)
        results.append({"file": name, "errors": errors})
    print(json.dumps(results, indent=2))
    sys.exit(1 if not results or any(x["errors"] for x in results) else 0)
