#!/usr/bin/env python3
"""Validate an allowlist-selected first-release public tree.

The validator never exports files. It evaluates only paths selected by the
candidate's publication-allowlist.json; all other local workspace material is
out of scope by design and defaults to DO_NOT_PUBLISH.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import tempfile
from pathlib import Path

MAX_DEFAULT = 5 * 1024 * 1024
SECRET_PATTERNS = {
    "openai_style": re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    "openrouter_style": re.compile(r"\bsk-or-[A-Za-z0-9_-]{8,}"),
    "github_classic": re.compile(r"\bghp_[A-Za-z0-9]{8,}"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"),
    "huggingface": re.compile(r"\bhf_[A-Za-z0-9]{8,}"),
    "localmaxxing": re.compile(r"\bbhk_[A-Za-z0-9_-]{8,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{8,}"),
    "private_key": re.compile(r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    "credential_assignment": re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|bearer)\s*[:=]\s*[^\s\"']{8,}"),
}
HOME_PATH = re.compile(r"(?:^|[\"'\s(])/(?:home|Users)/[^/\s]+/")
PRIVATE_IP = re.compile(r"\b(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)\d{1,3}\.\d{1,3}")
URL_CREDENTIAL = re.compile(r"(?:https?|ssh)://[^/\s:@]+:[^@/\s]+@|https?://[^\s?#]+\?(?:[^\s#]*&)?(?:token|api[_-]?key|key|authorization)=[^&#\s]+", re.I)
BINARY_SUFFIXES = {".gguf", ".safetensors", ".bin", ".pt", ".pth", ".onnx", ".sqlite", ".db", ".zip", ".tar", ".gz", ".xz", ".zst"}
FORBIDDEN_SEGMENTS = {"sources", "runtime", "logs", "local", "models", "telemetry", "cache", "caches"}


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def selected(root: Path, spec: dict) -> list[Path]:
    allowed, excluded = spec["allowed"], spec.get("excluded", [])
    return [p for p in sorted(root.rglob("*")) if (p.is_file() or p.is_symlink())
            and matches(p.relative_to(root).as_posix(), allowed)
            and not matches(p.relative_to(root).as_posix(), excluded)]


def text_of(path: Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_DEFAULT:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def validate(root: Path) -> dict:
    root = root.resolve()
    result = {"root": str(root), "status": "PASS", "selected_files": 0, "errors": [], "findings": []}
    allow_path, manifest_path = root / "publication-allowlist.json", root / "PUBLICATION-MANIFEST.json"
    if not allow_path.is_file(): result["errors"].append("missing publication-allowlist.json"); return fail(result)
    if not manifest_path.is_file(): result["errors"].append("missing PUBLICATION-MANIFEST.json"); return fail(result)
    try:
        spec, manifest = json.loads(allow_path.read_text()), json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        result["errors"].append(f"malformed publication metadata: {exc.msg}"); return fail(result)
    if spec.get("default") != "DO_NOT_PUBLISH" or spec.get("policy") != "ALLOWLIST_FIRST":
        result["errors"].append("allowlist does not enforce ALLOWLIST_FIRST / DO_NOT_PUBLISH default")
    required = ["README.md", "PUBLICATION-MANIFEST.json", "publication-allowlist.json", ".gitignore"]
    if root.name not in {"welp", "labs"}: required += ["MODEL.md", "model-manifest.json", "PUBLICATION-POLICY.md", "publication-policy.json"]
    for name in required:
        if not (root / name).is_file(): result["errors"].append(f"missing required file: {name}")
    files = selected(root, spec); result["selected_files"] = len(files)
    max_size = int(manifest.get("large_file_review_threshold_bytes", MAX_DEFAULT))
    for path in files:
        rel = path.relative_to(root).as_posix()
        if "sources" in Path(rel).parts:
            result["errors"].append(f"sources included by allowlist: {rel}")
        if path.is_symlink():
            result["errors"].append(f"selected symlink: {rel}")
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            result["errors"].append(f"forbidden binary/archive suffix: {rel}")
        if path.stat().st_size > max_size:
            result["errors"].append(f"large-file review required: {rel}")
        if path.suffix == ".json":
            try: json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError): result["errors"].append(f"malformed JSON: {rel}")
        text = text_of(path)
        if text is None: continue
        for category, pattern in SECRET_PATTERNS.items():
            if pattern.search(text): result["errors"].append(f"secret-like {category}: {rel}")
        if HOME_PATH.search(text): result["errors"].append(f"absolute home path: {rel}")
        if PRIVATE_IP.search(text): result["findings"].append(f"private-IP review: {rel}")
        if URL_CREDENTIAL.search(text): result["errors"].append(f"credential-bearing URL: {rel}")
    return fail(result)


def fail(result: dict) -> dict:
    if result["errors"]: result["status"] = "FAIL"
    return result


def write_fixture(root: Path, payload: str = "ok") -> None:
    root.mkdir(parents=True, exist_ok=True)
    spec = {"policy":"ALLOWLIST_FIRST","default":"DO_NOT_PUBLISH","allowed":["README.md","MODEL.md","model-manifest.json","PUBLICATION-POLICY.md","publication-policy.json","PUBLICATION-MANIFEST.json","publication-allowlist.json",".gitignore","public/**"],"excluded":["sources/**","models/**"]}
    manifest = {"large_file_review_threshold_bytes":1024}
    for name in ["README.md","MODEL.md","PUBLICATION-POLICY.md",".gitignore"]: (root/name).write_text(payload)
    for name, value in [("model-manifest.json",{}),("publication-policy.json",{}),("PUBLICATION-MANIFEST.json",manifest),("publication-allowlist.json",spec)]: (root/name).write_text(json.dumps(value))
    (root/"public").mkdir(); (root/"public"/"x.txt").write_text(payload)


def selftest() -> int:
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        good = base/"GOOD_PUBLIC_TREE"; write_fixture(good); cases.append(("GOOD_PUBLIC_TREE", validate(good)["status"] == "PASS"))
        protocol = base / "welp"
        write_fixture(protocol)
        for name in ("MODEL.md", "model-manifest.json", "PUBLICATION-POLICY.md",
                     "publication-policy.json"):
            (protocol / name).unlink()
        previous = Path.cwd()
        try:
            os.chdir(protocol)
            cases.append(("RELATIVE_PROTOCOL_ROOT", validate(Path("."))["status"] == "PASS"))
        finally:
            os.chdir(previous)
        secret = base/"SECRET_PRESENT"; write_fixture(secret, "api" + "_key=not-a-real-secret-12345678"); cases.append(("SECRET_PRESENT", validate(secret)["status"] == "FAIL"))
        binary = base/"MODEL_BINARY_PRESENT"; write_fixture(binary); (binary/"public/model.gguf").write_bytes(b"x"); cases.append(("MODEL_BINARY_PRESENT", validate(binary)["status"] == "FAIL"))
        link = base/"EXTERNAL_SYMLINK"; write_fixture(link); (link/"public/link").symlink_to("/tmp"); cases.append(("EXTERNAL_SYMLINK", validate(link)["status"] == "FAIL"))
        source = base/"SOURCES_INCLUDED"; write_fixture(source); spec=json.loads((source/"publication-allowlist.json").read_text()); spec["allowed"].append("sources/**"); spec["excluded"].remove("sources/**"); (source/"publication-allowlist.json").write_text(json.dumps(spec)); (source/"sources").mkdir(); (source/"sources/x.txt").write_text("x"); cases.append(("SOURCES_INCLUDED", validate(source)["status"] == "FAIL"))
        home = base/"ABSOLUTE_HOME_PATH"; write_fixture(home, "/home/" + "operator/private"); cases.append(("ABSOLUTE_HOME_PATH", validate(home)["status"] == "FAIL"))
        large = base/"UNKNOWN_LARGE_FILE"; write_fixture(large); (large/"public/large.txt").write_bytes(b"x"*1025); cases.append(("UNKNOWN_LARGE_FILE", validate(large)["status"] == "FAIL"))
    print(json.dumps({"status":"PASS" if all(ok for _,ok in cases) else "FAIL","fixtures":[{"name":n,"expected": "PASS" if n in {"GOOD_PUBLIC_TREE", "RELATIVE_PROTOCOL_ROOT"} else "FAIL","passed":ok} for n,ok in cases]}, indent=2))
    return 0 if all(ok for _,ok in cases) else 1


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("command", choices=["validate","selftest"]); parser.add_argument("root", nargs="?")
    args=parser.parse_args()
    if args.command == "selftest": return selftest()
    if not args.root: parser.error("validate requires ROOT")
    output=validate(Path(args.root)); print(json.dumps(output,indent=2)); return 0 if output["status"]=="PASS" else 1
if __name__ == "__main__": raise SystemExit(main())
