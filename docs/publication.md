# Evaluation publication operating contract (WELP v1.0 successor)

This contract governs how finalized WELP evaluations become public scientific
records. Publication is a deterministic, offline transformation plus an
established central-registry workflow — never an evaluation step, and never a
gate on the evaluation core.

## Four layers

| Layer | Authority and use |
|---|---|
| [wumbolabs.dev/evaluations](https://wumbolabs.dev/evaluations/) | Human-facing discovery, model summaries, and ordinary sharing. A deterministic derivative of the central registry. |
| [WumboLabs/evaluations](https://github.com/WumboLabs/evaluations) | Canonical public scientific registry: event reports, profile metadata, and public-safe supporting evidence. Exact citations use repository + full commit SHA + relative file path. |
| Local `research/model-evaluations/` tree | Working science, authoritative campaign reports, raw evidence, and internal audit material. Scientific conflicts resolve here; publish an attributed correction rather than rewriting a frozen public event. |
| External model archive | Large model artifacts and verified archive manifests; weights are never Git evidence. Formal evaluation uses a verified local artifact copy. |

A profile is a scientific surface, **not a repository boundary**. Never create
a new `eval-*` repository for a model, profile, campaign, or event. Historical
repositories are immutable provenance, not future publication targets.

## Identity

- `model_id`: stable model identity and one human-facing Evaluation page.
- `profile_id`: materially distinct artifact/quantization, runtime, or
  deployment topology. Multiple events can characterize the same profile.
- `event_id`: globally unique scientific/publication event; WELP campaigns
  export with `event_id = campaign_id` and `event_type =
  welp-recharacterization`. A context-only event cannot supersede unrelated
  model-role findings.

Registry paths: `models/<model_id>/model.json`,
`models/<model_id>/profiles/<profile_id>/profile.json` (schema
`wumbolabs-eval-profile/2`, explicit `event_ids`), and ordinary events at
`models/<model_id>/events/<event_id>/REPORT.md` with the structured export.
`registry.json` in the central repository owns model/profile/event
relationships; generated indexes and the website's `data/labs-registry.json`
are reproducible derivatives, never a second hand-maintained registry.

## Standing closeout flow

**Evaluation → verify → review → HUMAN_ACCEPTED → automatic public-safe
publication, with no second approval.**

1. **Evaluate.** Complete the authorized WELP campaign. Never start a
   benchmark, inference, or download merely to satisfy publication work.
2. **Verify.** Every section must finalize and replay-verify:
   `python3 -m welp_next validate --campaign CAMPAIGN` exits 0. Then export:
   `python3 -m welp_next.publication CAMPAIGN DEST` produces the canonical
   `wumbolabs-labs-publication/1` envelope with independent `welp_sections`
   and `profile_conditions` facets. The export requires an existing
   disposition in `summaries/website-publication.json` and retains it:
   `WEBSITE_READY`, `WEBSITE_PUBLISHED`, `WEBSITE_BLOCKED`, or
   `NOT_FOR_PUBLICATION`. Unreviewed exports stay at
   `PENDING_HUMAN_GATE` evidence state and cannot invent a public citation.
   Excluded and missing identities remain explicit rows: `NOT_RUN`, no numeric
   score, frozen exclusion reason, technical applicability, coverage impact,
   attempted/not-attempted and original outcome where present. Valid but
   non-evaluable attempts retain their original facets; they are not zeros or
   semantic failures. Exporting a partial inventory is technical reporting,
   not scientific completion or permission to publish. Explicit holds remain.
3. **Review.** A human scientific review of the finalized, verified record is
   performed outside the framework. The operator records the decision as a
   receipt, schema `welp-scientific-acceptance/1`:
   - `decision`: exactly `HUMAN_ACCEPTED`;
   - `campaign_id`: the reviewed campaign (must match the export);
   - `reviewed_at`: `YYYY-MM-DD`;
   - `basis`: public-safe prose describing the scientific acceptance basis;
   - `review_source_sha256`: SHA-256 of the private original decision source,
     bound by hash. Source bytes are never exported;
   - `section_manifests`: `{section: manifest_sha256}` covering exactly the
     export's finalized sections.
   - For `helicopterbench/3` only, `helicopterbench_human_review_sha256`: the
     exact completed, reconciled human-review sidecar digest. This additional
     binding prevents replacing a review while retaining the same automated
     section manifest. Historical /1 and /2 receipts do not gain this requirement.
4. **Apply acceptance.** Export again with
   `--acceptance RECEIPT.json --review-source DECISION_SOURCE`. The module
   binds the decision to the evidence and fails closed unless: the receipt is
   a recognized `HUMAN_ACCEPTED` receipt for this campaign with a valid date
   and non-empty basis; the decision source hash matches; every section is
   `REAL_MODEL` (only actual model findings enter public closeout); the
   receipt's section manifests equal the export's manifest hashes; no unit
   carries an unresolved technical `INVALID` outcome; and the export passes
   the public-safety scan. There is no approval flag: a plain export of a
   held or unreviewed campaign can never publish. Existing explicit holds do
   not disappear through acceptance — `WEBSITE_BLOCKED` requires resolving
   the exceptional website hold first. Only the default NOT_FOR_PUBLICATION
   development hold may advance through acceptance; an explicit nonpublication
   reason requires separate correction. An accepted export gains disposition
   `WEBSITE_READY` with the embedded `scientific_acceptance` receipt and
   reason "HUMAN_ACCEPTED scientific review; routine public-safe publication
   is standing-authorized."
   HelicopterBench /3 additionally requires the separately attributed human review
   to be finalized, with all questions answered and material disagreements
   resolved. Its independent /100 score remains separate from the automated /100
   result; the acceptance overlay never averages or replaces either result.
   If generation produced no admissible submission, the human channel is
   `NOT_APPLICABLE_NO_SUBMISSION`: no game was played and neither a human
   score nor a gameplay score is invented. Scientific acceptance still binds
   the original generation/budget finding and section manifest. This exception
   cannot conceal an existing scored game or waive review of a submitted game.
5. **Publish.** Under the standing automatic-closeout authorization, commit
   the public-safe evidence to `WumboLabs/evaluations` (recording native
   `publication_provenance`; no invented legacy provenance), update central
   `registry.json` with the immutable `{state: "published", repo, commit,
   path}` citation, run the central validator twice plus its checks, pin the
   registry commit for the website, and run the website sync/validation
   chain (`sync_labs.py` twice + `--check` + selftest + `zola build` + site
   checks). Inspect scoped diffs at each commit. Verify the live model page
   and immutable links, then close the local publication disposition.

### Captured HelicopterBench gameplay

When genuine captured footage exists, provide `--gameplay-media DESCRIPTOR`.
The descriptor includes `video_path` (private local input only), complete `sha256`,
`event_id`, `profile_id`, `methodology`, `game_sha256` and `model_artifact_sha256`.
The producer binds these to the finalized event and extraction record, verifies
the complete checksum, and uses ffprobe to require positive-duration H.264 MP4.
Copy those exact bytes to website
`static/media/evaluations/<event_id>/gameplay.mp4`; the public export contains the
event-specific URL/hash, dimensions and duration, never the private input path.
The website verifies bytes and attribution and renders a controls-enabled player.
Verify actual browser playback before promotion. Footage is supplementary to
objective scoring and must be actual independent execution of the evaluated game,
not repaired, reference or synthetic footage. Historical /1 remains separate.
If genuine footage is unavailable, record `--gameplay-unavailable-reason` instead.
Never replace missing footage with another event's video.

The operator executes this finite closeout using the existing registry and site
commands, returns the verified public URLs and stops. There is no daemon, second
registry or new approval service.

## What never enters an export

Credentials, private host paths/usernames or home directories, raw
prompt/debug payloads, model weights, internal filesystem paths, loopback
URLs, GPU serials/UUIDs, or any key-like material. `publication.public_safe`
rejects such values outright instead of silently redacting; a rejected value
requires operator review, not suppression. Exports retain measured values,
limitations, classifications, dates, attribution, manifest/profile references
and report hashes. Missing metrics remain unknown, never zero; negative and
budget-limited outcomes remain explicit. No composite or universal model
score is fabricated.

## Compatibility and corrections

Frozen `wumbolabs-publication/1` exports remain valid without optional
identity; legacy identity fields retain their original meaning. Never
reinterpret legacy repository names as central paths, and never rewrite
frozen scientific exports to make them current. Retain old immutable events;
append corrections with explicit supersession scope and an attributed,
citable correction event. Optional/null metrics mean unmeasured, not zero.
A `main`-branch URL is discovery, never an immutable scientific citation —
cite the central full-commit blob URL for an exact claim.
