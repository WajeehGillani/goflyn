# GoFlight Team Memory

A small shared-memory prototype where raw team notes are compiled by an LLM into
an attributed, interlinked Markdown wiki that humans and AI agents can query.
No vector database or chunk-based RAG is used. **Milestones 1–5.1 are complete.**

## What it does

- Ingests immutable notes with contributor attribution and real Git commits.
- Maintains operator, aircraft, and customer pages according to [schema.md](schema.md).
- Preserves conflicting values and evidence; never silently picks the newest.
- Answers from compiled wiki pages and returns the pages used.
- Lints conflicts, orphans, broken links, and missing sources without an LLM or writes.
- Records explicitly confirmed human resolutions without deleting earlier evidence.

## Architecture

Conversation → intent router → `ingest`, `query`, or `lint`; explicit human review → `resolve`.
The LLM interprets text;
Python owns paths, provenance, reconciliation, locking, Git, and lint. See the
[one-page architecture](ARCHITECTURE.md) and [live demo script](DEMO_SCRIPT.md).

## Why Markdown + Git

Memory is readable without this app, citations are inspectable, and every ingest has
a reviewable diff. Raw notes are evidence; wiki pages are compiled knowledge. There
is no hidden database, embedding index, or heavyweight agent framework.

## Requirements and setup

Python **3.12+**, Git, macOS/Linux (`fcntl.flock`), and an OpenAI API key for new
ingestion or nonempty-wiki answers. API calls are billable. From this source checkout:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
cp -n .env.example .env
git config user.name "Your Name"
git config user.email "you@example.com"
```

Edit `.env` to set `OPENAI_API_KEY`. Never commit it. `cp -n` preserves an existing
configuration. The supported install is editable from a Git source checkout.
If `python3.12` is not on PATH, substitute the absolute path to your Python 3.12+
interpreter in the first command; the default macOS `python3` may be too old.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for provider calls; never printed by the app |
| `OPENAI_MODEL` | Defaults to `gpt-4.1-mini` |
| `GOFLIGHT_USER` | Optional contributor label; `--user` overrides it |
| `GOFLIGHT_ROOT` | Export before launch to select another memory repository |

Shell variables override `.env`. A selected repository supplies its own `.env`.
The fresh-demo loader deliberately does **not** copy API keys or `.env` files.

## Run the application

```sh
goflight-memory --user Jack
```

Type new operational knowledge or a question naturally. `/help` explains `/status`,
`/lint`, `/add` (next prompt or inline), `/conflicts`, `/resolve <id>`, and `/exit`. No `/query`, `/ingest`,
or `/history` command is needed; use ordinary Git for history. Each message is
independent, except numbered references to the most recent conflict listing in that session.

## Explicit entity creation

Use `/add new customer Wajeeh`, `/add customer Acme Corp`,
“Add a new customer called Northstar Capital.”, “We have a new operator called
Falcon Air.”, or “Add aircraft N123AB.” These explicit assertions use the same ingest
engine: immutable raw instruction first, structured extraction, wiki/index/changelog,
then Git commit. Only customer/operator/aircraft pages are supported. Entity-only pages
have an empty Facts table and an attributed entity assertion under Sources; no unknown
attributes are invented. Repeating an entity merges provenance into its existing page.
“I spoke with someone named Wajeeh yesterday.” alone does not establish a customer.
The small explicit grammar runs without an LLM; ordinary notes still use extraction.
Previously committed notes are not silently reprocessed or backfilled.

## Human conflict resolution

Conflicts are never automatically resolved. Start with “Show unresolved conflicts.”
(or `/conflicts`), then use one of these forms:

```text
Number 1 should be Westchester. We confirmed the aircraft moved.
Westchester is correct for the N456FC home-base conflict. Falcon Charter confirmed the move.
/resolve <conflict-id>
```

The last form prompts for a value and reason, including a custom qualified statement
such as “24 hours weekdays; 48 hours weekends”. The CLI previews all evidence, the
exact proposed value, your session reviewer name, and reason. Only `yes` writes;
`no` or a blank prompted value cancels. Numbering is session-local; stored IDs are
stable hashes of entity type, normalized name, and field, unchanged from earlier milestones.

Under the existing write lock, `resolve_conflict` rechecks the reviewed evidence,
records reviewer/reason/UTC time and current value, preserves original facts/sources,
appends the changelog, and commits only the affected page and changelog. Stale
confirmations and already-resolved IDs are rejected. Lint stops counting the resolved
record; query uses its current value. New distinct evidence reopens the same ID while
retaining decision history; further evidence for already-reviewed values does not.
Reviewer names are local labels, not authentication. The LLM has no resolution tool.

## Query conflict safety

The guard checks fields relevant to the question or generated answer, not every
conflict on a loaded page. A type question can return “Citation Latitude” despite an
unresolved home base. A base question surfaces all competing values, source/contributor
evidence, and unresolved status, without choosing a winner.

An unsafe relevant-conflict answer triggers exactly one corrective generation with
the competing evidence. If that attempt fails validation or the provider fails, a
deterministic structured-evidence response is returned; no further LLM call or internal
conflict-validation error reaches the user. Current human-resolved values replace
historical alternatives in synthesis context. Query, including retry/fallback, is read-only.
Field relevance and answer checks are conservative lexical heuristics, not a proof
of semantic grounding; unrelated provider/path/schema errors remain explicit errors.

## Load/run the fictional demo

[samples/demo.json](samples/demo.json) contains **nine notes from John and Sarah**:
Atlantic Air / N123GF, SkyBridge Aviation / N777SB, Acme Corp, and Northstar Capital.
They cover aircraft types, bases, booking notice, dated availability, preferences,
past trips, and booking requirements. All operational details are fictional.

The checkout ships with real ingested memory and its original history. Replay the
notes through the **same production ingest function** with:

```sh
python -m goflight_memory.demo
```

Exact committed contributor/text retries reuse their existing source and commit,
so a fully loaded checkout needs no new API calls. An incomplete load resumes on
the same command. Never edit pending raw sources; fix the reported cause and retry.

For a clean demonstration, use a **new isolated directory** (recommended below).
The loader creates empty memory and one real initialization commit, then ingests
each note with the LLM and creates nine attributed runtime commits. It refuses
every existing destination, including empty directories and symlinks. There is no
destructive reset. It copies the schema and configured Git author identity, but no
secrets, user memory, or fabricated history.

## Five-minute demo

After setup above, with Git identity and an API key configured:

```sh
# From the source checkout: create a unique parent, not a reset target.
DEMO_PARENT=$(mktemp -d)
DEMO_ROOT="$DEMO_PARENT/memory-demo"
python -m goflight_memory.demo --fresh "$DEMO_ROOT"

