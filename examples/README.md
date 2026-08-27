# WELP examples

Example artifacts for new WELP campaigns. Historical WLEP example artifacts are preserved in their original locations under `wlep-development/`.

- `good_legacy_wlep/` — minimal legacy WLEP campaign (manifest + toolchain preflight + runtime capabilities + invalidated run reason + WLEP-CONFORMANCE.md) accepted by `validate_campaign_welp.py`. Mirrors the validator's `_good_legacy_wlep` fixture.
- `good_current_welp/` — minimal new WELP campaign (WELP-CONFORMANCE.md, welp-next-snapshot-2026-08-26-post-rename, welp-preflight const, welp- contract IDs) accepted by `validate_campaign_welp.py`. Mirrors the validator's `_good_current_welp` fixture.
- `good_welp_with_legacy_evidence/` — WELP campaign whose manifest references welp_*.schema.json (legacy-compatible) validation paths. Mirrors the validator's `_welp_using_legacy_evidence` fixture.
- `bad_unknown_prefix/` — campaign with a wxyz-* prefix; rejected by the validator.
- `bad_rewritten_legacy/` — silently-rewritten WLEP→WELP manifest referencing only wlep-* contracts; rejected.

These examples are produced live by the validator's `selftest` command in a `tempfile.TemporaryDirectory`. Operators can reproduce them with:

```bash
python3 validators/validate_campaign_welp.py selftest
```
