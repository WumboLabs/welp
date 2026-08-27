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
| `WELP-CONFORMANCE.md` | New WELP campaigns (canonical). |
| `summaries/welp_conformance.json` | New WELP campaigns (canonical). |
| `lab-records/<model-slug>/welp-<YYYY-MM-DD>/` | New WELP campaigns. |
| `manifest.json` validated against `welp_campaign_manifest.schema.json` | New WELP campaigns. |

Do not rename frozen campaign directories or frozen evidence filenames. Exact historical paths are provenance.

The canonical new-campaign validator is `validators/validate_campaign_welp.py`. It accepts frozen historical campaign artifacts where needed.
