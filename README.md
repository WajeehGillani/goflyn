# GoFlight Team Memory

GoFlight Team Memory is a small command-line shared memory for flight operations.
It turns team notes into an attributed Markdown wiki, answers questions from that
wiki, flags conflicting facts, and lets a human reviewer resolve conflicts with
an auditable Git commit.

The memory is just files plus Git. Raw notes are preserved as evidence, wiki pages
are readable Markdown, and every ingest or human resolution creates a normal commit.

## Quick Start

Requirements:

- Python 3.12+
- Git
- macOS or Linux
- An OpenAI API key for ingesting notes and answering questions from a nonempty wiki

From a fresh clone:

```sh
git clone https://github.com/WajeehGillani/goflyn.git
cd goflyn
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
cp -n .env.example .env
git config user.name "Your Name"
git config user.email "you@example.com"
```

Edit `.env` and set:

```sh
OPENAI_API_KEY=your_api_key_here
```

Then start the app:

```sh
goflight-memory --user "Your Name"
```

If `python3.12` is not on your PATH, use the absolute path to any Python 3.12+
interpreter. The default macOS `python3` may be too old.

## Basic Use

Inside the app, type operational notes or questions naturally:

```text
N456FC is a Citation Latitude operated by Falcon Charter.
Falcon Charter requires 24 hours booking notice.
Where is N456FC based?
Check the memory for problems.
```

Useful commands:

```text
/help        Show available commands
/status      Show contributor, memory counts, and repository paths
/add         Add a note using the next prompt
/add ...     Add an inline note or explicit entity assertion
/lint        Check wiki health without writes or LLM calls
/conflicts   List unresolved conflicts
/resolve ID  Review and resolve one conflict after explicit confirmation
/exit        Exit
```

Most of the time you do not need a command. Notes are routed to ingest, questions
are routed to query, and requests such as "check memory health" are routed to lint.

## What Gets Stored

The repository contains a `memory/` directory:

```text
memory/
  raw/        Immutable source notes
  wiki/       Compiled Markdown pages for operators, aircraft, and customers
  CHANGELOG.md
```

Supported entity types are:

- `operator`
- `aircraft`
- `customer`

Supported fields are defined in [schema.md](schema.md). The app preserves source
IDs and contributor labels so every wiki fact can be traced back to the raw note
that produced it.

## Adding Notes

Add normal operational knowledge by typing it in the shell:

```text
Acme Corp prefers Challenger-class aircraft and Teterboro departures.
N123GF is based at Teterboro Airport.
```

Every successful ingest:

- saves the raw note first;
- extracts supported entities and facts;
- updates wiki pages and the index;
- appends the changelog;
- creates a Git commit.

If an ingest fails after saving a raw note, retry the same text with the same
contributor. The app reuses the pending source instead of duplicating it.

## Explicit Entity Creation

You can create empty, attributed entity pages without inventing facts:

```text
/add new customer Wajeeh
/add customer Acme Corp
Add a new operator called Falcon Air.
We have a new aircraft N123AB.
```

These assertions still go through the same ingest path and create source-backed
wiki pages. Repeating an existing entity merges the new provenance into the page.
Vague mentions such as "I spoke with someone named Wajeeh" do not create a customer.

## Asking Questions

Queries answer only from compiled wiki pages. The app does not use general world
knowledge, raw notes, or hidden vector search to fill gaps.

Example:

```text
Where is N456FC based?
```

The answer includes the wiki pages used. If the requested information is missing,
the app says it is not currently in memory.

If a question depends on an unresolved conflict, the answer must show the competing
values and say the field is unresolved. The query path is read-only; retries and
fallbacks do not modify memory or create commits.

## Checking Health

Run:

```text
/lint
```

Lint is deterministic and offline. It checks for:

- unresolved conflicts;
- orphan pages;
- broken wiki links;
- missing source files;
- malformed conflict or resolution records.

Lint never calls the LLM, repairs files, or writes commits.

## Resolving Conflicts

Conflicts are preserved until a human reviewer explicitly resolves them.

Start by listing conflicts:

```text
/conflicts
```

Then resolve by ID:

```text
/resolve conflict-477276a53cd8f9e2
```

Or use the latest numbered listing:

```text
Number 1 should be 24 hours. Sarah confirmed this is the current booking notice.
```

Before writing, the CLI previews the competing evidence, proposed value, reviewer,
and reason. Only typing `yes` writes the resolution. `no` or a blank prompted value
cancels.

A resolution commit records:

- current reviewed value;
- reviewer label;
- reason;
- UTC timestamp;
- reviewed competing values and sources.

Original facts and evidence stay on the page. If a later note introduces a new
distinct value for the same field, the same stable conflict ID reopens with its
history preserved.

## Configuration

Settings come from `.env` and shell environment variables:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required for LLM-backed ingest/query |
| `OPENAI_MODEL` | Optional; defaults to `gpt-4.1-mini` |
| `GOFLIGHT_USER` | Optional contributor label; `--user` overrides it |
| `GOFLIGHT_ROOT` | Optional path to a different memory repository |

Shell variables override `.env`. Keep `.env` out of Git.

## Using Another Memory Repository

By default, the app uses the current checkout as the memory repository. To point
the CLI at another repository:

```sh
export GOFLIGHT_ROOT=/path/to/memory-repo
goflight-memory --user "Your Name"
```

That repository should be initialized with Git and contain the expected `memory/`
layout. The demo loader can create a clean example repository if you want to inspect
the file layout before using your own data.


## Development

Run the test suite:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The tests use temporary files, temporary Git repositories, and mocked LLM responses;
they do not require an API key.

Helpful docs:

- [schema.md](schema.md) explains the wiki format and supported fields.
- [ARCHITECTURE.md](ARCHITECTURE.md) describes the main design.
- [DEMO_SCRIPT.md](DEMO_SCRIPT.md) contains a fuller walkthrough.
- [docs/VALIDATION_5_1.md](docs/VALIDATION_5_1.md) records the latest challenge validation.
- [DECISIONS.md](DECISIONS.md) records implementation decisions.

## Current Limits

This is a local prototype, not a hosted multi-user service.

- Contributor names are local labels, not authentication.
- Only operator, aircraft, and customer entities are supported.
- Conflict detection is field-based and conservative; it does not understand every
  semantic alias, unit conversion, or temporal supersession.
- Query retrieval is bounded and reads only compiled wiki pages.
- The repository lock protects cooperating local writers on one filesystem, not
  distributed nodes or manual edits.
- Structured model output validates shape, not semantic truth.
