#!/usr/bin/env python3
"""Fail unapproved noncanonical protocol identifiers in current-facing WELP material.

current-facing: README/docs/examples/templates/protocol must not contain the
historical token unless listed in welp-legacy-exceptions.json (they should not be).

full: every tracked hit must map to an explicit exception.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TOKEN_RE = re.compile(r"wlep", re.I)
ALLOWED_CLASS = {"FROZEN_PROVENANCE_KEEP", "FUNCTIONAL_COMPATIBILITY_KEEP"}
CURRENT_FACING_GLOBS = [
    "README.md",
    "docs/**",
    "examples/**",
    "lab-record-template/**",
    "protocol/**",
]


def load_exceptions(repo: Path) -> dict[str, dict]:
    path = repo / "validators" / "welp-legacy-exceptions.json"
    spec = json.loads(path.read_text())
    out = {}
    for item in spec["exceptions"]:
        rel = item["path"]
        if item["classification"] not in ALLOWED_CLASS:
            raise SystemExit(f"invalid classification for {rel}")
        out[rel] = item
    return out


def git_tracked(repo: Path) -> list[str]:
    import subprocess
    r = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [p for p in r.stdout.decode().split("\0") if p]


def match_glob(rel: str, pattern: str) -> bool:
    from fnmatch import fnmatchcase
    return fnmatchcase(rel, pattern) or fnmatchcase(Path(rel).name, pattern)


def current_facing_paths(tracked: list[str]) -> list[str]:
    return [p for p in tracked if any(match_glob(p, g) for g in CURRENT_FACING_GLOBS)]


def hits_in_file(repo: Path, rel: str) -> list[dict]:
    path = repo / rel
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    found = []
    for i, line in enumerate(text.splitlines(), 1):
        if TOKEN_RE.search(line):
            found.append({"path": rel, "line": i, "text": line.strip()[:200]})
    if TOKEN_RE.search(Path(rel).name):
        found.append({"path": rel, "line": 0, "text": f"filename:{Path(rel).name}"})
    return found


def scan(repo: Path, mode: str) -> dict:
    exceptions = load_exceptions(repo)
    tracked = git_tracked(repo)
    scope = current_facing_paths(tracked) if mode == "current-facing" else tracked
    unapproved = []
    approved = []
    unknown = []
    for rel in scope:
        found = hits_in_file(repo, rel)
        if not found:
            continue
        exc = exceptions.get(rel)
        if mode == "current-facing":
            if exc:
                approved.extend({**h, **exc} for h in found)
            else:
                unapproved.extend(found)
            continue
        if not exc:
            unknown.extend(found)
        else:
            approved.extend({**h, **exc} for h in found)
    status = "PASS"
    if mode == "current-facing" and unapproved:
        status = "FAIL"
    if mode == "full" and unknown:
        status = "FAIL"
    return {
        "mode": mode,
        "status": status,
        "unapproved": unapproved,
        "approved": approved,
        "unknown": unknown,
        "current_facing_files": len(scope) if mode == "current-facing" else None,
    }


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


def selftest() -> int:
    cases = []

    def run_case(name, files, exceptions, mode, expect):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_tree(root, files)
            (root / "validators").mkdir(exist_ok=True)
            (root / "validators" / "welp-legacy-exceptions.json").write_text(
                json.dumps({"version": "1.0", "exceptions": exceptions})
            )
            import subprocess
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "t"],
                cwd=root,
                check=True,
            )
            result = scan(root, mode)
            ok = result["status"] == expect
            cases.append((name, ok, result["status"]))
            if not ok:
                print(json.dumps({"case": name, "expected": expect, "got": result}, indent=2))

    run_case(
        "PASS_CURRENT_WELP_ONLY",
        {"README.md": "# WELP\nCanonical protocol.\n", "docs/a.md": "WELP only\n"},
        [],
        "current-facing",
        "PASS",
    )
    run_case(
        "PASS_APPROVED_FROZEN_IDENTIFIER",
        {"snapshot-freeze/manifest.json": '{"id": "wlep-next-snapshot-2026-08-25-end-to-end"}\n'},
        [{"path": "snapshot-freeze/manifest.json", "classification": "FROZEN_PROVENANCE_KEEP", "reason": "frozen id"}],
        "full",
        "PASS",
    )
    run_case(
        "PASS_FUNCTIONAL_COMPATIBILITY",
        {"validators/validate_campaign_welp.py": "SNAPSHOT_RE = r'(welp|wlep)'\n"},
        [{"path": "validators/validate_campaign_welp.py", "classification": "FUNCTIONAL_COMPATIBILITY_KEEP", "reason": "compat"}],
        "full",
        "PASS",
    )
    run_case(
        "FAIL_NEW_WLEP_PROSE",
        {"README.md": "This campaign used WLEP.\n"},
        [],
        "current-facing",
        "FAIL",
    )
    run_case(
        "FAIL_NEW_WLEP_FILENAME_OR_ID",
        {"docs/wlep-guide.md": "guide\n"},
        [],
        "current-facing",
        "FAIL",
    )

    print(json.dumps({"selftest": [{"name": n, "ok": ok, "status": s} for n, ok, s in cases]}, indent=2))
    return 0 if all(ok for _, ok, _ in cases) else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["current-facing", "full", "selftest"])
    p.add_argument("--root", default=".")
    args = p.parse_args()
    if args.command == "selftest":
        return selftest()
    repo = Path(args.root).resolve()
    result = scan(repo, args.command)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
