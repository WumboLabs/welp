"""Evaluator-only acceptance for agentic-research-1-atlas9-batching (trusted).

Mechanical oracle. Extracted from
welp/fixtures/agentic/research/evaluator/extra_checks.py (adaptation: the
answer artifact is read through the core's symlink-refusing
read_workspace_text; see tmp/m3-advancement-agentic/agentic-provenance.json).

Correct resolution (frozen at fixture creation, before any model output): the
governing source is ops-bulletin-7, whose 96-message consumer batch limit
supersedes the manuals; ops-bulletin-5 was a withdrawn draft. Citations
resolve under the word-boundary rule (a cited reference is valid when it is
the frozen id, or an unambiguous word-boundary extension or truncation of
exactly one frozen id). Ambiguity is never guessed.
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from welp_next import agentic  # noqa: E402  (trusted core import, setup only)

FROZEN_IDS = ["changelog", "faq", "glossary", "governance", "manual-v1",
              "manual-v2", "manual-v3", "ops-bulletin-5", "ops-bulletin-7",
              "quickstart"]
EXPECTED_VALUE = 96
GOVERNING = "ops-bulletin-7"
SUPERSEDED_REQUIRED = {"manual-v3", "manual-v2"}


def _resolve(token, frozen=FROZEN_IDS):
    """Word-boundary citation resolution; ambiguity fails closed."""
    if token in frozen:
        return token
    hits = []
    for fid in frozen:
        if fid.startswith(token) and not fid[len(token):len(token) + 1].isalnum():
            hits.append(fid)  # token is an unambiguous truncation
        elif token.startswith(fid) and not token[len(fid):len(fid) + 1].isalnum():
            hits.append(fid)  # unambiguous extension
    return hits[0] if len(hits) == 1 else None


def _split_ids(value):
    return [t.strip().lower() for t in re.split(r"[,\s]+", value.strip()) if t.strip()]


def extra_checks(record, transcript, workspace, fixture):
    checks = []
    ws = Path(workspace)
    try:
        text = agentic.read_workspace_text(ws, "research-pack/answer.md")
    except OSError:
        return {"checks": [{"id": "acceptance", "pass": False,
                            "detail": "research-pack/answer.md missing"}],
                "acceptance_pass": False}

    m = re.search(r"maximum\s+recommended\s+consumer\s+batch\s+size\s*:\s*(\d+)\s+messages",
                  text, re.I)
    checks.append({"id": "value_correct", "pass": bool(m and int(m.group(1)) == EXPECTED_VALUE),
                   "detail": f"value={m.group(1) if m else None}"})

    mg = re.search(r"governing\s+source\s*:\s*(.+)", text, re.I)
    gov_tok = _split_ids(mg.group(1))[0] if mg else ""
    gov_ok = _resolve(gov_tok.rstrip(".,")
                      ) == GOVERNING
    checks.append({"id": "governing_source_correct", "pass": gov_ok,
                   "detail": f"governing token={gov_tok!r}"})

    ms = re.search(r"superseded\s+on\s+this\s+point\s*:\s*(.+)", text, re.I)
    sup_tokens = [_resolve(t.rstrip(".,")) for t in _split_ids(ms.group(1))] if ms else []
    sup_resolved = {t for t in sup_tokens if t}
    sup_ok = (ms is not None and SUPERSEDED_REQUIRED <= sup_resolved
              and None not in sup_tokens)
    checks.append({"id": "superseded_list_correct", "pass": sup_ok,
                   "detail": f"resolved={sorted(sup_resolved)} raw={_split_ids(ms.group(1)) if ms else []}"})

    mu = re.search(r"sources\s+used\s*:\s*(.+)", text, re.I)
    used_tokens = [_resolve(t.rstrip(".,")) for t in _split_ids(mu.group(1))] if mu else []
    used_resolved = {t for t in used_tokens if t}
    used_ok = (mu is not None and GOVERNING in used_resolved
               and None not in used_tokens)
    checks.append({"id": "citations_resolve", "pass": used_ok,
                   "detail": f"resolved={sorted(used_resolved)}"})

    withdrawn_governing = gov_ok is False and bool(
        re.search(r"governing\s+source\s*:\s*.*ops-bulletin-5", text, re.I))
    checks.append({"id": "no_withdrawn_as_governing", "pass": not withdrawn_governing,
                   "detail": "ops-bulletin-5 cited as governing" if withdrawn_governing else "ok"})

    return {"checks": checks, "acceptance_pass": all(c["pass"] for c in checks)}
