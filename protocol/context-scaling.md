# WELP Context Scaling — DRAFT

> **Status: DRAFT — NOT v1.0.** Current methodology for new campaigns in
> [WumboLabs/welp](https://github.com/WumboLabs/welp), the canonical methodology
> and evidence source. The HivemindVault notes are a human-readable mirror.

## Scope and compatibility

This method separates selecting a practical profile from characterizing the
complete authoritative model-card context envelope. A preferable daily context
is never an automatic context-characterization stop condition.

Use this method with the [WELP lifecycle](WELP.md) and
[campaign checklist](../docs/reproduction.md). Freeze its revision/hash with the
campaign inputs before testing. Frozen historical contracts, snapshots, and
reports remain unchanged and reproduce under their original rules. The legacy
`welp-context` 0.1.0-draft contract's ×4 ladder, ±10% targeting, and B/M/E screen
alone do not establish the full-context coverage defined here. Retain any
stricter frozen seed/scoring requirements; do not relax them after results.
This current method supersedes the earlier noncanonical research Context
Scaling draft for future full-context claims, not for historical reproduction.

## Terminology and claim language

| Term | Meaning |
|---|---|
| Configured context capacity | Exact token capacity requested from the runtime; also record the effective capacity. |
| Capacity admission | That exact capacity successfully allocates and serves; a small-prompt smoke establishes admission only. |
| Near-full / full-budget occupancy | The final rendered/tokenized input fills the usable prompt budget within the bounds below. This is the primary performance/resource test at a context rung. |
| Useful-context validation | A near-full fixture passes the frozen behavioral gates for retrieving/using information throughout the occupied window. |
| Model-card context coverage | Every authoritative native and officially advertised extended range, including its exact maximum, has an explicit evidence-backed disposition. |
| TECHNICAL_CONTEXT_MAX | Largest measured admitted capacity under the stated profile/resource convention; not a useful-context claim. |
| PRACTICAL_CONTEXT_MAX | Largest measured operating point satisfying the frozen resource reserve and practical gates. |
| USEFUL_CONTEXT_MAX | Highest near-full rung passing the required useful-context contract; not evidence for untested intervening or higher rungs. |
| DAILY_CONTEXT / FAST_PROFILE_CONTEXT | Chosen sustained-use / speed-feature operating point, each bounded by its own measured profile. |

Configured capacity is **not** context validation. For example, configured
131072 with 5000 rendered input tokens demonstrates only **128K-capacity
admission with low occupancy**. It does not establish a full 128K context test.

Valid phrasing distinguishes the evidence:

- “128K-capacity admitted.”
- “128K near-full occupancy tested at 130200 rendered input tokens.”
- “128K useful-context validated at near-full occupancy.”

“128K tested” is invalid when only a small prompt was used. Every context claim
must expose configured capacity, usable prompt budget, actual rendered input
tokens, occupancy percentage, and reserved output tokens; unexplored fields are
explicitly `NOT_TESTED` or `UNKNOWN`, never invented. Use exact token counts
alongside human-readable K labels.

## Full-window definition

```text
usable_prompt_budget = configured_context
                       - reserved_generation_tokens
                       - required_template_or_runtime_safety_allowance
occupancy_percent = 100 * actual_rendered_input_tokens / usable_prompt_budget
```

Freeze output reserve and any required safety allowance before each test.
Count the **final prompt after the real chat template and tokenizer have been
applied**, including system text, instructions, special tokens, and generation
prefix. Template tokens already counted in that input must not be subtracted a
second time as an allowance. Verify requested versus effective runtime capacity
and tokenization; an unexplained mismatch invalidates the claimed rung.

- Preferred target: **>=99% of usable_prompt_budget**.
- Hard near-full acceptance floor: **>=97% of usable_prompt_budget**.
- Input must not exceed the usable prompt budget; generation needs its reserve.
- If architecture/runtime mechanics require a different bounded margin, freeze
  and justify the exception before testing, retain the mechanism evidence, and
  report actual tokens and occupancy. Below 97% is an explicitly labeled
  exception, not an unqualified standard near-full/full-context pass. A
  substantially emptier prompt cannot be silently called full context.

Nominal filler size, raw source-text length, configured capacity, pre-template
counts, and independent-segment token sums are not substitutes for the final
rendered/tokenized prompt. Record that prompt's identity/hash and measured token
count; verify no runtime truncation or unaccounted prompt transformation.

Illustration only: capacity 131072, output reserve 512, safety allowance 128
leaves 130432 usable tokens. An input of 130200 occupies 99.82% of that budget;
5000 occupies 3.83%. These are arithmetic examples, not model measurements.

## C0 — Pin the authoritative envelope and freeze the plan

Before context testing, pin the official model card, official config, and
applicable official extension documentation: URLs, revisions/content hashes,
exact claims, and units. Record separately:

1. Native context maximum in exact tokens.
2. Officially supported extension mechanism(s), including required settings.
3. Exact officially advertised extended maximum for each supported mechanism.

Record explicit absence of an official extension with a source; do not invent
one. Resolve contradictory or ambiguous authoritative claims before freezing a
coverage conclusion; record unresolved claims as a blocker rather than selecting
the convenient smaller limit. Runtime acceptance of a large `--ctx-size` is not
proof of official extension support. For YaRN or equivalent, retain effective
configuration and implementation/startup evidence that the documented mechanism
is actually applied. Native and extended contexts are separate experimental
surfaces, even if capacity values overlap.

Freeze artifact, runtime/build, real tokenizer/template, requested/effective
profile, KV/recurrent-state geometry, offload policy, output reserve, safety
allowance, VRAM reserve, cache policy, rungs, seeds, useful-context/scoring gates,
performance expectations, and host-safety stops. Label evidence MEASURED,
DERIVED, INFERENCE, HYPOTHESIS, EXTERNAL_REPORTED, or UNKNOWN. A card claim is
EXTERNAL_REPORTED, not local validation; fit accounting is DERIVED with stated
inputs and assumptions.

## C1–C2 — Proportional fit ladder and practical resource ceiling

Plan proportional major rungs through the complete advertised range, plus useful
boundary probes. A typical native ladder is 8K, 16K, 32K, 64K, 128K, any useful
intermediate boundary, then the **exact native model-card maximum**. Use only
rungs appropriate to the model's range; intermediate spacing is model-dependent.
Every exact advertised native maximum must receive a disposition, not rounding
to the nearest K label. For each official extension, continue from native max
through one or more proportional extended rungs to the **exact officially
advertised extension maximum**, which also must receive a disposition.

Before every major rung, perform fit/accounting, inspect GPU/host state, and
preserve operational constraints. Account for weights, context-dependent KV,
recurrent state, workspace, allocator/runtime overhead, host/offload costs, and
required reserve; do not extrapolate a nonlinear boundary as proof. Hybrid
attention may have distinct KV and recurrent pools; report them separately.
Paged runtimes require effective block-pool accounting, not only a context flag.

If a maximum is predicted not to fit:

- If safe, make **one bounded exact-capacity admission attempt** and retain its
  success/failure evidence. Do not repeatedly OOM the machine.
- If the attempt itself presents unreasonable host risk, retain a hard
  lower-bound accounting proof of impossibility under the frozen hardware/profile
  constraints and establish the nearest actual measured fit boundary. An
  unsupported estimate is insufficient for `FIT_LIMIT`.
- A safe failed admission likewise needs evidence establishing the actual fit
  boundary and resource attribution; do not label arbitrary runtime errors OOM.

Stop on CUDA/OOM/Xid/runtime or host-safety errors, retain evidence, and do not
retry an unsafe rung. Resume only under the applicable safety/authorization
rules. `FIT_LIMIT` does not imply the model lacks the advertised capability on
other hardware. A different offload/runtime/profile is a separate surface, not a
silent rescue of the original.

C2 derives the practical resource ceiling from measured telemetry and the frozen
reserve. Latency, throughput, reserve, reliability, and intended role select the
practical default independently of the coverage obligation.

## C3 — Useful context at near-full occupancy

The useful-context fixtures themselves must meet the full-window occupancy
rule, not merely run under a large configured capacity. Freeze exact retrieval,
multi-fact/synthesis, conflict handling, grounding/absent-evidence, and instruction
retention gates as applicable before inference; preserve finish-reason and
truncation gating. Incomplete output is not automatically a retrieval failure.

**Outcome semantics (methodology revision, 2026-09-19).** Every useful-context
request emits the CP-1 outcome record (`welp-outcomes` 0.1.0-draft): the
behavioral gates report structured results for retrieval, synthesis,
absent-info handling, and terminal/instruction handling, plus `completion`
(`COMPLETE | FAIL_LENGTH | EMPTY_ANSWER | INVALID_STOP`) and `budget`. The
harness MUST parse and record the verbatim `finish_reason` per request; a
harness that can capture it but writes a constant null is a scorer-artifact
defect. When a runtime does not expose finish_reason, derive completion from
measured token accounting (completion_tokens >= reserve => FAIL_LENGTH) and
label the derivation DERIVED.

**Standardized output reserve.** The context output reserve is **512 tokens**
(`welp-generation-budget` 0.1.0-draft), derived as
`max(512, 2 × answer_budget of the useful-context gate tasks)` — the gate
task answer budget is 256 and measured canonical gate answers are 40–128
tokens. Campaign-by-campaign 512-vs-640 variance is prohibited from the
methodology-revision snapshot on; any exception must be pre-frozen, justified,
and reported per the full-window exception rule.

**Semantic and operational lanes.** A rung whose retrieval/synthesis evidence
is strong but whose normal operational generation budget prevented a completed
final answer is reported **`BUDGET_LIMITED`** — not `FAILED` (the rung keeps
its retrieval evidence visible) and not `VALIDATED`. Lane declarations:

- `USEFUL_CONTEXT_MAX_OPERATIONAL`: highest rung passing all gates with a
  completed answer **within the frozen operational profile** (frozen reserve,
  frozen reasoning mode). This is the deployment-facing number.
- `USEFUL_CONTEXT_MAX_SEMANTIC`: may only be claimed from a **PREDECLARED
  non-starving lane** that actually produced a completed, scorable answer
  (all gates PASS, completion COMPLETE). "Correct facts visible in the
  reasoning trace" never promotes to semantic PASS.

Use combined target depths **2%, 25%, 50%, 75%, and 95%**. Measure against the
**final rendered/tokenized input**: for each target, record its actual token
start offset and `100 * offset / actual_rendered_input_tokens`. Freeze the
marker/span convention; retain target spans, intended depths, actual depths,
and placement errors. All five placements must satisfy:

- Preferred absolute error: **<=0.25 percentage points**.
- Hard absolute error: **<=0.50 percentage points**.

The five-depth placement set and its preflight evidence are validator-checked
for methodology-revision-era campaigns (R13): the pre-revision campaign
practice of four placed targets plus a ~99% instruction block does not satisfy
the 95%-depth requirement (the qwen3-14b closeout completion of 2026-09-15 is
the correction precedent; retained evidence stays unchanged).

Render/tokenize the whole prompt, locate targets in that final token stream,
adjust, then re-render and re-tokenize to verify occupancy and every depth.
Nominal segment labels and independent-segment token-sum assumptions are invalid.
Do not infer token offsets by separately tokenizing a prefix.

At the highest runnable native context, use **at least two seeds**; at the
highest runnable officially extended context, use **at least two seeds** for
each runnable extension surface. A frozen method requiring more remains binding
(the legacy three-seed confirmation contract still requires three, not two).
Report each seed and depth outcome and the frozen aggregation rule. Seeds do not
replace missing depths, and high-rung success does not silently fill other rows.

Report inference requests separately from target-field/depth observations:
five fields inside one combined prompt are **one inference request and five
observations**, not five requests. Retain invalidated requests in execution
accounting without counting them as valid coverage.

The canonical fixture family (Family A) and its outcome evaluation live in
`fixtures/useful_context/family-a.json` and `harness/context.py`
(`welp-phase-harness/1.0.0-draft`); campaigns must use the canonical fixture
and scorer rather than per-campaign copies. A supplementary Family B for
generalization is planned P2 work and MUST NOT replace Family A as the
canonical longitudinal fixture.

## C4 — Near-full performance and resources

Every major successfully admitted rung requires near-full performance testing,
including the exact native maximum and each official extension maximum if
successfully admitted. A small-prompt capacity smoke cannot replace this.
Capture at least:

- Configured/effective capacity, usable prompt budget, actual rendered input
  tokens, occupancy, output reserve, safety allowance, actual generated tokens.
- TTFT, prefill throughput (or explicitly defined measured proxy), decode
  throughput, and end-to-end latency (E2E), with units and measurement boundaries.
- Post-load VRAM, minimum free VRAM during the run, and the frozen reserve.
- Power and temperature where safely available; otherwise availability/reason.
- CUDA, OOM, Xid, and runtime errors, including explicit absence or UNKNOWN when
  monitoring is unavailable; no unsupported clean-run claim.

Measure uncached prefill under the frozen cache policy; report processed/cached
tokens where available and limitations of proxies. Never disguise cached input
as full-window prefill. The prefill degradation curve is a first-class result.

Near-full performance asks whether the stack can process a genuinely full
window with acceptable resource/performance behavior. Useful context asks
whether it can use information throughout that window. **Both are required for
VALIDATED**, alongside admission and applicable frozen stability gates.
Retrieval at a much smaller occupancy answers neither full-window question.
If a safety stop prevents these required runs, retain `PARTIAL` unless a
completed, evidence-backed limiting disposition below is established.

## C5–C7 — Retained stability and operational checks

C5 retains repeated long-context runs, drift/fragmentation/cache-eviction checks,
and zero Xid/reset under the frozen stability contract. C6 remains optional
agent/session endurance at DAILY_CONTEXT; C7 retains compaction/resume resilience
at the claimed ceiling where applicable. Freeze applicability and list missing
required stages as gaps, never implied passes. Full-envelope coverage does not
authorize bypassing safety or earlier lifecycle gates.

## Dispositions and context-completeness gate

| Final disposition | Required evidence | Completed disposition? |
|---|---|---|
| VALIDATED | Capacity admitted; standard near-full performance and useful-context gates passed, with all applicable frozen requirements satisfied. | Yes |
| FIT_LIMIT | Resource envelope prevents the point; safely measured failure or rigorous impossibility proof plus nearest actual measured fit boundary and attribution. | Yes |
| INTEGRATION_BLOCKED | Pinned runtime does not implement, or demonstrably cannot verify, the required native/official extension mechanism; retain implementation/configuration evidence and bounded diagnostics. | Yes |
| FAILED | Valid near-full measurements fail a frozen performance or useful-context gate; report gate, results, repetitions, and attribution. Not an invalid fixture or unmeasured range. | Yes, a measured negative result, not validation |
| PARTIAL | Capacity may admit, but required near-full performance/useful-context or other frozen evidence is incomplete. | No |
| NOT_TESTED | No valid tested or demonstrated limiting disposition yet. | No |

`FIT_LIMIT` and `INTEGRATION_BLOCKED` are legitimate completed scientific
coverage dispositions, not model-quality FAIL. `FAILED` preserves an actual
measured negative result without falsely calling it VALIDATED. Missing tools,
unauthorized work, or a preferred small default alone are not demonstrated
integration/fit limits. Report budget-margin exceptions explicitly; they cannot
be converted into standard `VALIDATED` by relabeling them.

Keep separate gates:

- **PRACTICAL PROFILE SELECTED**: a daily/default and any guarded profile chosen
  on latency, throughput, reserve, reliability, and role evidence.
- **PRACTICAL BASELINE CHARACTERIZED**: bounded first-pass work may finish while
  advertised context coverage remains deferred.
- **MODEL-CARD CONTEXT ENVELOPE COMPLETE**: every planned major native/official
  extension rung and every exact advertised maximum has a completed disposition,
  including explicit evidence covering any resource-/integration-limited range.

Only the last gate permits **CONTEXT CHARACTERIZATION COMPLETE**. Any advertised
maximum or required rung still `PARTIAL` or `NOT_TESTED` prevents that claim. A
proper early safety/quality stop can finish a bounded campaign report without
finishing context characterization; record every remaining gap and stop reason.
Coverage completion is not an all-rungs-pass or whole-campaign success claim.

Illustrative decisions, not measurements: default 32K, practical extended 64K,
native maximum 262K validated but impractical; or default 32K, native maximum
`FIT_LIMIT` with a measured 128K fit boundary. Exact card maxima and boundary
tokens must appear in the actual report. Practical profile selection never
terminates the ladder by itself.

## Mandatory coverage report

Use the [standard coverage table](../lab-record-template/README.md#model-card-context-coverage)
for every campaign, even when Context was not reached. One row per major rung
per native/extension surface, with separate rows for exact advertised maxima;
include capacity-only, failed, blocked, partial, and untested rows. Link pinned
claims, effective mechanism evidence, per-run token/telemetry/depth results, and
fit proofs. Report per-run values rather than blending different occupancies or
seeds into a misleading single value. The table and the ten-question
[campaign checklist](../docs/reproduction.md#model-card-context-checklist)
make unanswered ranges visible.

The existing campaign-bundle validator does not mechanically enforce this new
narrative coverage gate. Operator review of the table and underlying evidence
is mandatory; a validator exit 0 alone does not establish context completeness.
