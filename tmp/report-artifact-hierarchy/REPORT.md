# REPORT — WELP Report Artifact Hierarchy

> Artifact role: milestone review report (repository development report per the
> global OMP `<repo>/tmp/<milestone-name>/REPORT.md` convention — not a campaign
> bundle primary report)
> Milestone: welp/report-artifact-hierarchy
> Status: CURRENT
> Date: 2026-09-10

## 1. Outcome

PASS — WELP_REPORT_ARTIFACT_HIERARCHY_ESTABLISHED. The canonical WELP repo now
formally defines the report artifact hierarchy (`REPORT.md` primary /
`WELP-LAB-RECORD.md` companion / noncanonical review summaries / quarantined
prior attempts), the Lab Record template and reproduction checklist enforce the
new naming, the campaign validator enforces it for new-format bundles without
invalidating historical bundles, the engine-kernel durable policy is updated
narrowly, and the Hivemind methodology mirror reflects the hierarchy. No model
inference; no historical campaign evidence modified; nothing staged or committed.

## 2. Starting state

- Canonical WELP repo had NO explicit report artifact hierarchy. The only
  report-naming rules were: `docs/reproduction.md` step 10 ("Produce
  `report.md`, ..."), `lab-record-template/LAB-RECORD-LAYOUT.md` (`report.md` =
  full Standard Completion Package report; `README.md` = summary),
  `docs/validator.md`, and `validators/validate_campaign_welp.py` (required
  `report.md` unconditionally).
- HEAD `5ece8f9 Enforce canonical WELP naming` covers the protocol NAME
  (WELP vs frozen `wlep` identifiers) only, not report artifact roles.
- The working tree carried unrelated, pre-existing uncommitted Context Scaling
  changes (README.md, docs/README.md, docs/reproduction.md,
  lab-record-template/README.md, protocol/WELP.md, untracked
  protocol/context-scaling.md, tmp/full-context-coverage/) from a prior
  milestone. PRESERVED UNTOUCHED; this milestone's edits were layered on top.
- Motivating example (MiniCPM5-2B, 2026-09-10): `REPORT.md` (primary, 55
  scientific requests, 7 supervised server arms) coexisted with `report.md`
  (compact Lab Record) in one bundle, plus a human review summary under
  `~/Projects/local-llm/tmp/` and a `-prior-attempt-quarantined/` sibling — all
  legitimate, none self-identifying by filename.

## 3. Canonical repo/path/HEAD

- Repo: `~/Projects/local-llm/welp` (origin `git@github.com:WumboLabs/welp.git`)
- HEAD at start and end: `5ece8f9 Enforce canonical WELP naming` (branch
  `main`, in sync with `origin/main` at start; no fetch/pull/push performed)
- No WELP-local AGENTS.md/policy file exists (checked); global OMP
  (`~/.omp/agent/AGENTS.md`, EXPLICITLY_READ), workspace
  (`~/Projects/local-llm/AGENTS.md`, AUTO_LOADED), global ZCode
  (`~/.zcode/AGENTS.md`, AUTO_LOADED), and engine-kernel
  (`research/engine-kernel/AGENTS.md`, EXPLICITLY_READ) policies applied.

## 4. Problem being corrected

`REPORT.md` and `report.md` could coexist as differently-cased names for two
different document roles (primary scientific report vs compact Lab Record), and
nothing in filename, header, or documentation identified which artifact governs
scientific claims or how superseded prior attempts relate to current evidence.

## 5. New artifact hierarchy

Documented canonically in `protocol/WELP.md` → "Report artifact hierarchy"
(artifact table + rules), mirrored in `docs/naming-policy.md`:

