# Lab Record Template (WELP)

A published campaign record references external raw evidence; it never embeds model binaries.

Required sections:
1. Model identity (repo/revision/file/sha256)
2. Runtime + hardware identity
3. Requested vs effective serving profile (+ delta, including explicit `gate_baseline_reasoning_state`)
4. WELP snapshot identity (manifest hash; for new campaigns, snapshot_id begins with `welp-next-snapshot-`)
5. Contract/scorer identities + scorer self-test result
6. Phase results and gate decisions
7. Stop reason
8. Execution counts incl. invalidated runs
9. LocalMaxxing status
10. WELP conformance (`WELP-CONFORMANCE.md` + `summaries/welp_conformance.json`) and protocol findings
11. Limitations
12. Artifact index (machine-readable)
13. Reproduction instructions
14. Supported deployment roles (only where evidence permits)

## Filename conventions

| Convention | When to use |
|---|---|
| `WELP-CONFORMANCE.md` | New WELP campaigns (canonical for fresh testing). |
| `WLEP-CONFORMANCE.md` | Legacy historical WLEP campaigns; preserved unchanged. |
| `summaries/welp_conformance.json` | New WELP campaigns (canonical). |
| `summaries/wlep_conformance.json` | Legacy historical WLEP campaigns. |
| `lab-records/<model-slug>/welp-<YYYY-MM-DD>/` | New WELP campaigns. |
| `lab-records/<model-slug>/wlep-<YYYY-MM-DD>/` | Historical WLEP campaigns; filesystem path is provenance, never renamed. |
| `manifest.json` validated against `welp_campaign_manifest.schema.json` | New WELP campaigns. |
| `manifest.json` validated against `wlep_campaign_manifest.schema.json` (legacy) | Historical WLEP campaigns. |

Both validators accept either filename; the WELP validator at `validators/validate_campaign_welp.py` is the canonical new-campaign validator.
