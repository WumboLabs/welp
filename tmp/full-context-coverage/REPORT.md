# WELP full-context coverage methodology review

## 1. Outcome

PASS — the bounded documentation revision and required checks are complete.
WELP remains DRAFT. No model inference, release, or publication was performed.

## 2. Starting WELP state

MEASURED: clean canonical checkout at
`5ece8f9f7cda2a43066749ce9de37e980fd5b894`. The public package had a main
protocol, reproduction checklist, and Lab Record template, but no detailed
Context Scaling document. The existing research/vault method used 90–95%
occupancy and did not require complete advertised-envelope dispositions.
The frozen context contract retains its older ×4 ladder/±10% targeting/B/M/E
screen. Those historical rules and snapshot bytes were not revised.

Policy loading: global `~/.omp/agent/AGENTS.md` and local-llm `AGENTS.md` were
auto-loaded. `research/engine-kernel/AGENTS.md` was not auto-loaded and was read
explicitly. WELP-local `AGENTS.md` was not auto-loaded; an exact-path read found
no such file. No policy search or speculative descendant-policy scan was used.

## 3. Canonical WELP path and remote

MEASURED: `/home/cheez/Projects/local-llm/welp`, remote
`git@github.com:WumboLabs/welp.git` (fetch and push).
Canonical public source: <https://github.com/WumboLabs/welp>.
The existing checkout was reused; no clone, fetch, publication, or remote
mutation was needed. Remote identity and local HEAD were verified; freshness
against the latest remote branch was not checked.

## 4. Documents changed

Six WELP documentation paths: overview, documentation index, lifecycle, new
canonical Context Scaling method, existing campaign checklist, and existing Lab
Record template. Six existing vault methodology notes were synchronized. The
engine-kernel policy received one concise section. Exact paths appear in §19.

## 5. Context methodology defect corrected

DERIVED from the user-reported campaign scope: selecting 32K default / 64K
guarded profiles answers the practical-profile question, not the entire
model-card envelope question. Capacity admission with a small prompt does not
measure full-window performance or useful context. Historical measurements
remain valid only for their original tested ranges and frozen methodology.

## 6. New terminology

Capacity admission; near-full / full-budget occupancy; useful-context
validation; model-card context coverage. Configured capacity, technical ceiling,
practical ceiling, useful-context ceiling, and daily/fast-profile choices remain
distinct. Context claims expose capacity, usable budget, actual rendered tokens,
occupancy, and reserved output tokens, with exact token counts.

## 7. Full-window occupancy definition

Usable prompt budget = configured context − reserved generation tokens −
required template/runtime safety allowance. The final real-template/tokenizer
input is authoritative; template tokens already counted are not deducted twice.
Preferred occupancy >=99%; hard standard near-full floor >=97%. Runtime-required
exceptions must be bounded, frozen, justified, and explicitly labeled, not called
standard VALIDATED. No nominal filler, raw-length, pre-template, segment-sum,
or configuration-only substitution. No unreported truncation.

DERIVED arithmetic example: 131072 − 512 − 128 = 130432 usable tokens;
130200 input tokens = 99.82%, versus 5000 = 3.83%. These are not inference results.

## 8. Native model-card coverage rule

Pin official card/config URLs, revisions/hashes, exact claims, and token units.
Plan a proportional ladder and explicit exact-native-maximum row. All required
rungs/ranges need evidence-backed dispositions; do not round away the maximum or
silently leave it open because a smaller practical default is preferred.

## 9. Official extension rule

Pin each official extension mechanism and its exact advertised maximum
separately. Verify effective application (for example YaRN), not merely runtime
acceptance of a large context flag. Native and extended contexts are separate
surfaces; each extension maximum gets a disposition. Absence of an official
extension must be source-backed; conflicting claims must be resolved or blocked.

## 10. Fit-limit and integration-blocked dispositions

Fit-first accounting and host safety apply before every major rung. One bounded
exact-capacity attempt if safe; otherwise rigorous lower-bound impossibility
proof plus nearest actual measured fit boundary. No repeated OOMs or speculative
fit-limit claims. FIT_LIMIT and INTEGRATION_BLOCKED are completed scientific
coverage dispositions when demonstrated, not model-quality FAIL.

