# GoFlight Team Memory

A shared team wiki for humans and AI agents: immutable raw notes → LLM-maintained,
interlinked Markdown → answers grounded in compiled knowledge. Every claim will
retain source and contributor attribution, including unresolved contradictions.

**Status: Milestone 3 complete — grounded wiki queries and attributed ingestion.** Notes become
source-attributed wiki facts and real Git commits; questions receive wiki-grounded
answers and page citations. Lint (Milestone 4) and human conflict resolution are not implemented.

## Setup

Requires Python 3.12+, Git, and macOS/Linux (the lock uses `fcntl.flock`). From this checkout:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. `OPENAI_MODEL` defaults to `gpt-4.1-mini` for small
structured extraction, routing, page selection, and answer calls. The OpenAI SDK is the sole provider
dependency; requests use [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and disable response storage. Normal ingestion sends the note for routing and again
with the schema for extraction. `/add` skips the routing call. API usage is billable.

Configure a Git author/committer if one is not already set:

```sh
git config user.name "Your Name"
git config user.email "you@example.com"
goflight-memory --user "John"
```

Or launch `goflight-memory` and enter a contributor name. Optional `GOFLIGHT_USER`
in `.env` supplies a default. Shell variables override `.env`; `--user` overrides
the configured contributor. Each note is independent; conversational context is
not inferred from earlier messages.

The editable install finds this checkout even when launched elsewhere. To select
another checkout, export `GOFLIGHT_ROOT=/absolute/path/to/checkout` before launch;
configuration is read from that checkout's `.env`. Keep `.env` and secrets out of Git.

## Current shell

- `/help`: show commands and current limitations.
- `/status`: show contributor, raw source count (including pending notes), entity
  page count, unresolved conflict count, and root paths.
- `/add`: enter a note on the next prompt to force the same ingest pipeline.
- `/exit`: exit cleanly; Ctrl-C and EOF also exit.

Enter a meaningful statement about an operator, aircraft, or customer to ingest it.
Ask a question naturally to query the wiki. Low-confidence classifications and general
conversation do not write memory. The ingest API also supports multiline text without
trimming or changing it: `ingest(text, contributor, paths=paths, client=client)`.

## Querying compiled knowledge

`query(question, paths=paths, client=client)` reads **compiled Markdown wiki pages**.
It does not read raw historical notes, generate embeddings, or use a vector database.
The index supplies a catalog of entity labels and paths. Exact name matches select
pages directly; otherwise one structured LLM call selects only catalogued paths.
Related links are followed when the question names the target or asks about its
relationship type (e.g. aircraft, operator, or fit). A pet-policy question about an
operator does not automatically load all linked aircraft.

Traversal is breadth-first, deduplicated, and capped at **5 pages and 2 link hops**.
Page files are capped at 32 KiB each and the index at 64 KiB; oversized files fail
clearly rather than being truncated. Raw-source, external, invented, escaping, and
symlink paths cannot become query context. The parser supports the inline links
emitted by ingestion, not every Markdown dialect.

One answer call receives only those selected pages. The model must report missing
information and qualify uncertain comparisons. A structured `supported=false`
result becomes an explicit "not currently in memory" answer; it cannot emit a
positive unsupported policy. Python validates cited paths and appends unresolved
values from the consulted pages even if the model omits them. Answers that mention
only one literal side of a known conflict are rejected. This is a useful guard,
not a proof of semantic entailment: faithful synthesis still depends on the LLM.
Conservative conflict notices may include other unresolved fields on the same page.

`Pages used` lists validated wiki-relative paths (clickable in terminals supporting
OSC 8 links). The evidence chain remains answer → wiki page → source → contributor.
Queries never save conclusions, edit memory, or create Git commits. An existing
ingest lock is opened read-only/shared while collecting context; the answer call
uses that in-memory snapshot after releasing it. Query does not create a lock file.
If an ingest starts while reading a checkout with no existing lock, the query fails
with a retry message. Independent manual edits are not coordinated by this lock.

Retrieval is deliberately bounded, so a broad question can miss facts outside the
selected pages. Use explicit entity names for predictable discovery; semantic
aliases and arbitrary relationship wording are not exhaustively handled.

## Storage, conflicts, and failures

Raw files are `memory/raw/source-001.md`, etc. Each has a quoted metadata header
and the exact original note body. Python allocates IDs under the repository lock
and uses exclusive creation. Wiki pages contain readable fact tables, relative
entity links, evidence references, and visible unresolved conflict sections.
Matching values merge evidence. Different values for the same entity/field preserve
both sides; recency does not pick a winner. Values compare by Unicode normalization,
case folding, and collapsed whitespace, with no semantic alias or unit matching.

Runtime commits say `ingest source-NNN by Contributor`, with source, contributor,
pages, and conflict count in the message. The Git author/committer uses local Git
configuration; the source contributor is a separate user-supplied label, not an
authenticated identity. Only explicit ingest-owned files are staged/committed.
Unrelated unstaged work is left alone; existing staged changes or dirty memory block
ingestion. `.env` and the persistent lock file are ignored.

On extraction, validation, write, or commit failure, the CLI reports failure and
restores wiki files and ingest-owned staging. A fully saved raw source remains
immutable and uncommitted. Retry its **exact original text with the same contributor**
to reuse that source ID. Other notes are blocked while it is pending. Successful
exact retries return the existing source/commit without another LLM call through
`/add` (natural input may still incur routing). This deliberately treats identical
text from the same contributor as a retry; a different contributor adds new evidence.

The lock serializes writers sharing one checkout, including the LLM request and Git
commit. It does not coordinate independent/distributed filesystems. Caught failures
roll back; process termination/power loss or rollback failure may require manual Git
inspection/recovery. A lock is not a crash-safe multi-file transaction. Ingest refuses
unsupported manual wiki/index edits instead of replacing them.

## Two-source manual demo (real API, opt-in)

With the key configured, launch `goflight-memory --user John` and enter:

> I spoke with Atlantic Air. They operate N123GF, which is a Challenger 350 based at Teterboro. They require 24 hours notice for bookings.

Exit and launch `goflight-memory --user Sarah`, then enter:

> Atlantic Air told me N123GF is now based at Westchester and they require 48 hours notice.

On an empty memory these create `source-001` and `source-002`, two entity pages,
and unresolved `home_base` and `minimum_booking_notice` conflicts. Use `/status`;
inspect `memory/raw/`, `memory/wiki/aircraft/n123gf.md`,
`memory/wiki/operators/atlantic-air.md`, `index.md`, and `CHANGELOG.md`.
Run `git log --oneline` to see both runtime commits separately from development history.
On a populated memory IDs continue sequentially; exact repeated notes are idempotent.

## Query demo (real API, opt-in)

After the two-source ingest demo, use Sarah's CLI to ingest:

> Acme Corp prefers Challenger-class aircraft and departures from Teterboro or Westchester.

Then launch `goflight-memory --user Wajeeh` and ask:

- What do we know about Atlantic Air?
- Would Atlantic Air's aircraft fit Acme Corp's known preferences?
- Does Atlantic Air allow pets?
- Where is N123GF based?

Expect page citations, a qualified comparison spanning customer/operator/aircraft
pages, unknown pet policy, and both unresolved home-base values. Check `git status`
and `git log --oneline` before and after: these questions make no memory changes or commits.

## Validation and roadmap

```sh
python -m unittest discover -s tests -v
```

- Tests mock LLM calls and use real temporary Git repositories; no API key/network
  is required. They cover ingestion, retries, concurrent writes, query discovery and
  bounds, path/citation validation, conflicts, unknown answers, and read-only behavior.
- Milestone 4: deterministic wiki lint.
- Milestone 5: fictional samples, a short demo, concurrency checks, and hardening.

See [schema.md](schema.md) for page rules and [ARCHITECTURE.md](ARCHITECTURE.md) for
the trust boundary and planned operations.
