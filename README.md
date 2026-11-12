# WELP — Modular model evaluation

WELP is an eight-section, model/runtime/backend/GPU/host-independent framework
for evidence-backed evaluation of language models. It produces one
model-facing research record per evaluation: standardized, reproducible,
original-evidence-backed findings for text, coding, reasoning, tool-use, and
Agentic models. There are no cross-model leaderboards or rankings; comparisons
appear only where a section explicitly compares configurations for one model.
`SPEC.md` is the authoritative scientific specification.

WELP v1.0 was HUMAN_ACCEPTED on 2026-11-11 after end-to-end validation with three
diverse real-model families and is published as `WumboLabs/welp` tag `v1.0.0`.
This tree is the **v1.1.0 source release**: it carries the owner-accepted
prospective corrections — capability-based native context admission and
explicit full-inventory pre-dispatch enforcement (SPEC §3.4), backend-name
neutrality, excluded-identity export rows, cache-aware native timing
interpretation with optional AMD boundary observations (§4.12), the portable
`WELP_WORKSPACE_ROOT` deployment root, and the prospective HelicopterBench /3
rubric with independent attributed human review (§4.11.1) — without changing
any accepted v1.0 evidence, methodology pin or published result. No new model
campaign is authorized or included. Claims are bounded: results are
configuration-specific (artifact × runtime × deployment), negative results and
budget-limited outcomes are first-class findings, and no universal model score
is computed.

## Sections

Eight scientific sections, independently finalized and reported:

- **Model/Core baseline** (`baseline`) — the standardized reliability, coding,
  reasoning, context and real-work inventory; the anchor for advancement.
- **Advanced Coding** (`coding`) — predefined fixed eligibility, frozen tasks
  and budgets.
- **Advanced Reasoning** (`advanced-reasoning`)
- **Advanced Long Context** (`advanced-long-context`)
- **Advanced Tool Use** (`advanced-tool-use`)
- **HelicopterBench** (`helicopterbench`) — objective playable-game benchmark
  with frozen mechanical scoring; the prospective `helicopterbench/3`
  methodology adds a true 100-point rubric and an independent attributed
  human playtesting review channel (the default remains the frozen `/2`;
  historical /1 and /2 campaigns are never rescored).
- **Runtime Performance** (`runtime-performance`) — measured serving
  conditions (tokens/s, latency, boundary memory), always reported separately
  from quality and never mixed into scoring.
- **Agentic** (`agentic-readiness`, `agentic`) — offline readiness plus the
  campaign-gated authentic scored route; Agentic findings are independent of
  Model findings and never averaged with them.

Non-scored `diagnostic` and `calibration` sections support deployment
diagnostics and fixed calibration pairs.

## Requirements

- Python **3.11+** (only the standard library; no third-party packages).
- Optional external tools, only for the sections that use them:
  - `bwrap` (bubblewrap) — isolated execution probes for coding/Agentic
    sandbox checks and the HelicopterBench /3 human play session;
  - a Chromium-family browser — independent HelicopterBench artifact
    verification and the /3 human play session;
  - a live Wayland display — interactive /3 play sessions only (no X11
    fallback; missing isolation/display prerequisites fail closed);
  - `ffprobe` (FFmpeg) — verify captured H.264 MP4 publication assets;
  - `nvidia-smi` — optional NVIDIA GPU/environment observations;
  - `amd-smi` — optional AMD GPU/environment observations (device-wide
    boundary samples; never process allocations or true peaks);
  - a qualified OpenAI-compatible serving endpoint (e.g. `llama-server`) for
    `REAL_MODEL` measurements.

No build step: run from the source tree. Nothing runs between CLI
invocations; WELP installs no services or daemons.

## Layout

```
welp_next/    framework library and CLI implementation
fixtures/     frozen scientific fixtures (tasks, corpora, oracles)
tests/        behavioral test suite (software validation, no model calls)
docs/         publication contract
SPEC.md       scientific specification: methodology, limits, evidence rules
```

## CLI

All commands print compact JSON (`--json` for machine-readable output) and
fail closed with a `BLOCKED` record on any check failure.

```
python3 -m welp_next plan   --profile PROFILE.json --section baseline
python3 -m welp_next run    --profile PROFILE.json --section baseline
python3 -m welp_next status --campaign CAMPAIGN --section baseline
python3 -m welp_next resume --campaign CAMPAIGN --profile PROFILE.json
python3 -m welp_next report --campaign CAMPAIGN --section baseline
python3 -m welp_next validate --campaign CAMPAIGN [--campaign ...]
```

- `plan` checks the qualified deployment profile (§3 of SPEC) and freezes the
  section plan; `run` executes it with preflight fail-closed admission,
  original-evidence recording, append-only manifests and interruption/resume
  integrity; `report` renders the section report and finalizes the section;
  `validate` is the lean release validator: it replays finalized campaigns
  from original evidence (manifest verification, attempt reconstruction,
  lifecycle and activation predicates) without any inference.
- Agentic sections run offline against fixed SOFTWARE_TEST configurations via
  `--agentic-config`; the authentic scored route activates only from a
  recorded campaign-bound activation file (`--scored`), never from a source
  flag.
- `plan`/`run`/`resume` accept `--methodology helicopterbench/3` to select
  the prospective /3 scoring methodology for the helicopterbench section;
  the default remains the frozen `/2` and the selection is rejected for any
  other section.