VALIDATED requires admission, near-full performance, near-full useful-context,
and applicable frozen gates. Measured FAILED retains attributed negative
performance/useful-context evidence. PARTIAL and NOT_TESTED do not complete
coverage. This avoids misclassifying a genuine measured failure as validation or
leaving the disposition taxonomy unable to express it.

## 11. Useful-context and performance requirements

Useful-context fixtures themselves occupy the near-full usable budget. Combined
2/25/50/75/95% targets use actual offsets in the final rendered/tokenized prompt;
placement error <=0.25 percentage points preferred, <=0.50 hard. Highest runnable
native and each runnable official extension context require at least two seeds;
stricter frozen three-seed rules remain binding. Separate inference requests from
target-field/depth observations and retain invalidated request accounting.

Every major admitted rung, including admitted exact maxima, requires near-full
performance/resource measurements: capacities/budgets/tokens/occupancy/reserves,
TTFT, prefill throughput or measured proxy, decode throughput, E2E, post-load and
minimum-free VRAM, safely available power/temperature, and CUDA/OOM/Xid/runtime
errors. Unavailable monitoring cannot imply a clean run. Both performance and
usefulness are necessary; small-prompt admission cannot replace either.

## 12. Mandatory reporting table and checklist

`lab-record-template/README.md` now contains the standard 14-column coverage
table, including output reserve/safety allowance and separate request/observation
counts. One row per major native/official extension rung and exact maximum;
untested/partial/limited/negative rows remain visible. `docs/reproduction.md`
contains all ten required model-card coverage questions. Both are mandatory even
when an early gate stops the campaign before Context.

## 13. Context-completeness gate

PRACTICAL PROFILE SELECTED / PRACTICAL BASELINE CHARACTERIZED is independent of
MODEL-CARD CONTEXT ENVELOPE COMPLETE. Only completed dispositions for every
required rung and exact native/official extension maximum, including evidence
covering limited ranges, permit CONTEXT CHARACTERIZATION COMPLETE. Proper early
stops can finish bounded reports while coverage remains incomplete. Coverage
completion does not mean every rung passed or the whole campaign succeeded.

## 14. Engine-kernel AGENTS delta

One 14-line section enforces native/official extension dispositions, capacity
versus validation, near-full actual final-token occupancy with headroom and
performance/usefulness, independent practical defaults, and the canonical WELP
Context Scaling path. It routes future claims away from the earlier noncanonical
research draft without rewriting that retained draft. No global or workspace
policy change was authorized or made.

## 15. Hivemind mirror delta

Updated existing Context Scaling, lifecycle, terminology, Phase Structure,
Standard Completion Package, and Early-Stop Philosophy notes. Public WELP is
explicitly canonical. No raw outputs, telemetry, or campaign bundles were copied.
The existing E4 historical paragraph remains verbatim, with its historical scope
made explicit rather than retroactively promoted to the new standard.

## 16. Deferred Qwen context items

EXTERNAL_REPORTED (user handoff), not a new card/evidence audit:

- **Qwen3.5-4B:** existing tested ranges remain valid; full model-card context
  completion deferred.
- **Qwen3.5-9B:** existing tested ranges remain valid; full model-card context
  completion deferred.
- **Qwen3.8-27B:** later audit authoritative card-versus-tested-context coverage
  and close any gap.

Qwen testing is intentionally PAUSED. No historical Qwen report was edited and
no Qwen inference was run. No suitable canonical WELP roadmap/backlog exists in
the inspected repository layout; these campaign deferrals are retained here,
not placed in a newly invented roadmap or reusable methodology table.

## 17. MiniCPM5-2B next-gate note

After human review, **MiniCPM5-2B** is the next active model campaign, not Qwen.
It must freeze and use the revised method from the start: authoritative card
native/official-extension envelope, exact maxima dispositions, capacity
admission, final-token near-full occupancy, full-occupancy performance, and
useful-context validation throughout the full occupied window. No advertised
range may be silently left open. MiniCPM was not started in this milestone.

## 18. Validation

MEASURED:

- All six changed canonical WELP documents and all six changed vault notes read
  completely; lifecycle, method, terminology, checklist, and template reconciled.
  The final review report is also read back before delivery.