| Artifact | Role | Authority |
|---|---|---|
| `REPORT.md` | PRIMARY SCIENTIFIC REPORT | authoritative source of truth |
| `WELP-LAB-RECORD.md` | standardized structured Lab Record companion | companion/index; never a second experiment or independent report |
| `<campaign-slug>-review-report.md` | human review summary (conventionally `~/Projects/local-llm/tmp/`) | noncanonical convenience summary; must link primary + Lab Record |
| `<campaign>-prior-attempt-quarantined/` | superseded prior execution preserved intact | superseded forensic evidence; never current evidence |

## 6. Primary REPORT.md rule

Exactly one current primary `REPORT.md` per active campaign bundle; source of
truth for outcome, interpretation, measurements, negative findings,
classifications, context dispositions, limitations, next human gate. If any
companion conflicts, `REPORT.md` governs.

## 7. WELP-LAB-RECORD.md rule

Standardized companion replacing the future use of `report.md`; summarizes/
indexes the SAME campaign; explicitly NOT another experiment/run/primary report.
`lab-record-template/README.md` now instructs instantiation as
`WELP-LAB-RECORD.md` and carries the role header in the template itself.

## 8. Human review-summary rule

`<campaign-slug>-review-report.md`, preferred location
`~/Projects/local-llm/tmp/`; convenience document that must prominently link
`REPORT.md` and `WELP-LAB-RECORD.md`; explicitly noncanonical; `REPORT.md`
governs on conflict.

## 9. Superseded/quarantine rule

Prior substantial executions are never silently deleted, overwritten, merged,
or treated as current evidence; quarantine under an unmistakable sibling path
(preferred suffix `-prior-attempt-quarantined`), record provenance, and the
current `REPORT.md` must state the prior attempt's existence, quarantine path,
supersession reason, and whether any of its data is used. Quarantined bytes are
not relabeled when preservation contracts require byte identity.

## 10. Artifact-role headers

Lightweight standard documented in `protocol/WELP.md` and embedded in the Lab
Record template: `Artifact role:` / `Campaign:` / `Status: CURRENT | CURRENT
COMPANION` / `Primary scientific report: REPORT.md` (companions). Review
summaries additionally carry explicit pointers to both current companions.

## 11. Source-of-truth precedence

`REPORT.md` (authoritative narrative/scientific) > `WELP-LAB-RECORD.md`
(standardized derivative/index) > review summary (convenience). Companion
disagreement is a documentation defect: reconcile from retained raw evidence,
never from convenience. Superseded prior attempts never silently override the
current primary. No document describes the Lab Record as an independent
scientific report; precedence is explicit everywhere it matters.

## 12. Template/checklist changes

- `lab-record-template/README.md`: role header block, "Filename and role"
  section (instantiate as `WELP-LAB-RECORD.md`; companion-not-replacement;
  `REPORT.md` authoritative), updated Filename conventions table (REPORT.md /
  WELP-LAB-RECORD.md / review summary / report.md historical-only).
- `lab-record-template/LAB-RECORD-LAYOUT.md`: bundle tree now shows `REPORT.md`
  (primary) + `WELP-LAB-RECORD.md` (companion); historical single-`report.md`
  bundles explicitly framed as frozen evidence; quarantine sibling rule stated.
- `docs/reproduction.md`: step 10 rewritten to the new completion package; new
  concise "Report artifact checklist" (7 questions: exactly one CURRENT
  REPORT.md; Lab Record named WELP-LAB-RECORD.md; no ambiguous report.md;
  companions point to primary; quarantine exclusion; explicit statuses;
  fingerprint consistency).
- `README.md` (root): one core-rules bullet pointing at the hierarchy.
- `docs/validator.md`: required-files and detected-defects sections updated.

## 13. Validator behavior

`validators/validate_campaign_welp.py` — smallest correct implementation
(new-format-only enforcement + historical warning; no schema/versioning
migration needed; schemas unchanged — none encode report filenames):

