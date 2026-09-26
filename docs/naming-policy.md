# WELP naming policy

Canonical protocol name: **WELP** (WumboLabs Evaluation Lifecycle Protocol).

## Current / new work

All new and current-facing artifacts use `WELP` / `welp`:

- docs, READMEs, templates, examples
- new contracts, schemas, reports, Lab Records
- Labs catalog presentation
- WumboCore Lab Records

Do not introduce noncanonical protocol identifiers in current-facing material.

## Report artifact filenames

Campaign report artifacts have fixed role names (full hierarchy and precedence
rules: [Report artifact hierarchy](../protocol/WELP.md#report-artifact-hierarchy)):

- `REPORT.md` — the primary scientific report; exactly one per current campaign bundle.
- `WELP-LAB-RECORD.md` — the standardized Lab Record companion; summarize/index `REPORT.md`, never compete with it.
- `<campaign-slug>-review-report.md` — optional human review summary; a noncanonical convenience document.
- `report.md` — historical: accepted in frozen bundles, prohibited as a future Lab Record name, and never coexisting with `REPORT.md`.

## Frozen provenance

Do not rewrite frozen provenance identifiers. Exact historical snapshot IDs, contract IDs, conformance filenames, campaign directory names, and hash-bound evidence stay as recorded.

## Display names for tests and modules (2026-09-24 hardening II)

WELP tests and modules carry stable machine IDs (fixture IDs, module keys,
contract IDs, file names) and short human-facing display names. Display names
exist so docs, reports and the website read clearly without memorizing
internal taxonomy. Rules:

- Current-facing material (README, docs, protocol notes, templates, website
  text, generated report prose) uses the clear display name.
- Introduce a historical machine ID once, in parentheses, when disambiguation
  helps — e.g. "Controlled Context (legacy ID: Family A 1.3)" — then use the
  display name. Do not repeatedly expose legacy jargon.
- Machine IDs never change: fixture paths, fixture versions, contract IDs,
  module keys, evidence keys and frozen snapshots are provenance. New
  prospective fixtures MAY use clearer IDs if compatibility mapping is
  explicit and validators understand legacy IDs; prefer compatibility aliases
  over breaking historical provenance.
- Frozen historical reports are never rewritten to replace old labels.
- Reviewer-facing evidence (rubric IDs, review packets) may include both the
  display name and the machine ID.

Canonical display-name map (machine ID -> display name):

| Stable machine ID | Display name |
|---|---|
| `welp-useful-context-family-a` fixture (Family A 1.3) | Controlled Context |
| multidocument fixture / `multidocument` module | Multi-Document Context |
| `tool-recovery` / tool-recovery 0.2 module | Tool Recovery |
| `linux-diagnosis` fixture | Linux Diagnosis |
| repository coding fixture (`repository-timeout`) | Repository Repair |
| `multi-turn-correction` fixture | Multi-Turn Correction |
| quality screen (`welp-quality-screen-12-v1`) | Assistant Quality |
| strict structured / JSON-exact tasks | Structured Output |
| long-context performance arms | Long-Context Performance |
| semantic budget lane (reasoning-bearing measurement) | Reasoning Budget |
| `DEPLOYMENT` prompt lane | Deployment Prompt |
| `MINIMAL` prompt lane | Minimal Prompt |
| `PUBLISHER` prompt lane | Publisher Prompt |
| `OPTIMIZED` prompt lane | Optimized Prompt |
| semantic / operational budget lanes | Semantic Budget / Operational Budget |
| `standard` reasoning profile | Standard |
| `reasoning-on` reasoning profile | Reasoning On |
| `reasoning-off` reasoning profile | Reasoning Off |
| `reasoning-<level>` qualified effort profile | Reasoning <Level> (e.g. Reasoning High) |
| `welp-agentic` contract / `sections.agentic` | WELP Agentic |
| the Model section (`sections.model`) | WELP Model |
| `agentic-repository-1` fixture | Agentic Repository Task |
| `agentic-system-1` fixture | Agentic System Task |
| `agentic-research-1` fixture | Agentic Research Task |

Names not on this map follow the rule of thumb: 2–4 clear words, plain English
over jargon, no abstract letter/number-only labels.

## Validator compatibility

The campaign validator may retain historical identifiers where required to validate frozen campaign artifacts. New campaigns must still use WELP identifiers.

## Publication

Human-readable publication uses WELP. Translate internal frozen identifiers to canonical WELP terminology when the exact historical string is not required for reproducibility.