# The new repository has no .env. Enter the key without terminal echo.
export OPENAI_API_KEY="$(python -c 'import getpass; print(getpass.getpass("OpenAI API key: "))')"
export GOFLIGHT_ROOT="$DEMO_ROOT"
git -C "$DEMO_ROOT" status --short
git -C "$DEMO_ROOT" rev-parse HEAD
goflight-memory --user Jack
```

Enter these messages, one at a time:

```text
Would Atlantic Air's aircraft fit Acme Corp's known preferences?
Does Atlantic Air allow pets?
Where is N123GF based?
How much booking notice does Atlantic Air require?
Check the memory for problems.
/lint
/exit
```

Expected: three-page comparison with uncertainty, unknown pet policy, both base
values, both notice values, and matching conversational/slash lint reports.
Aircraft-class consistency and prior trips do not establish current availability,
service suitability, or permission to promise a flight.

```sh
git -C "$DEMO_ROOT" log --oneline
git -C "$DEMO_ROOT" show --stat HEAD
git -C "$DEMO_ROOT" status --short
git -C "$DEMO_ROOT" rev-parse HEAD
unset GOFLIGHT_ROOT
```

Query/lint leave status and HEAD unchanged. Isolated memory is kept for inspection;
no main-checkout data is deleted. To resume it, export its `GOFLIGHT_ROOT` and provide
the key again. A fresh live load took **24 seconds**, and the complete query/lint
sequence **11.3 seconds** in acceptance testing; install/key entry and provider latency
vary. The walkthrough budgets remaining time for inspecting evidence.

## Example interactions and observed results

- “N123GF is available for charter on October 14 and 15, 2026, subject to operator confirmation.” → attributed ingestion.
- “Would Atlantic Air's aircraft fit Acme Corp's known preferences?” → customer,
  operator, and aircraft pages; class comparison and unresolved base/notice.
- “Does Atlantic Air allow pets?” → information absent, not an invented policy.
- “Where is N123GF based?” → Teterboro **and** Westchester; unresolved.
- “How much booking notice does Atlantic Air require?” → 24 **and** 48 hours; unresolved.

The fresh acceptance run had **9 sources, 6 entities, 8 scanned wiki pages, 2
contradictions, and 0 orphan/broken-link/missing-source issues**. Lint intentionally
is not “clean”: the two contradictions demonstrate conflict preservation.

**Historical checkout caveat:** its first source-008 extraction misclassified vegetarian
catering as `aircraft_preferences`, creating a third warning against Challenger-class
aircraft. Evidence and the runtime commit remain intact. Field guidance was clarified;
the fresh run put catering under `travel_preferences`. Milestone 5.1 now automatically
retries unsafe relevant-conflict answers and falls back safely. The historical extraction
mistake remains visible; this milestone does not rewrite old evidence.

## Conflict handling and failures

Values compare by Unicode normalization, case folding, and collapsed whitespace.
Different values for one entity/field retain evidence and become unresolved; recency
is not resolution. Ingest/query/lint/resolve share one structured conflict parser/model.
Lint reports unresolved records, not semantic contradictions inferred by an LLM.
Older status-only resolved records remain lint-readable but cannot supply an authoritative
query value or be silently ingested; full human resolution metadata is required.

Missing keys, refused/invalid model output, unsafe selected paths, malformed pages,
and Git failures produce errors, not success. Caught ingest failures restore wiki
changes/staging; a saved raw note remains pending for exact-text/same-contributor
retry. Dirty memory or unrelated staged changes block ingest. An empty wiki query
returns unknown without an LLM call. `/status` and `/lint` work offline.

## Concurrency model

One repository-level POSIX lock serializes ingest and resolution transactions, including
extraction and commit. Human confirmation occurs before acquiring the write lock and
the reviewed evidence is checked again inside it. Read operations share an existing lock without creating it;
query releases it before synthesis. **Only cooperating writers sharing one repository/
filesystem are protected**, not distributed nodes or manual edits. A waiting writer
blocks until the first finishes. Kill/power loss can require manual Git recovery:
this is not a crash-safe multi-file database transaction.

## Tests

```sh
python -m unittest discover -s tests -v
# Focused orphan demo using temporary fixtures:
python -m unittest discover -s tests -p test_lint.py -v
```

Normal tests use mocked semantic responses and real temporary files/Git; no API is
required. They cover foundation, ingestion, query, lint, routing, retries, safe demo
creation, all nine sample transactions, conflict retry/fallback, entity-only assertions,
human confirmation/cancellation, stale reviews, scoped resolution commits/rollback,
resolved/reopened state, and overlapping writes. The lock test holds
writer A inside extraction, proves B cannot enter, then verifies both contributors'
evidence and commits survive. A separate process-lock test also runs. Orphan tests
omit a temporary entity from the index; infrastructure is excluded and index-only
links count. No orphan fixture is left in the main wiki.

## Design tradeoffs / limitations

- This is an interview prototype, not production-ready or authenticated. Source
  contributor labels differ from Git's locally configured author/committer.
- Structured output validates shape, not semantic truth. [OpenAI guidance](https://developers.openai.com/api/docs/guides/structured-outputs)
  notes that mistakes remain possible; clarified prompts are not a proof.
- No semantic aliases, unit equivalence, temporal supersession, or multi-valued field
  reconciliation. Conservative conflicts can be false positives.
- Queries read only the wiki: up to 5 pages / 2 hops, 32 KiB per page / 64 KiB index.
  Bounded retrieval can miss facts; citation checks are not full entailment checks.
- Generated inline Markdown links only; no fragment-heading validation. Zero incoming
  links define orphans, so disconnected cycles can pass. Read errors can leave a partial graph.
- Lint checks source existence, not sentence-level citation coverage. It never repairs
  files, commits, or calls an LLM. Noncanonical manual edits block ingest.

## What I would build next

With a week: reviewable branches/PRs, richer
schema/entity handling, better retrieval, evaluation/observability, and optional MCP.
UI, authentication, deployment, and heavy orchestration were deliberately not built.
See [SUBMISSION_NOTE.md](SUBMISSION_NOTE.md), [Milestone 5.1 validation](docs/VALIDATION_5_1.md),
[decisions](DECISIONS.md), and the [historical M5 checklist](docs/VALIDATION.md).
