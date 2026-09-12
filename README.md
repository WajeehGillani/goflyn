# GoFlight Team Memory

A shared team wiki for humans and AI agents: immutable raw notes → LLM-maintained,
interlinked Markdown → answers grounded in compiled knowledge. Every claim will
retain source and contributor attribution, including unresolved contradictions.

**Status: Milestone 1 foundation.** The conversational shell, domain models,
configuration, schema, and empty wiki are ready. Memory operations and LLM calls
are not implemented yet.

## Setup

Requires Python 3.12+ and Git. From this checkout:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
goflight-memory
```

Set optional `GOFLIGHT_USER` in `.env`, pass `goflight-memory --user "Wajeeh"`, or
enter a contributor name at startup. No API key is required. Shell environment
variables override `.env`; `--user` overrides the configured contributor.

The editable install finds this checkout even when launched elsewhere. To select
another checkout, export `GOFLIGHT_ROOT=/absolute/path/to/checkout` before launch;
configuration is read from that checkout's `.env`. Keep `.env` and secrets out of Git.

## Current shell

- `/help`: show commands and current limitations.
- `/status`: show contributor, raw source count, wiki Markdown count, and root paths.
- `/exit`: exit cleanly; Ctrl-C and EOF also exit.

Natural language receives a placeholder response. `/status` initially reports zero
raw sources and two Markdown pages (the index and changelog). `.gitkeep` files are
excluded. Until ingest defines source storage, raw count means non-hidden files
under `memory/raw/`. The shell does not write memory or call an LLM.

## Validation and roadmap

```sh
python -m unittest discover -s tests -v
```

- Milestone 2: immutable source ingest, provenance, wiki compilation, conflicts,
  repository locking, and attributed Git commits.
- Milestone 3: query using page selection, bounded links, and grounded citations.
- Milestone 4: deterministic wiki lint.
- Milestone 5: fictional samples, a short demo, concurrency checks, and hardening.

See [schema.md](schema.md) for page rules and [ARCHITECTURE.md](ARCHITECTURE.md) for
the trust boundary and planned operations.