- New-format bundles (exact-case `REPORT.md` present, detected via directory
  name set so case-insensitive filesystems cannot misread a legacy bundle):
  `R01` REPORT.md primary; `R02` ERROR on `REPORT.md` + `report.md`
  coexistence; `R03` INFO when `WELP-LAB-RECORD.md` present, WARNING when
  absent.
- Historical bundles (no `REPORT.md`): unchanged requirement of `report.md`
  (error if missing, exactly as before) plus `R04` legacy-naming warning.
- `protocol-findings.md` requirement unchanged.

## 14. Historical compatibility

The five pre-existing fixtures (legacy WLEP, current WELP pre-hierarchy,
WELP-with-legacy-evidence, unknown-prefix, improperly-rewritten) still validate
exactly as before — warnings do not affect validity, so all completed historical
bundles (including the MiniCPM5-2B bundles, which use `report.md`) remain VALID.
Three fixtures added: good new hierarchy (accepted), ambiguous
`REPORT.md`+`report.md` pair (rejected with R02), new format without Lab Record
(accepted with R03 warning). Selftest extended from 5 to 8 fixture sets and now
asserts R02/R03/R04 firing. `publication-allowlist.json` and
`PUBLICATION-MANIFEST.json` gained `REPORT.md` and `WELP-LAB-RECORD.md` allowed
patterns (existing `report.md` pattern retained for historical trees); both
files are pattern allowlists, not hash-bound evidence.

## 15. Engine-kernel AGENTS delta

`research/engine-kernel/AGENTS.md`: one new concise section "WELP report
artifact hierarchy" (5 bullets: canonical-WELP pointer; REPORT.md primary;
WELP-LAB-RECORD.md companion; no report.md second role; review summaries
noncanonical; quarantined attempts supply no current claims unless explicitly
incorporated and attributed). No duplication of the full WELP section; global
and workspace AGENTS.md untouched.

## 16. Hivemind mirror delta

`~/Documents/HiveMindVault/03 - Reference/WumboLabs/`:

- `Standard Completion Package.md`: required artifact 1 renamed to "Primary
  scientific report (`REPORT.md`)"; new short "Report artifact hierarchy"
  subsection (companion naming, review-summary role, quarantine rule, canonical
  pointer). Pre-existing content otherwise preserved.
- `Standard Campaign Artifacts.md`: campaign layout tree now lists `REPORT.md`
  + `WELP-LAB-RECORD.md` with one clarifying sentence.
- No MiniCPM raw evidence or campaign-specific measurements copied into the
  vault; the public WELP repository remains canonical. Other modified notes in
  that vault directory are pre-existing uncommitted changes, untouched.

## 17. Exact files changed

Canonical WELP (`~/Projects/local-llm/welp`, all unstaged):

1. `README.md` (core-rules bullet; on top of pre-existing +1 context line)
2. `protocol/WELP.md` (new hierarchy section; validator fixture count; on top of pre-existing context-gate section)
3. `docs/naming-policy.md` (report artifact filenames section)
4. `docs/reproduction.md` (step 10 rewrite; report artifact checklist; on top of pre-existing context-scaling changes)
5. `docs/validator.md` (required files, R02–R04 defects, 8-fixture suite)
6. `lab-record-template/README.md` (role header, filename/role section, conventions table; on top of pre-existing coverage-table changes)
7. `lab-record-template/LAB-RECORD-LAYOUT.md` (bundle tree + historical note)
8. `validators/validate_campaign_welp.py` (R01–R04, 3 new fixtures, extended selftest, docstring)
9. `publication-allowlist.json` (+2 patterns)
10. `PUBLICATION-MANIFEST.json` (+2 patterns)

Elsewhere:

11. `~/Projects/local-llm/research/engine-kernel/AGENTS.md` (new hierarchy section)
12. `~/Documents/HiveMindVault/03 - Reference/WumboLabs/Standard Completion Package.md`
13. `~/Documents/HiveMindVault/03 - Reference/WumboLabs/Standard Campaign Artifacts.md`

