# Lab Record Template (WELP)

> Artifact role: WELP LAB RECORD (template)
> Campaign: `<campaign slug>`
> Status: CURRENT COMPANION
> Primary scientific report: `REPORT.md`

A published campaign record references external raw evidence; it never embeds model binaries.

## Filename and role

Instantiate this template as **`WELP-LAB-RECORD.md`** in the campaign bundle
(not `report.md`). This record is a structured companion to the primary
scientific report `REPORT.md`: it summarizes/indexes the same campaign and does
NOT replace it. `REPORT.md` is authoritative; if the two disagree, `REPORT.md`
governs and the discrepancy is reconciled from retained raw evidence. See the
[report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy).

Required sections:
1. Model identity (repo/revision/file/sha256)
2. Runtime + hardware identity
3. Requested vs effective serving profile (+ delta, including explicit `gate_baseline_reasoning_state`)
4. WELP snapshot identity (manifest hash; for new campaigns, snapshot_id begins with `welp-next-snapshot-`)
5. Contract/scorer identities + scorer self-test result
6. Phase results and gate decisions
7. Stop reason
8. Execution counts incl. invalidated runs
9. LocalMaxxing status — the standardized disposition below
10. WELP conformance (`WELP-CONFORMANCE.md` + `summaries/welp_conformance.json`) and protocol findings
11. Limitations
12. Artifact index (machine-readable)
13. Reproduction instructions
14. Supported deployment roles (only where evidence permits)
15. Model-card context coverage table below, including all untested/partial ranges and exact native/official extension maxima
16. Separate practical-profile/baseline decision and model-card context-completeness gate

## LocalMaxxing disposition

Mandatory for every model campaign, including early stops. Exactly one status;
values and rules per [WELP](../protocol/WELP.md#localmaxxing-completion-disposition).

| Field | Value |
|---|---|
| Eligibility | eligible / not eligible (+ one-line representation finding) |
| Status | `SUBMITTED` / `MEASURED_NOT_SUBMITTED` / `NOT_ELIGIBLE` / `BLOCKED` |
| Canonical profile | artifact (hf id/revision/sha256) · quant/precision · engine + runtime version · configured context · KV dtype · speculation/MTP · geometry · hardware |
| Benchmark prompt | prompt identity/source + ACTUAL prompt tokens (never a nominal value alone) |
| Result summary | tok/s out (and prefill/TTFT/VRAM where produced), repetitions policy |
| Submission origin | `NEW` / `VERIFIED_EXISTING` / none |
| Submission reference | submission id / URL, date |
| verifiedRun state | as returned by the service (never fabricated) |
| Reason / blocker | required unless `SUBMITTED` |

Raw payloads, responses, and per-repetition data live under the campaign's
`localmaxxing/` evidence directory; this section summarizes, never replaces,
them.

## Model-card context coverage

Mandatory for every campaign, including an early stop before Context. Follow
[WELP Context Scaling](../protocol/context-scaling.md); freeze the method
revision/hash and pinned official card/config/extension sources. Include one row
per major rung per surface and separate exact-maximum rows. Record a documented
absence of official extension support rather than inventing an extension row.

| Surface | Card claim (source/revision; native or extension maximum) | Runtime configuration (requested/effective mechanism) | Configured capacity (tokens) | Capacity admitted? | Usable prompt budget (tokens) | Actual occupied tokens (final rendered input) | Occupancy % | Reserved output tokens / safety allowance | Near-full performance run? | Useful-context run? | Seeds / inference requests / target-field-depth observations | Final disposition | Evidence path / notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Native: exact maximum (replace with pinned claim) | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | NOT_TESTED | Record source and outstanding work; no validation implied. |

Duplicate the row for each planned rung/official extension maximum; replace
planning values with evidence, never invented numbers. Link per-run rows where
seeds or workloads differ rather than averaging away occupancy or failures.
Expose all five context-claim quantities: capacity, usable budget, actual
rendered input tokens, occupancy, and output reserve. Near-full means >=97% of
usable budget (>=99% preferred) after real template/tokenization; report any
pre-frozen bounded exception explicitly, not as a standard VALIDATED pass.

Every major admitted rung requires near-full performance: TTFT, prefill
throughput/proxy, decode throughput, E2E, post-load/minimum-free VRAM, power and
temperature where safely available, and CUDA/OOM/Xid/runtime errors. Link
availability limitations and exact measurement boundaries. Useful-context
evidence must itself be near-full, with measured 2/25/50/75/95 depths and
placement errors, per-seed results, and distinct request/observation counts.

Dispositions: `VALIDATED`, `FIT_LIMIT`, `INTEGRATION_BLOCKED`, measured `FAILED`,
`PARTIAL`, or `NOT_TESTED`, under the method's evidence rules. Fit/integration
limits are completed scientific dispositions, not model-quality FAIL. `PARTIAL`
or `NOT_TESTED` at any required rung/native/official extension maximum prevents
**MODEL-CARD CONTEXT ENVELOPE COMPLETE / CONTEXT CHARACTERIZATION COMPLETE**.
Report **PRACTICAL PROFILE SELECTED / PRACTICAL BASELINE CHARACTERIZED** separately;
a sensible default does not terminate full-envelope characterization.

## Filename conventions

| Convention | When to use |
|---|---|
| `REPORT.md` | New WELP campaigns: the primary scientific report (exactly one per current bundle; authoritative). |
| `WELP-LAB-RECORD.md` | New WELP campaigns: this template, instantiated as the standardized companion record. |
| `<campaign-slug>-review-report.md` | When requested: optional human review summary under `~/Projects/local-llm/tmp/` (noncanonical; links to `REPORT.md` + `WELP-LAB-RECORD.md`). |
| `WELP-CONFORMANCE.md` | New WELP campaigns (canonical). |
| `summaries/welp_conformance.json` | New WELP campaigns (canonical). |
| `lab-records/<model-slug>/welp-<YYYY-MM-DD>/` | New WELP campaigns. |
| `manifest.json` validated against `welp_campaign_manifest.schema.json` | New WELP campaigns. |
| `report.md` | Historical bundles only. Do not use in new campaigns; never alongside `REPORT.md`. |

Do not rename frozen campaign directories or frozen evidence filenames. Exact historical paths are provenance.

The canonical new-campaign validator is `validators/validate_campaign_welp.py`. It accepts frozen historical campaign artifacts where needed.
