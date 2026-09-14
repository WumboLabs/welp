# Evaluation publication operating contract

## Four layers

| Layer | Authority and use |
|---|---|
| [wumbolabs.dev/evaluations](https://wumbolabs.dev/evaluations/) | Human-facing discovery, model summaries, and ordinary sharing. |
| [WumboLabs/evaluations](https://github.com/WumboLabs/evaluations) | Canonical public scientific registry, event reports, profile metadata, and public-safe supporting evidence. Exact citations use repository + full commit SHA + relative file path. |
| Local `research/model-evaluations/` | Working science, authoritative campaign reports, raw evidence, and internal audit material. Resolve scientific conflicts here; publish an attributed correction rather than silently rewriting a frozen public event. |
| NAS model archive | Large model artifacts and verified archive manifests; weights are not Git evidence. Formal evaluation uses a verified local artifact copy. |

A profile is a scientific surface, **not a repository boundary**. Never create a new
`eval-*` repository for a model, profile, campaign, or event. Existing legacy repos
are immutable historical provenance, not future publication targets.

## Identity and paths

- `model_id`: stable model identity and one human-facing Evaluation page.
- `profile_id`: materially distinct artifact/quantization, runtime, or deployment
  topology. Multiple events can characterize the same profile.
- `event_id`: globally unique scientific/publication event; retain its date and
  evidence scope. A context-only event cannot supersede unrelated model-role findings.
- Models: `models/<model_id>/model.json` and generated `README.md`.
- Profiles: `models/<model_id>/profiles/<profile_id>/profile.json`, schema
  `wumbolabs-eval-profile/2`, with repository `WumboLabs/evaluations`, matching
  `profile_path`, and explicit `event_ids`.
- Ordinary events: `models/<model_id>/events/<event_id>/REPORT.md`, optional
  public-safe `WELP-LAB-RECORD.md`, structured export, and supporting artifacts.
- Shared comparisons: `shared-events/<shared_event_id>/REPORT.md`, one copy with
  explicit related model/profile IDs. Central shared-event metadata has no owner
  model/profile. `website_attribution` preserves display placement only, not ownership
  or scientific precedence. In an export, `identity.model_id/profile_id` are display
  attribution and the related IDs describe the actual shared scope.

`registry.json` in the central repository owns model/profile/event relationships,
current per-surface attribution, and publication paths. Its generated indexes and
metadata are derivatives. The website's `data/labs-registry.json` is another
reproducible derivative, never a second hand-maintained registry.

## Publish an accepted event

1. Complete the authorized local WELP campaign. Do not start a benchmark, inference,
   LocalMaxxing submission, or model download merely to satisfy publication work.
2. Resolve `model_id`, `profile_id`, `event_id`, date, and actual evidence scope.
   Reuse an existing profile when its material tested surface is unchanged.
3. Produce `summaries/website-publication.json` and the public-safe report. Until
   accepted public evidence exists, record `PENDING_HUMAN_GATE`, no URL/commit/path,
   and proposed target `WumboLabs/evaluations`. Current exports include `identity`.
4. Validate the campaign, publication export, and any new profile descriptor:
   `python3 validators/validate_campaign_welp.py CAMPAIGN`,
   `python3 validators/validate_publication.py EXPORT PROFILE`.
5. Review all publishable bytes. Exclude credentials, private paths/usernames, raw
   prompts/debug logs, raw LocalMaxxing payloads, weights, and Nsight Systems traces.
   Preserve measured values, limitations, classifications, dates, and attribution.
6. Add the public event files to the existing central checkout. Record native
   `publication_provenance` (campaign identity, source artifact, and content digest);
   migration-only legacy provenance must not be invented for new work. Retain old
   immutable events and append corrections with explicit supersession scope.
7. With explicit human Git authorization, inspect scoped working/staged diffs and
   commit the evidence files. A file cannot truthfully contain its own future commit
   SHA: use this evidence commit in the following registry commit.
8. Update central `registry.json`: model/profile relationships, event metadata,
   scoped current-state attribution, `website_event_order`, and `canonical_evidence`
   `{state: "published", repo: "WumboLabs/evaluations", commit: FULL_SHA, path: REPORT_PATH}`.
   A website export uses the same tuple with state `PUBLISHED`. Optional `url` must
   equal `https://github.com/<repo>/blob/<commit>/<path>`. Structured/narrative sources
   carry their own exact commit, relative path, and SHA-256. Update profile `event_ids`.
9. Run central `python3 scripts/validate.py --generate` twice (second run changes
   zero files), then `python3 scripts/validate.py`. This checks identity, references,
   exact Git-object bytes, provenance, path safety, generated indexes, and public
   safety. Inspect, commit, and push the registry/index update under the same gate.
10. Pin the pushed registry's full commit, path, and SHA-256 in website
    `data/evaluations-source.json`. Run `python3 scripts/sync_labs.py` twice (second
    run no-op), `--check`, `selftest`, publication-gap checks, `zola build`, and
    `python3 scripts/check_evaluations_site.py`.
11. Inspect scoped website diffs; commit/push/deploy only with explicit authorization.
    Verify the actual live model page, immutable report/profile links, related
    shared-event pages, and preserved compatibility URLs before marking published.
12. Close the local publication disposition and roadmap entry without altering
    unrelated scientific priorities. Report exact commits/paths and observed results.

## Historical compatibility

Frozen `wumbolabs-labs-publication/1` exports remain valid without optional identity;
legacy `identity.profile_repo` and legacy URL-only evidence retain their original
meaning. Historical repo/commit citations without a central `path` remain historical.
Never reinterpret a legacy repository name as a central path or rewrite frozen
scientific exports to make them current. The website overlays central citations on
in-memory derivatives while retaining exact original export bytes.

Version 1 profile descriptors preserve `first_event` even where its historical alias
was not an indexed event ID. Version 2 uses actual indexed `event_ids`; a retained
`legacy_first_event` is provenance, not a newly manufactured event. Previously
published role vocabulary and absent precision fields are accepted as historical
facts. Optional/null metrics mean unmeasured, not zero; narrow events need not repeat
inherited reliability claims. These compatibility rules do not change WELP science.

Run `python3 validators/validate_publication.py selftest` for immutable-citation,
path, identity, shared-relationship, and legacy acceptance boundaries. The central
validator additionally checks registry-wide uniqueness and referential integrity.

## Sharing and citations

Share the website model URL for ordinary discussion, the central model/profile index
for evidence navigation, and a central **full-commit blob URL** for an exact claim.
A `main` branch URL is discovery, never an immutable scientific citation. Historical
legacy links remain useful provenance and must continue resolving after archival.
Archive notices point to the corresponding central model/profile and website page;
archiving is allowed only after their replacement is pushed and live-verified.
