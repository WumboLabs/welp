# WELP examples

Example artifacts for new WELP campaigns.

- `good_current_welp/` — minimal new WELP campaign (`WELP-CONFORMANCE.md`, `welp-next-snapshot-*`, `welp-preflight`, `welp-` contract IDs) accepted by `validate_campaign_welp.py`.
- `good_welp_with_legacy_evidence/` — WELP campaign that still validates against frozen historical evidence paths. Accepted.
- `bad_unknown_prefix/` — campaign with a noncanonical protocol prefix; rejected.
- `bad_rewritten_legacy/` — current-looking manifest whose evidence still points only at frozen historical contracts; rejected.

Frozen historical campaign fixtures are produced by the validator self-test when needed. They are not templates for new work.

```bash
python3 validators/validate_campaign_welp.py selftest
```
