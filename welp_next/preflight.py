"""Scientific protocol admission, not host attestation.

The operating agent supplies model provenance and deployment conditions and owns
transport, GPU admission, monitoring and cleanup. WELP checks the scientific
configuration and current model-facing API. No subprocess, GPU or remote host
inspection occurs here. Historical observations remain verifiable in policy.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from . import policy
from .policy import CheckError, validate_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
GET_TIMEOUT_SECONDS = 10.0
MAX_BODY_BYTES = 1 << 20
USER_AGENT = f"{policy.FRAMEWORK} preflight"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_profile(path):
    try:
        profile = json.loads(Path(path).read_bytes())
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise CheckError(f"profile: cannot read JSON {path}: {exc}") from exc
    validate_profile(profile)
    return profile


def _check(name, status, detail):
    return {"name": name, "status": status, "detail": detail, "timestamp": _now()}


def _fail_closed(evidence):
    failures = [c["name"] for c in evidence["checks"] if c["status"] == "FAIL"]
    evidence["ok"] = False
    exc = CheckError("preflight failed closed: " + ", ".join(failures), field=failures[0])
    exc.checks, exc.evidence = evidence["checks"], evidence
    raise exc


def offline(profile):
    validate_profile(profile)
    root = Path(profile["campaign_root"]).resolve()
    if profile["evidence_kind"] == "REAL_MODEL":
        expected = (WORKSPACE_ROOT / "research/model-evaluations" /
                    profile["model"]["model_key"] / "campaign-groups" / profile["campaign_id"])
        routed = root == expected.resolve()
    else:
        routed = root.is_relative_to((PROJECT_ROOT / "tmp").resolve()) and root != (PROJECT_ROOT / "tmp").resolve()
    parent = root
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    usable = parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
    evidence = {"ok": True, "stage": "offline", "timestamp": _now(),
        "admission_version": policy.ADMISSION_VERSION,
        "profile_id": profile["profile_id"], "campaign_id": profile["campaign_id"],
        "model_key": profile["model"]["model_key"], "evidence_kind": profile["evidence_kind"],
        "framework": profile["framework"]["version"], "methodology": profile["framework"]["methodology"],
        "profile_revision": policy.digest(profile),
        "model_science_eligible": profile["evidence_kind"] == "REAL_MODEL",
        "contact": {"endpoint": False, "gpu": False},
        "checks": [_check("profile.schema", "PASS", {"scientific_configuration": policy.scientific_configuration(profile)}),
                   _check("campaign.routing", "PASS" if routed and usable else "FAIL", {"campaign_root": str(root), "writable": usable})],
        "supplied_conditions": {key: profile[key] for key in ("model", "runtime", "hardware", "deployment", "qualification", "environment") if key in profile},
        "provenance_authority": "operating agent; not independently rehashed or machine-attested by WELP"}
    if not routed or not usable:
        _fail_closed(evidence)
    return evidence


class _HttpFailure(Exception):
    def __init__(self, name, detail):
        super().__init__(name)
        self.name, self.detail = name, detail


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_request(request, timeout):
    """No redirects or environment proxies for the configured private origin."""
    return urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect).open(request, timeout=timeout)


def _http_get_json(url, data=None):
    req = urlrequest.Request(url, data=data, headers={"Accept": "application/json",
        "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with open_request(req, GET_TIMEOUT_SECONDS) as response:
            status = response.status
            raw = response.read(MAX_BODY_BYTES + 1)
    except urlerror.HTTPError as exc:
        raise _HttpFailure("endpoint.http", {"url": url, "status": exc.code}) from exc
    except (urlerror.URLError, OSError, TimeoutError) as exc:
        raise _HttpFailure("endpoint.unreachable", {"url": url, "error": str(exc)}) from exc
    if len(raw) > MAX_BODY_BYTES:
        raise _HttpFailure("endpoint.body_too_large", {"url": url})
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _HttpFailure("endpoint.body", {"url": url, "error": str(exc)}) from exc
    if not isinstance(parsed, dict):
        raise _HttpFailure("endpoint.body", {"url": url, "error": "JSON object required"})
    return status, parsed, hashlib.sha256(raw).hexdigest(), len(raw)


def online(profile):
    evidence = offline(profile)
    evidence["stage"] = "online"
    evidence["contact"]["endpoint"] = True
    base = profile["runtime"]["serve"]["endpoint"].rstrip("/")
    observed = {}
    def metadata(path, payload=None):
        status, body, sha, size = _http_get_json(base + path, None if payload is None else policy.canonical(payload))
        observed[path] = {"status": status, "body": body, "raw_sha256": sha, "raw_bytes": size}
        return body
    try:
        models = metadata("/models")
        model_id = profile["runtime"]["serve"]["model_id"]
        ids = [row.get("id") for row in models.get("data", []) if isinstance(row, dict)]
        if model_id not in ids:
            raise _HttpFailure("endpoint.model", {"requested": model_id, "available": ids})
        raw = metadata(profile["runtime"]["serve"]["echo_path"])
        echo = {"admission_version": policy.ADMISSION_VERSION}
        if profile["runtime"]["engine"]["name"] == "llama.cpp":
            probe = {"messages": [{"role": "user", "content": "WELP preflight template rendering only."}],
                     **profile["reasoning"]["controls"]}
            rendered = metadata("/apply-template", probe)
            tokens = metadata("/tokenize", {"content": rendered.get("prompt"), "add_special": True, "parse_special": True})
            echo.update(props=raw, template_probe={"request": probe, "response": rendered}, tokenizer_probe=tokens)
        else:
            echo["configuration"] = raw
        evidence["echo"] = echo
        defects = policy.protocol_defects(profile, echo)
        evidence["checks"].append(_check("serve.protocol", "FAIL" if defects else "PASS", {"defects": defects}))
    except _HttpFailure as exc:
        evidence["checks"].append(_check(exc.name, "FAIL", exc.detail))
    evidence["admission"] = {"endpoint": base, "observations": observed, "timestamp": _now()}
    if any(c["status"] == "FAIL" for c in evidence["checks"]):
        _fail_closed(evidence)
    return evidence
