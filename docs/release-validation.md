# WELP v1.0 release validation

Scientific/operational completion was HUMAN_ACCEPTED by the owner on 2026-11-11. This document records how the WELP v1.0 release source was validated; it is not itself a claim that remote release deployment has completed.

## Scientific acceptance basis

Three distinct accepted model families: Qwen3.5-9B, fresh Gemma 4 12B and Liquid AI LFM2.5-8B-A1B. The accepted release aggregate covers 11 campaigns, 14 independently finalized sections and 204 runner-backed unit replays. All eight sections are implemented; Advanced Coding, Advanced Reasoning and Full Agentic M3 are accepted with their original limitations.

Valid negatives are retained: Qwen specialist budget limits, Agentic Research/Repository FAILs, LFM reasoning FAIL and the broken LFM HelicopterBench /2 game (19/90 raw, 21.1/100 normalized, PARTIAL). Generation completion is not gameplay success. Historical HelicopterBench /1 remains separately attributed and is never rescored under /2.

The lean validator verifies original manifests and shared runner-backed replay predicates. Its Agentic manifest checks do not claim to rerun the historical independent Agentic checker. Finite inventories, fixed budgets and configuration-specific observations do not establish universal model capability.

## Software and publication verification

Fresh prepared-source command:

```sh
python3 -B -m unittest discover -s tests
```

Result: 341 tests run, OK, with two explicit evidence-dependent skips. Tests include scientific acceptance binding, changed-manifest/source rejection, preservation of negative/budget-limited outcomes, and refusal of unresolved INVALID coverage, software evidence and private review material.

The existing website consumer admitted 11 actual accepted public-safe event exports and rejected missing scientific acceptance, another event's video attribution and incorrect asset hashes. The website's existing pinned registry remained unchanged while authenticated remote promotion was unavailable. Local Zola build, deterministic registry projection and existing content/route checks passed (743 site checks).

That promotion obstacle was authentication-only and has been resolved: the
GitHub CLI API token was invalid at preparation time, and push access was
verified over the repository's existing, already-authenticated SSH transport
instead — `git push --dry-run` against `WumboLabs/welp` succeeds over it. No
credentials were created or modified; normal promotion uses that SSH
transport, and CLI API access is not required for it.

The genuine LFM /2 gameplay MP4 was verified as H.264, 800×364, 26 seconds and 8,993 bytes, fully decoded without error and played in a browser. SHA-256: `72a16a92c3fb259322ef01969e401ac8a7e2ab56cd2fddafc678f7175d4f3fc4`. Observed footage shows the Loading screen, not a functioning game; it is supplementary negative evidence, not a substitute for scoring.

No new model inference, model acquisition, accelerator workload, production-service activation or scientific methodology change was performed for this release preparation. Public GitHub/event/website promotion remains a separately verified execution step, never inferred from these local checks.
