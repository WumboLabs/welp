# WELP / LocalMaxxing methodology review report

Artifact role: WELP development review report (noncanonical convenience companion)
Campaign: localmaxxing-integration
Status: CURRENT
Primary scientific report: n/a (methodology maintenance milestone; no model science in this bundle)
Date: 2026-09-10 (execution window extends to 2026-09-11 local)

## 1. Outcome

PASS — WELP_LOCALMAXXING_COMPLETION_STANDARD_ESTABLISHED. LocalMaxxing is now a
durable, validator-enforced completion step of every future WELP model campaign,
and the four recent canonical profiles were benchmarked and submitted in the
companion backfill campaign
(`research/engine-kernel/experiments/localmaxxing-backfill-2026-09-10/REPORT.md`).

## 2. Starting WELP state

- HEAD `62fc68f3a7e901e6e19fbcc05d1550d0b240cdc2` ("WELP: establish report artifact
  hierarchy"); previous `f6efc232d6550f6642dfafda85863e0cd78e40cf`; tracked source
  clean; untracked `tmp/` only. Verified before edits.
- Existing LocalMaxxing surface: campaign-start preflight auth status only
  (`publication.localmaxxing_auth_status`: READY | AUTH_BLOCKED | CLI_INCOMPATIBLE |
  NOT_APPLICABLE) in `schemas/welp_toolchain_preflight.schema.json`,
  `docs/reproduction.md` step 1, Lab Record section 9 ("LocalMaxxing status" —
  vocabulary undefined), and `welp_publication_status.schema.json` (free-form
  `localmaxxing.status`). No completion disposition, no canonical-profile rule,
  no prompt-token rule, no validator enforcement.

## 3. Current LocalMaxxing tooling identity

- `lmx v0.1.33` (`4a36be4871d0bf26960b2868e18771269df4dc8e`, built 2026-08-10,
  linux/amd64, static Go). PATH resolution: `/usr/local/sbin/lmx` (also
  `/usr/local/bin/lmx`, `~/.local/bin/lmx`).
- Source/package identity: upstream Go distribution tarball retained at
  `~/Projects/local-llm/localmaxxing/lmx-linux-amd64.tar.gz` (2026-07-04 install).
- Auth: existing saved CLI auth + `LOCALMAXXING_API_KEY` in the session
  environment; `lmx auth whoami` returned the expected account identity
  (READY). No key material printed, copied, rotated, or created.
- Full machine-readable contract frozen at
  `research/engine-kernel/experiments/localmaxxing-backfill-2026-09-10/provenance/lmx-context/`
  (27 sections) and `provenance/lmx-help-all-v0.1.33.txt`.

## 4. Current benchmark/submission contract

- Speed-test engines accepted (schema enum): llama.cpp, vllm, sglang, exllamav2,
  **exllamav3**, tensorrt-llm, mlx, ollama, lmstudio, and others.
- Required: `hfId`, `quantization`, `engineName`, hardware union, and at least
  `tokSOut`; optional `ttftMs`, `tokSPrefill`, `tokSTotal`, `peakVramGb`.
- Canonical prompts: `reasoning-v1` (330 approx tokens, sha256
  `9000edaadb16fc77ab78b39917245a03d4d7585c3ba770cb045a47a0e0683445`) and
  `code-v1` (260 approx tokens, sha256 `a737db73…a690`); `minOutputTokens` 256.
- `verifiedRun` server-side checks: promptSha256/promptSample match a canonical
  prompt (nonce-stripped), non-empty outputSample, engineTimingsRaw present,
  batchSize 1 + concurrency 1, outputTokens >= 256, spec/MTP acceptance stats
  when speculation is enabled, tokSOut <= physical ceiling x 1.15.
- Mechanism: `POST /api/speed-tests/dry-run` (no write) then `POST /api/speed-tests`
  (public submission); all traffic via the official `lmx` CLI (Cloudflare blocks
  direct HTTP). Repetition policy: CLI remote mode default 1 warmup + 3 timed
  iterations, median reported; this milestone used 2 warmup + 5 timed iterations.
- LIMITATION (verified): the v0.1.33 CLI binary contains no string for
  `promptSha256`/`outputSample`/`engineTimingsRaw` and `--canonical-prompt`
  does not exist (`unknown_option`), although the site agent-context documents
  them — the CLI lags the API. Consequence: submissions via the installed CLI
  cannot carry verified-run evidence and are stored `verifiedRun: false` with
  explicit `verificationIssues`. E4 precedent identical.

## 5. Historical prompt-token hazard verification

- STILL PRESENT in v0.1.33: `--prompt-tokens <n>` maps to `llama-bench -p` and
  is "submitted as promptTokens" (verbatim CLI help). A nominal value, not a
  measured count.
- VERIFIED safe alternative used here: remote-endpoint mode reports actual
  rendered prompt tokens from endpoint usage accounting
  (`tokenSources.prompt = "endpoint_usage"`). The backfill used this path for
  all four models: 266/266/252/266 actual tokens for the canonical
  `reasoning-v1` prompt across the four runtimes.

## 6. New LocalMaxxing statuses

`SUBMITTED` (origin NEW | VERIFIED_EXISTING + reference), `MEASURED_NOT_SUBMITTED`
(exact reason), `NOT_ELIGIBLE` (demonstrated representation limit; never
engine-swapped), `BLOCKED` (exact blocker). Deprecated as completion
dispositions for eligible campaigns: `NOT_APPLICABLE` / `NOT_AUTHORIZED`.
Preflight auth readiness vocabulary is unchanged and distinct; auth failure at
submission time is `BLOCKED`, not `NOT_ELIGIBLE`.

## 7. Canonical-profile rule

LocalMaxxing benchmarks the CANONICAL PRACTICAL PROFILE (artifact, quant,
engine/runtime, configured context, KV dtype, speculation/MTP, geometry,
hardware, power) — never an experimental context boundary (e.g. MiniCPM's
131K fp8-KV surface), never a convenient alternate engine, never a one-off
profile. Configured context and actual prompt tokens are always reported
separately.

## 8. Eligibility rule

Every WELP model campaign evaluates LocalMaxxing eligibility after the
canonical practical profile is selected; eligible campaigns run the current
official benchmark and submit during campaign completion when submission
access works. A campaign never silently omits LocalMaxxing, and model science
may remain PASS while the disposition is `MEASURED_NOT_SUBMITTED` or `BLOCKED`
with the unresolved status visible.

## 9. Duplicate-submission rule

Before any submission: search the local run store and any service-exposed
history for an exact existing record (artifact, quant, engine, key geometry,
hardware, context). Exact match -> `SUBMITTED` / `VERIFIED_EXISTING`, no
duplicate. Materially different record -> does not satisfy the disposition.
(Applied in the backfill: Qwen3.8's three E4-era APPROVED records describe the
H4-era wrapper and do not match the current H1 canonical; the eight 2026-09-08
diagnostic drafts were never submitted and were not submitted now.)

## 10. Authentication/external-action rule

Existing configured auth only; no new accounts, no key rotation, no printing
of key material. LocalMaxxing benchmark submission of the eligible canonical
profile is the explicitly authorized campaign-completion exception to generic
"no external submission" rules; it authorizes no other external action
(GitHub, X, other services remain human-gated).

## 11. WELP lifecycle delta

`docs/reproduction.md` operator checklist: new mandatory step 8 (LocalMaxxing
completion disposition) between context characterization and final
classification, matching the durable order: identity/provenance -> artifact
admission -> baseline -> capability/context/reliability -> practical canonical
profile -> LMX eligibility -> LMX benchmark -> LMX submission -> completion
package -> final classification. Step 11 (Standard Completion Package) now
includes `summaries/localmaxxing.json`; step 12 (publication routing) documents
the submission exception.

## 12. REPORT.md requirements (future campaigns)

Expose at minimum: LocalMaxxing eligibility; status (four canonical values);
benchmarked canonical profile; actual prompt tokens; result summary; submission
origin (NEW/VERIFIED_EXISTING); submission reference; exact blocker/reason when
not submitted.

## 13. WELP-LAB-RECORD.md requirements

`lab-record-template/README.md` section 9 expanded into a standardized
"LocalMaxxing disposition" section: eligibility, status, canonical profile
line, prompt identity + ACTUAL prompt tokens, result summary + repetition
policy, submission origin, submission reference/date, verifiedRun state as
returned by the service, and reason/blocker unless SUBMITTED. Raw payloads and
responses stay in the campaign's `localmaxxing/` evidence directory.

## 14. Reproduction/checklist delta

See section 11; the operator checklist is the reproduction surface. No other
checklist semantics changed; historical campaigns reproduce unchanged.

## 15. Validator delta

`validators/validate_campaign_welp.py`:
- New R05: `summaries/localmaxxing.json` REQUIRED (error) for new-format
  bundles whose campaign snapshot date >= 2026-09-10; expected (warning) in
  earlier bundles — frozen evidence remains valid unchanged.
- New R06: content validation — status exactly one of the four canonical
  values; SUBMITTED requires origin (NEW | VERIFIED_EXISTING) + submission_ref;
  MEASURED_NOT_SUBMITTED / NOT_ELIGIBLE / BLOCKED require reason.
- Selftest extended 8 -> 11 fixtures, all PASS (valid SUBMITTED bundle; missing
  disposition with post-integration snapshot -> error; deprecated
  `NOT_APPLICABLE` status -> error; pre-integration new-format bundle without
  the file -> valid with R05 warning).
- `docs/validator.md` updated (required files, disposition fields, R05/R06).
- `schemas/welp_publication_status.schema.json`: additive `disposition` object
  (status enum, origin, submission_ref, actual_prompt_tokens, reason) inside
  `localmaxxing`; existing fields untouched.

## 16. Historical compatibility

- Selftest: all 8 pre-existing fixtures still PASS unchanged; 3 added.
- Real bundles: `minicpm5-2b-rtx5070-welp-characterization-2026-09-10` and
  `minicpm5-2b-rtx5070-baseline-2026-09-09` were re-validated. Delta vs HEAD
  validator on these bundles is exactly one added R05 warning. NOTE (pre-existing,
  out of scope): both fail R02 (REPORT.md + report.md coexistence) identically
  under the HEAD validator — a consequence of the report-hierarchy commit that
  post-dates those bundles; not touched per campaign-immutability rules.

## 17. Engine-kernel AGENTS delta

One concise durable section "## LocalMaxxing disposition" added to
`research/engine-kernel/AGENTS.md` (disposition mandatory; canonical stack;
actual prompt tokens demonstrated; eligible submissions expected during
completion; no engine substitution; canonical WELP owns detailed rules). No
duplication of the WELP method.

## 18. HiveMind mirror delta

- `WumboLabs Evaluation Lifecycle Protocol (WELP).md`: new "LocalMaxxing
  completion disposition" section after the context-completeness gate.
- `LocalMaxxing Publication Workflow.md`: new "WELP completion disposition
  (2026-09-10)" block distinguishing completion statuses from per-submission
  lifecycle statuses.
- `Standard Completion Package.md`: required-artifact item 7 now names
  `summaries/localmaxxing.json` with the four statuses.
- No raw benchmark data copied into the vault; pre-existing unrelated Vault
  modifications preserved.

## 19. Exact changed files (this milestone, WELP repo)

- `protocol/WELP.md` (+ LocalMaxxing completion disposition section; validator
  line updated to 11 fixtures)
- `docs/reproduction.md` (checklist step 8 inserted; steps renumbered 9-12;
  completion package + publication routing amended)
- `lab-record-template/README.md` (section 9 + standardized disposition table)
- `docs/validator.md` (R05/R06, disposition fields, 11-fixture usage)
- `schemas/welp_publication_status.schema.json` (additive disposition object)
- `validators/validate_campaign_welp.py` (R05/R06 checks + 3 fixtures + selftest)
- `tmp/localmaxxing-integration/REPORT.md` (this file; untracked)

Outside WELP: `research/engine-kernel/AGENTS.md`; three HiveMind notes listed
in section 18; the new backfill bundle.

## 20. Validation

- `python3 validators/validate_campaign_welp.py selftest` -> 11 fixtures,
  pass: true, failures: [].
- Real-bundle re-validation (see section 16).
- `python3 validators/check_canonical_welp_naming.py current-facing` -> no
  unknown entries (11 current-facing files).
- `git diff --check` -> clean.
- JSON schema edited parse-verified (json.load + key/enum inspection).

## 21. Git state

WELP: all changes unstaged and uncommitted (human gate). No add/commit/push/
tag/release/merge/rebase. Committed history untouched. HiveMind: unstaged only.

## 22. Residual uncertainty

1. Server-side accepted-payload normalization observed via dry-run `parsed`
   echoes; live APPROVED responses confirm acceptance of all four payloads.
2. `verifiedRun` remains false on all submissions until either the lmx CLI
   ships the evidence-capture flags (`--canonical-prompt` et al.) or the
   canonical exl3 wrapper exposes MTP acceptance counters. Full evidence is
   retained locally to support a future re-verification attempt if the service
   ever supports evidence attach without re-measurement.
3. The service exposes no submission-query API through lmx v0.1.33; duplicate
   checks necessarily rely on local stores plus archived submission receipts.

## 23. Decision

PASS — WELP_LOCALMAXXING_COMPLETION_STANDARD_ESTABLISHED.

## 24. Next human gate

Review the methodology/backfill results and the unstaged WELP documentation
changes; commit the methodology update if accepted; then authorize Gemma 4 E4B
characterization.
