# GoFlight Team Memory

A shared team wiki for humans and AI agents: immutable raw notes → LLM-maintained,
interlinked Markdown → answers grounded in compiled knowledge. Every claim will
retain source and contributor attribution, including unresolved contradictions.

**Status: Milestone 2 complete — attributed ingestion.** Natural-language notes become
source-attributed wiki facts and real Git commits. Query (Milestone 3), lint
(Milestone 4), and human conflict resolution are not implemented.

## Setup

Requires Python 3.12+, Git, and macOS/Linux (the lock uses `fcntl.flock`). From this checkout:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. `OPENAI_MODEL` defaults to `gpt-4.1-mini` for small
structured extraction and routing calls. The OpenAI SDK is the sole provider
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
Questions receive the Milestone 3 notice. Low-confidence classifications and general
conversation do not write memory. The core API also supports multiline text without
trimming or changing it: `ingest(text, contributor, paths=paths, client=client)`.

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

## Validation and roadmap

```sh
python -m unittest discover -s tests -v
```

- Tests use mocked extraction plus real temporary Git repositories; no API key/network
  is required. They include failures, source immutability, provenance, locks, and concurrent writes.
- Milestone 3: query using page selection, bounded links, and grounded citations.
- Milestone 4: deterministic wiki lint.
- Milestone 5: fictional samples, a short demo, concurrency checks, and hardening.

See [schema.md](schema.md) for page rules and [ARCHITECTURE.md](ARCHITECTURE.md) for
the trust boundary and planned operations.