- 14 canonical local Markdown links/anchors and 64 vault wikilinks resolve.
- Bounded in-memory checks cover 14 changed documents (including this report):
  UTF-8/newlines, conflict markers, balanced fences, eight tables with consistent
  column counts, and valid DRAFT vault YAML. No errors.
- `python3 validators/check_canonical_welp_naming.py current-facing --root .`:
  PASS, 10 tracked current-facing files. The new untracked method was separately
  checked for canonical WELP naming.
- `python3 validators/validate_public_tree.py validate /home/cheez/Projects/local-llm/welp`:
  PASS, 34 selected files, zero errors/findings. The report is not selected.
- `git diff --check`: exit 0. Full tracked documentation diff reviewed, plus the
  new method read completely and the final checklist correction reviewed.
- All 28 other tracked WELP files remain byte-identical, including contracts,
  schemas, validators, and frozen snapshot. Engine-kernel policy differs only by
  its 14-line section; its canonical relative link resolves.
- Global/workspace policies and both Qwen3.5 baseline review reports retain their
  pre-edit SHA-256 values. The existing vault E4 paragraph is byte-identical.
- Acceptance criteria reconciled against the changed methodology, mirrors,
  deferral notes, and current preservation/Git evidence; no unresolved
  cross-document context contradiction found.

DERIVED: both illustrative occupancy percentages recompute correctly.

The initial public-tree invocation with root `.` returned four missing-model-
metadata errors: the checker branches on lexical `root.name` and does not
recognize `.` as WELP. The absolute-root invocation above passes; no validator
code or metadata was changed to suppress the error.

No Markdown CLI/renderer was installed in the available environment; no
dependency was installed. These are bounded lexical/YAML/link and manual
content checks, not a claim of a full Markdown rendering/lint suite. No model
execution or campaign test suite was run. Verification used in-memory snippets;
no throwaway script files, scaffolding, or model processes remain to clean up.

## 19. Exact changed-file list

Canonical WELP files (relative to `/home/cheez/Projects/local-llm/welp`):

1. `README.md`
2. `docs/README.md`
3. `docs/reproduction.md`
4. `lab-record-template/README.md`
5. `protocol/WELP.md`
6. `protocol/context-scaling.md` (new; no canonical detailed method existed)
7. `tmp/full-context-coverage/REPORT.md` (new, local review report)

Policy:

8. `/home/cheez/Projects/local-llm/research/engine-kernel/AGENTS.md`

Existing notes beneath
`/home/cheez/Documents/HiveMindVault/03 - Reference/WumboLabs/`:

9. `WELP Context Scaling (DRAFT).md`
10. `WumboLabs Evaluation Lifecycle Protocol (WELP).md`
11. `Context Terminology.md`
12. `WLEP Phase Structure.md` (existing filename/aliases preserved)
13. `Standard Completion Package.md`
14. `Early-Stop Philosophy.md`

## 20. Git state

MEASURED final state: five modified tracked Markdown files, plus untracked
`protocol/context-scaling.md` and `tmp/full-context-coverage/REPORT.md`.
`git diff --cached --name-only` is empty. HEAD remains
`5ece8f9f7cda2a43066749ce9de37e980fd5b894`. No stage, commit, push, tag,
release, version bump, or publication was performed. The report remains local
and outside the publication allowlist; no ignore/publication policy was changed.

## 21. Residual uncertainty

This establishes documentation requirements, not model capability results.
No authoritative model card was newly audited, no fit boundary measured, and no
inference run. The campaign-bundle validator does not enforce the new narrative
coverage gate; the method/checklist/template explicitly require operator review.
Frozen contract IDs/versions and snapshots stay unchanged; future campaigns must
pin this method's revision/hash alongside their frozen inputs.

## 22. Decision

**PASS — WELP_FULL_CONTEXT_COVERAGE_STANDARD_ESTABLISHED**

This is a methodology/documentation outcome, not model-quality validation or a
hardware-fit result. No acceptance gate remains blocked.

## 23. Next human gate

Review the bounded WELP DRAFT revision, then explicitly authorize a separately
frozen MiniCPM5-2B campaign under this methodology; do not resume Qwen or start
MiniCPM automatically. Publication and Git operations remain human-controlled.
