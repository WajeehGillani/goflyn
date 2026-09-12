# Team Memory Wiki Schema

This document defines wiki maintenance rules. It is not a database schema.

## Pages and naming

Create a page only for an operator, aircraft, or customer supported by useful source
evidence. Do not create pages for greetings, filler, or insignificant information.
Use one page per entity, beginning with `# <canonical name>` (tail number for aircraft).

Paths beneath `memory/wiki/` are `operators/<slug>.md`, `aircraft/<slug>.md`, and
`customers/<slug>.md`. Slugs are lowercase names/tail numbers with punctuation and
whitespace replaced by hyphens. Python owns normalization and collision handling;
never merge ambiguous identities merely because their slugs match. Keep existing
page paths stable when new aliases appear.

Each page starts with its name and `Type: operator|aircraft|customer`, followed by
`## Facts`, `## Related entities`, `## Conflicts`, and `## Sources`. The Facts section
is a Markdown table with columns `Field | Value | Evidence`. Use these field names:

| Page type | Supported fields |
| --- | --- |
| Operator | contacts; minimum_booking_notice; booking_requirements; operating_notes |
| Aircraft | type; operator; home_base; availability; operating_notes |
| Customer | aircraft_preferences; airport_preferences; travel_preferences; operating_notes |

Customer aircraft preferences describe aircraft types/classes, not catering or
cabin activities. Use travel_preferences for catering, comfort, and working in
flight; airport_preferences for departure airports; operating_notes for past trips.
Keep an explicitly combined alternative (e.g. "Teterboro or Westchester") together.

Represent fleet relationships as aircraft `operator` facts. Python generates
reciprocal aircraft/operator links with evidence. Do not infer a relationship from
co-occurrence alone. Omit missing fields rather than asserting invented values.

## Evidence and updates

1. Original raw sources are immutable: preserve their text unchanged. Each source
   has a stable source ID, contributor, source type, and timezone-aware creation time.
2. Every factual wiki claim must cite at least one source beside the claim. Use a
   relative Markdown link followed by the contributor, such as
   `[source-001](../../raw/source-001.md) — John` from an entity page.
   Raw files use `source-NNN.md` with sequential Python-generated IDs. The metadata
   header contains `source_id`, `contributor`, `source_type`, and `created_at`, then
   `---` and one blank separator line precede the exact UTF-8 note body.
3. Never invent missing information or infer an unstated fact as certain.
4. Add new facts; attach additional attributed evidence to matching facts. Earlier
   evidence must remain traceable even after newer evidence arrives.
5. Never silently overwrite contradictory information. Preserve both values and
   their source/contributor evidence; mark the affected claim and the Conflicts
   section **Unresolved** with a stable conflict ID. Recency alone does not resolve
   a contradiction. Only an explicitly confirmed human decision resolves it.
   Compare values using Unicode normalization, case folding, and collapsed whitespace.
   All different values for one entity/field are conservatively conflicting, even
   for potentially multi-valued fields such as contacts or preferences.
6. Link related entities using relative Markdown links to their wiki pages. Links
   express relationships; factual relationship claims still require source evidence.
7. Keep a Sources section listing the evidence used by the page. This supplements
   claim-level citations, not replaces them.
8. Maintain human-readable Markdown. Add entity links under the corresponding
   section of `index.md`; append attributed summaries with source and page links to
   `CHANGELOG.md`. These navigation summaries must not introduce unsupported facts.

The LLM proposes structured entities/facts. Deterministic Python validates provenance,
resolves paths, writes files, and preserves conflicts. Equal normalized values share
one fact row; multiple evidence references are separated by `<br>`. Python escapes
Markdown/HTML metacharacters in textual data so it cannot create page structure.
Conflict sections use stable `### conflict-<hash>` headings, `Field: <field>`, and an
exact `Status: unresolved` or `Status: resolved` line followed by every historical
supported value and its evidence.

## Explicit entity assertions

A direct instruction such as “Add customer Wajeeh” is useful entity-existence evidence.
Store the instruction as a raw source first. An entity-only page keeps the empty Facts
table and adds `Entity assertion: <source/contributor evidence>` under Sources. Merge
duplicate assertions into the existing page; never invent attributes or treat a vague
person mention as evidence of being a customer. No new entity types are introduced.

## Human resolution records

The existing stable conflict ID survives resolution and later reopening. Keep the
original fact rows and competing evidence. Under that conflict's heading, append:

```text
#### Human resolution

Current value: <selected value or qualified human statement>
Reviewer: <identified session user>
Reason: <human explanation>
Resolved at: <timezone-aware ISO timestamp>
Reviewed values: <escaped JSON string array>
Reviewed sources: <source/contributor evidence>
```

Values use the same escaping and evidence syntax as facts. Decision records are
append-only history: the latest decision supplies the current value only while the
conflict is resolved. A new distinct fact value outside its reviewed values reopens
the field; previous decisions remain history. Matching-value evidence does not reopen.
Queries project the active human value instead of treating superseded alternatives as
current facts. Lint counts only unresolved conflicts. One parser/model is shared by
ingest, query, lint, and resolution; the LLM cannot write a resolution. Only explicit
human confirmation writes the page/changelog and creates a scoped Git commit.

Pages and index are generated deterministically. Ingest refuses noncanonical manual
edits instead of silently discarding them. Raw sources must never be edited, including
pending sources retained after failure. Earlier citations always remain intact.