New (untracked): `tmp/report-artifact-hierarchy/REPORT.md` (this file).

## 18. Validation

- Read back every changed canonical WELP document (complete final states
  reviewed; full `git diff` hunks reviewed line by line).
- Current-facing `report.md` grep: every remaining mention is an explicit
  prohibition, a checklist item, or explicitly framed as historical/frozen or
  validator legacy-compatibility code. No current-facing document instructs
  creating `report.md`.
- `validate_campaign_welp.py selftest`: PASS (8 fixture sets; new hierarchy
  accepted; ambiguous pair rejected; legacy/historical sets unchanged).
- `check_canonical_welp_naming.py selftest`: PASS; `current-facing`: PASS
  (10 files, no unapproved frozen-token hits introduced).
- `validate_public_tree.py selftest`: PASS; `validate` over the repo root:
  PASS (34 files). [Initial FAIL was an invocation artifact — `Path(".").name`
  is empty, so the validator did not recognize the root as "welp"; rerun with
  the absolute named path passed.]
- Relative markdown links in all changed docs resolve: LINKS_OK (script check).
- `git diff --check` (welp repo): clean. HiveMindVault repo: clean.
  `research/engine-kernel` is not a Git repository — git diff --check
  inapplicable there.
- Historical evidence immutability: all five MiniCPM5-2B bundles under
  `research/engine-kernel/experiments/` (characterization, `-prior-attempt-
  quarantined`, flashinfer repair, contained-toolchain qualification, baseline)
  contain zero files modified after 2026-09-10 20:00 (this session); the
  characterization bundle's `REPORT.md` + `report.md` and the quarantined
  bundle's `REPORT.md` verified present and untouched.

## 19. Git state

- welp: branch `main` at `5ece8f9` (no new commits); 11 tracked files modified
  (10 by this milestone as listed in §17; docs/README.md carries only the
  pre-existing context-scaling line), untracked `protocol/context-scaling.md`
  and `tmp/` pre-existing/added-local; nothing staged, committed, pushed, or
  tagged. No fetch/pull performed.
- HiveMindVault: my two note edits unstaged among pre-existing uncommitted
  modifications; nothing staged.
- engine-kernel: not a Git repository.

## 20. Residual uncertainty

- The `R03` Lab-Record expectation is a WARNING, not an error, in new-format
  bundles: deliberate, so the standard can settle without failing otherwise
  complete bundles; tightening to an error is a one-line future change.
- Publication allowlist/manifest additions assume future campaign bundles would
  only be published through a separate human-gated release; the patterns merely
  keep the new names publishable if examples are ever added.
- The pre-existing uncommitted Context Scaling changes were reviewed for
  boundary integrity but are not validated by this milestone beyond confirming
  they are byte-preserved in the combined diff.
- Vault mirror numbering in `Standard Completion Package.md` retains its
  pre-existing irregular numbering (1,2,3,4,5,7,9,10,11); left as found (scope).

## 21. Decision

PASS — WELP_REPORT_ARTIFACT_HIERARCHY_ESTABLISHED. All §18 acceptance criteria
demonstrated: WELP remains DRAFT; hierarchy formally defined; future `report.md`
prohibited; case-pair ambiguity prevented for new-format bundles; review-report
role noncanonical; precedence explicit; quarantine separation explicit;
companions point back to the primary; templates/checklists updated; validator
updated without breaking historical evidence; MiniCPM bundles untouched;
engine-kernel policy updated narrowly; Hivemind mirror updated; no inference;
no publication; no stage/commit/push/tag.

## 22. Next human gate

Human review of the unstaged combined diff in `~/Projects/local-llm/welp` (this
milestone's artifact-hierarchy changes plus the pending Context Scaling
changes), then an explicit human decision to commit — recommended as two
separate commits (context-scaling; report-artifact-hierarchy) — before any
future WELP campaign uses the new completion package.
