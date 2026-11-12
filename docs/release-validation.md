# WELP release validation

This document records how WELP release sources are validated. It is not itself
a claim that remote release deployment has completed.

## Scientific acceptance basis (v1.0, 2026-11-11)

Scientific/operational completion was HUMAN_ACCEPTED by the owner on
2026-11-11. Three distinct accepted model families: Qwen3.5-9B, fresh
Gemma 4 12B and Liquid AI LFM2.5-8B-A1B. The accepted release aggregate
covers 11 campaigns, 14 independently finalized sections and 204
runner-backed unit replays. All eight sections are implemented; Advanced
Coding, Advanced Reasoning and Full Agentic M3 are accepted with their
original limitations.

Valid negatives are retained: Qwen specialist budget limits, Agentic
Research/Repository FAILs, LFM reasoning FAIL and the broken LFM
HelicopterBench /2 game (19/90 raw, 21.1/100 normalized, PARTIAL). Generation
completion is not gameplay success. Historical HelicopterBench /1 remains
separately attributed and is never rescored under /2 or /3.

The lean validator verifies original manifests and shared runner-backed
replay predicates. Its Agentic manifest checks do not claim to rerun the
historical independent Agentic checker. Finite inventories, fixed budgets and
configuration-specific observations do not establish universal model
capability.

## v1.1.0 source release scope

The v1.1.0 source release (2026-11-11) adds no new campaign evidence and
changes no accepted v1.0 result, methodology pin or frozen fixture. It
carries the owner-accepted prospective corrections only:

- capability-based native context admission and explicit full-inventory
  pre-dispatch enforcement (SPEC §3.4), with a `context.meter.evidence`
  preflight check;
- supplied-backend neutrality (SPEC §3.1): backend names are recorded
  conditions, not a vendor-name admission whitelist;
- excluded/missing-identity export rows that stay distinct from scored
  failures (SPEC §9.3, `docs/publication.md`);
- cache-aware native timing interpretation (`native-input-cache-split/1`)
  and optional device-wide AMD boundary observations via
  `python -m welp_next.observe_amd` (SPEC §4.12);
- the portable `WELP_WORKSPACE_ROOT` deployment root (SPEC §9.1);
- the prospective `helicopterbench/3` rubric (SPEC §4.11.1) with the
  independent attributed human review workflow (`welp_next.heli_review`).
  No historical game is rescored as /3; the first official /3 result requires
  a separately authorized prospective evaluation.

## Software verification

From a prepared source tree (standard library only):

```sh
python3 -B -m unittest discover -s tests
```

The suite is self-contained: it builds its own scratch space, uses synthetic
SOFTWARE_TEST endpoints and profiles, and skips only explicitly
evidence-dependent checks when that evidence is not reachable. It covers
scientific acceptance binding, changed-manifest/source rejection, preservation
of negative/budget-limited outcomes, exclusion-row export semantics,
refusal of unresolved INVALID coverage, software evidence and private review
material, HelicopterBench /2 and /3 scoring and review-surface behavior, and
the observe_amd unit-conversion contract.

The release validator verifies finalized campaigns by reconstruction without
any inference:

```sh
python3 -m welp_next validate --campaign /absolute/campaign --json
```

Exit status 0 means the checks passed; 2 names the failed check. Genuine
negative model findings are valid results and never a validation failure.

`PUBLICATION-MANIFEST.json` records each delivered file's size, SHA-256 and
POSIX permission mode. Fixture executable bits are part of the scientific
workspace identity: preserve them when copying or checking out the release.
Release verification checks bytes and modes before publication; Git preserves
the executable bit. Private campaigns and generated test scratch are excluded.

## Publication verification

The offline export adapter is tested against synthetic campaigns: missing
scientific acceptance, another event's media attribution and incorrect asset
hashes are rejected; excluded/missing identities export as explicit
`NOT_RUN` rows without invented scores. The full publication contract,
including the evaluation → verify → review → HUMAN_ACCEPTED → automatic
publication flow, is in `docs/publication.md`.

No model inference, model acquisition, accelerator workload, production-
service activation or scientific methodology change is performed or
authorized by preparing this source tree. Public repository/event/website
promotion remains a separately verified execution step, never inferred from
these local checks.