- HelicopterBench /3 human review (`welp_next.heli_review`, SPEC §4.11.1) is
  a local, self-contained surface that never alters finalized automated
  evidence and never invents human answers:

  ```
  python3 -m welp_next heli-review --campaign CAMPAIGN status
  python3 -m welp_next heli-review --campaign CAMPAIGN prepare
  python3 -m welp_next heli-review --campaign CAMPAIGN play \
      [--browser BROWSER] [--timeout SECONDS] [--headless]
  python3 -m welp_next heli-review --campaign CAMPAIGN import --review REVIEW.json
  python3 -m welp_next heli-review --campaign CAMPAIGN reconcile --reconciliation RESOLUTION.json
  ```

  `prepare` writes a checklist-only document that cannot execute the game in
  an ordinary browser. `play` launches the exact SHA-256-bound game plus the
  checklist inside a disposable bubblewrap network namespace with only a
  fresh browser profile and the review-export directory writable — narrow
  Wayland socket only, no X11 fallback; missing bubblewrap, browser or
  display prerequisites fail closed. `import` binds an attributed human
  reviewer's 14 answers to the exact game/automation bytes (superseding an
  unfinished draft preserves the original bytes; a finalized review is
  immutable); `reconcile` appends explicit evidence-backed resolutions for
  material disagreements; `status` reports open differences and the
  acceptance gate. Unanswered items stay unresolved — a running earned-points
  total is never a final score. These commands authorize no inference and no
  publication.
- Publication export (offline, no network):
  `python3 -m welp_next.publication CAMPAIGN DEST
  [--acceptance RECEIPT.json --review-source DECISION_SOURCE]` — see
  `docs/publication.md`.

`tests/support.py` builds valid SOFTWARE_TEST profiles and a counting
synthetic OpenAI-compatible endpoint, so the whole workflow can be exercised
without any model: see the test suite for complete worked examples.

## Qualified evaluation

Every measurement records a qualified deployment profile first: model
artifact identity (path/format/revision/SHA-256), runtime/engine identity and
context capacity, reasoning controls, fixed sampler and budgets with recorded
qualification sources, hardware and environment, plus required capability
qualifications (native tool interface, rendered-token context meter, approved
isolated executor). `REAL_MODEL` campaigns route under the established
`research/model-evaluations/<model-key>/campaign-groups/<campaign-id>/`
convention; `SOFTWARE_TEST` work stays inside the project `tmp/` tree.
The evidence umbrella root defaults to the source checkout's sibling
`local-llm/` directory and can be pointed at any deployment location with
`WELP_WORKSPACE_ROOT=/absolute/umbrella`; it is never the source directory
itself, and the required routing under the selected root is still enforced.
Fixed
methodology, budgets and scoring precede any measurement; changing them
mid-evaluation invalidates the affected work.

## Outcomes, evidence and validation

Each work unit records one derived outcome from six facets (outcome, reason,
execution, completion, scoring, limits). Poor performance is a legitimate
scientific result: `FAIL`, `BUDGET_LIMITED`, `NOT_EVALUABLE`, invalid and
indeterminate findings are preserved verbatim — never re-rolled, regraded or
averaged. Every attempt keeps original request/response evidence under a
SHA-256 manifest; corrections are errata, never rewrites. Interruption is
recoverable attempt history, not an evaluated answer.

Software validation: `python3 -B -m unittest discover -s tests` runs the
behavioral suite (self-contained; it creates its own scratch space under
`tmp/` and skips optional evidence-dependent checks when that evidence is not
reachable). Release validation: `welp validate --campaign ...` verifies
finalized campaigns by reconstruction.

## Publication

Publication is a deterministic offline transformation, never an evaluation
step. A finalized campaign exports with its existing visibility disposition;
held or unreviewed records cannot enter the website consumer. A separately
recorded, evidence-bound `HUMAN_ACCEPTED` scientific review receipt
(`welp-scientific-acceptance/1`) — bound to the exact campaign, review date,
public-safe basis and the reviewed section manifests — admits routine
public-safe publication to the central registry (`WumboLabs/evaluations`) and
site (wumbolabs.dev/evaluations) through the standing closeout flow, with no
additional approval. The receipt contains neither private decision-source
bytes nor reviewer identity. Exports never contain credentials, private
paths, raw prompts, or model weights; unsafe values fail closed. The full
contract, including the evaluation → verify → review → HUMAN_ACCEPTED →
automatic publication flow, is in `docs/publication.md`.

## License, provenance and limits

Released under the Apache License, Version 2.0 — see `LICENSE` and `NOTICE`.
WELP (v1.0, carried unchanged into this v1.1.0 source release) is the
successor of the legacy WumboLabs WELP framework: the
reused scientific fixtures listed in `SPEC.md` §8 carry recorded provenance
(source + SHA-256), and the framework itself was authored fresh under this
specification. Bounded claims: diagnostic advancement is a bounded evidence
claim, not a population predictor; measured performance is
deployment-attributed; context envelope completion is not claimed; all
scientific limits and open calibration items are recorded in `SPEC.md`
(§4, §10, §12).

The published [`v1.0.0` tag](https://github.com/WumboLabs/welp/tree/v1.0.0) and
the [pre-v1.0 public snapshot](https://github.com/WumboLabs/welp/tree/228dfe6cd0785470d7e4f778f0e3f08ca413bbc7)
remain discoverable historical references; promotion must preserve their ancestry.
`provenance.json` records public-safe historical extraction hashes.
See [release validation](docs/release-validation.md) for acceptance and software
verification, including valid negative results and remaining comparison limits.
