# Team Memory Wiki Schema

This document guides future wiki maintenance. It is not a database schema.

## Pages and naming

Create a page only for an operator, aircraft, or customer supported by useful source
evidence. Do not create pages for greetings, filler, or insignificant information.
Use one page per entity, beginning with `# <canonical name>` (tail number for aircraft).

Paths beneath `memory/wiki/` are `operators/<slug>.md`, `aircraft/<slug>.md`, and
`customers/<slug>.md`. Slugs are lowercase names/tail numbers with punctuation and
whitespace replaced by hyphens. Python owns normalization and collision handling;
never merge ambiguous identities merely because their slugs match. Keep existing
page paths stable when new aliases appear.

Use these level-two sections; leave unknown sections empty or write `Unknown`.

| Page type | Sections |
| --- | --- |
| Operator | Contacts; Booking requirements; Operating notes; Aircraft; Sources; Conflicts |
| Aircraft | Type; Operator; Home base; Availability; Operating notes; Sources; Conflicts |
| Customer | Aircraft preferences; Airport preferences; Travel preferences; Operating notes; Sources; Conflicts |

## Evidence and updates

1. Original raw sources are immutable: preserve their text unchanged. Each source
   has a stable source ID, contributor, source type, and timezone-aware creation time.
2. Every factual wiki claim must cite at least one source beside the claim. Use a
   relative Markdown link labeled with the source ID and contributor, such as
   `[<source_id> — <contributor>](../../raw/<source-file>)` from an entity page.
   This is a link template; the raw filename format will be defined with ingest.
3. Never invent missing information or infer an unstated fact as certain.
4. Add new facts; attach additional attributed evidence to matching facts. Earlier
   evidence must remain traceable even after newer evidence arrives.
5. Never silently overwrite contradictory information. Preserve both values and
   their source/contributor evidence; mark the affected claim and the Conflicts
   section **Unresolved** with a stable conflict ID. Recency alone does not resolve
   a contradiction. Human review is required; resolution is not implemented yet.
6. Link related entities using relative Markdown links to their wiki pages. Links
   express relationships; factual relationship claims still require source evidence.
7. Keep a Sources section listing the evidence used by the page. This supplements
   claim-level citations, not replaces them.
8. Maintain human-readable Markdown. Add entity links under the corresponding
   section of `index.md`; append attributed summaries with source and page links to
   `CHANGELOG.md`. These navigation summaries must not introduce unsupported facts.

The LLM proposes semantic content. Deterministic Python validates provenance,
resolves paths, writes files, and preserves conflicts. This milestone defines the
contract only; it does not enforce persisted wiki content yet.
