# Lab Record Template (per model campaign) — WELP

```
lab-records/<model-slug>/welp-<YYYY-MM-DD>/
├── REPORT.md            # PRIMARY SCIENTIFIC REPORT (authoritative source of truth)
├── WELP-LAB-RECORD.md   # standardized WELP Lab Record (structured companion; this template)
├── README.md            # human entry point (links REPORT.md + WELP-LAB-RECORD.md)
├── WELP-CONFORMANCE.md  # human-readable conformance record (canonical for WELP campaigns)
├── manifest.json        # welp_campaign_manifest.schema.json instance
├── SHA256SUMS           # artifact index hashes
├── environment/         # environment.json, runtime identity, driver/CUDA
├── protocol/            # snapshot id + note hashes used
├── commands/            # exact launch/run commands
├── results/             # raw jsonl (public-eligible)
├── summaries/           # all machine-readable summaries incl artifact_index, publication_status, welp_conformance.json
├── agentic/             # WELP Agentic section evidence when applicable: task records, transcripts, result JSONs (per welp-agentic-0.1.0-draft; also record sections.model / sections.agentic dispositions in the manifest)
├── telemetry/           # gpu/journal samples
├── omp/                 # omp evidence if applicable (system-level)
├── localmaxxing/        # submission payloads/responses (redacted)
└── reproduction/        # step-by-step instructions
```

No model binaries ever. Public/private eligibility per artifact_index entries.

Historical bundles may instead contain a single `report.md` (the former full
Standard Completion Package report). That is frozen evidence of the earlier
convention: leave it byte-identical, and never combine `report.md` with
`REPORT.md` in a current bundle. A superseded prior execution lives only under
an unmistakable sibling path (preferred suffix `-prior-attempt-quarantined/`).
See the [report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy).

## Frozen campaign directories

Do not rename frozen campaign directories. Exact historical paths are provenance.
