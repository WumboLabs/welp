# Lab Record Template (per model campaign) — WELP

```
lab-records/<model-slug>/welp-<YYYY-MM-DD>/
├── README.md            # human entry point (= report.md summary)
├── report.md            # full Standard Completion Package report
├── WELP-CONFORMANCE.md  # human-readable conformance record (canonical for WELP campaigns)
├── manifest.json        # welp_campaign_manifest.schema.json instance
├── SHA256SUMS           # artifact index hashes
├── environment/         # environment.json, runtime identity, driver/CUDA
├── protocol/            # snapshot id + note hashes used
├── commands/            # exact launch/run commands
├── results/             # raw jsonl (public-eligible)
├── summaries/           # all machine-readable summaries incl artifact_index, publication_status, welp_conformance.json
├── telemetry/           # gpu/journal samples
├── omp/                 # omp evidence if applicable (system-level)
├── localmaxxing/        # submission payloads/responses (redacted)
└── reproduction/        # step-by-step instructions
```

No model binaries ever. Public/private eligibility per artifact_index entries.

## Compatibility note

The directory name `welp-<YYYY-MM-DD>/` is the WELP-canonical convention. Historical campaigns continue to use `wlep-<YYYY-MM-DD>/` and their filesystem path is provenance — do NOT rename those directories.
