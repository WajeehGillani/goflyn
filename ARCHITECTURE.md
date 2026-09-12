# Architecture

One local Python application compiles attributed team notes into an inspectable
Markdown wiki. Git holds real development and ingest history; no vector database,
chunk-based RAG, SQL, or agent orchestration framework is used.

```mermaid
flowchart LR
    U[Human / agent] --> C[Conversational CLI]
    C --> R[Intent router]
    R --> I[Ingest]
    R --> Q[Query]
    R --> L[Lint]
    I --> S[Immutable raw sources]
    I --> W[Markdown wiki]
    I --> G[Git commit]
    W --> Q
    W --> L
    Q --> A[Answer + pages used]
    L --> H[Health report]
```

## Storage and trust boundary

`memory/raw/source-NNN.md` stores exact note text with contributor, type, ID, and UTC
timestamp. `memory/wiki/{operators,aircraft,customers}/` stores fact/evidence tables,
related links, conflicts, and sources; `index.md` and `CHANGELOG.md` provide navigation
and attributed summaries. `schema.md` defines supported fields. No hidden state store.

The LLM handles ambiguous routing, structured extraction, optional page selection,
and grounded synthesis. Python validates schema/provenance, owns IDs and safe paths,
reconciles facts, preserves conflicts, writes files, locks, commits, and lints.
Provider responses are proposals, not trusted instructions. Structured output does
not guarantee semantic correctness. Only `llm/client.py` imports the provider SDK.

## Operations

- **Ingest:** exclusive lock → preserve raw text → LLM extraction with schema → validate
  attribution → reconcile facts → render wiki/index/changelog → scoped Git commit.
  Matching normalized values merge evidence; differing values retain both sides and
  produce stable unresolved records. Aircraft/operator facts create reciprocal links.
  Exact same-user/text retries return the original commit. Caught failures restore
  wiki/staging and keep a saved source pending for retry. Dirty memory and unrelated
  staged work block ingestion. No manual edits are silently discarded.
- **Query:** index catalog → exact name match or structured page selection → relevant
  breadth-first traversal → LLM answer → validated citations and conflict notices.
  Only catalogued wiki pages become context; raw notes never do. Limits: 5 pages,
  2 hops, 32 KiB/page, 64 KiB/index. Unsupported answers become unknown; literal
  one-sided conflict answers fail safely. Query never calls Git or writes memory.
- **Lint:** Markdown scanner → recorded-conflict parser → dictionary/set link graph →
  source-reference validation → report. No LLM or writes. Unresolved records and zero
  incoming-link entities are warnings; broken references and malformed state are errors.
  Index/changelog links count; raw/self-links do not. Infrastructure cannot be orphaned.
  Per-page errors preserve the remaining scan; root/lock failures are explicit.

## Concurrency, delivery, and limits

`fcntl.flock` serializes cooperating ingests sharing one repository/filesystem,
including provider calls and Git. Query/lint/status share read locks without creating
lock files; query releases its lock before synthesis. Independent distributed nodes
and manual edits are not protected. Power loss/SIGKILL may need manual recovery;
atomic per-file replacement is not a crash-safe multi-file transaction.

`agent/` owns UX, `core/` operations/models, `wiki/` compilation/parsing, `infra/`
paths/configuration/locking/Git. `demo.py` initializes only a new isolated directory
and feeds fictional notes through production ingest; it never resets existing data.

Limits: whole-wiki reconciliation, bounded query, generated Markdown dialect, no
semantic/temporal resolution, full graph reachability, or grounding proof. Contributor
labels are unauthenticated. No UI, MCP, deployment, or human-resolution workflow.
See the [validation record](docs/VALIDATION.md) for demos and retained extraction errors.
