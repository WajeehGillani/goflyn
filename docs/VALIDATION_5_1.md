# Milestone 5.1 validation — 2026-09-12

## Defects and scope

The old query loop scanned every loaded page's conflicts, appended all of them to
every answer, and raised a user-visible error for a literal one-sided answer. It had
no corrective generation or deterministic recovery. The new check uses question/answer
field relevance, one corrective attempt, and structured-evidence fallback.

The CLI supported only bare `/add` followed by a note; inline `/add ...` was unknown.
More fundamentally, reconciliation kept entities only when referenced by facts or a
fleet relationship. An explicit entity assertion with no attributes was dropped.
Explicit supported assertions now yield a structured entity after immutable raw
storage and pass through the existing compiler with entity-existence provenance.

Human decisions now use the existing stable entity/type/field hash IDs and repository
lock. The CLI previews evidence/value/reviewer/reason and requires yes. Resolution
preserves raw notes/facts, adds typed decision history, updates the changelog, and
commits only those two files. Shared parsing keeps ingest/query/lint/resolve consistent.
No optional product feature, new database, or automatic AI truth resolution was added.

## Real ten-scenario acceptance

Ran the production CLI with the configured `gpt-4.1-mini`, using the exact two Falcon
Charter notes from the brief. John supplied the first, Sarah the second, and Wajeeh
performed the confirmed resolution. Calls used the configured key without printing
or copying it. Assertions inspected actual filesystem state and real Git history.

Repository retained at `/private/tmp/goflight-m51-acceptance.SmmXlA/memory`.
This is an isolated, initially empty repository, not a reset of the user's checkout.
The temporary directory may eventually be removed by the operating system.

| Scenario | Observed result |
| --- | --- |
| 1. Clean ingest | Falcon Charter and N456FC created; Citation Latitude, Teterboro Airport, and 24-hour notice attributed; zero conflicts |
| 2. Later Westchester note | New source; original text unchanged; one home_base conflict; both values retained |
| 3. Base query | Both full airport names, source IDs/contributors, unresolved status, wiki citation; no validator error |
| 4. Type query | “The aircraft N456FC is a Citation Latitude.” No home-base warning |
| 5. Lint | One attributed N456FC.home_base contradiction; zero orphan/broken-link/missing-source issues |
| 6. Human resolution | Natural named request expanded Westchester to Westchester County Airport; full preview then yes; reviewer Wajeeh, reason and UTC time recorded; real two-file commit |
| 7. Resolved query | Westchester County Airport, no unresolved-base warning; historical alternative excluded from synthesis |
| 8. Lint again | Zero contradictions and no other issues |
| 9. `/add new customer Wajeeh` | source-003 stores `new customer Wajeeh`; customer page and index entry created; empty Facts table; Wajeeh attribution |
| 10. Vague person mention | No new customer or added entity evidence; existing customer bytes unchanged |

Raw notes were byte-identical before/after resolution; original aircraft fact objects
were identical. Inspected resolution metadata, customer page, index, changelog and
commit diffs. Query/lint snapshots proved unchanged memory bytes and HEAD; final
isolated Git status was clean. The first resolved answer correctly returned the base
but conflated the reviewer with the operator named in the reason. Prompt wording was
tightened; a live recheck named Wajeeh as reviewer, Falcon Charter as the confirming
operator, and still changed no files/history. This remains a semantic model limitation,
not evidence that prompts guarantee attribution.

### Actual runtime commits in the isolated repository

- Clean ingest: `1345757a28f4fc9f13f5081a878bebee381bdb7e`
- Conflict ingest: `5241c6bf9577d834d94320724f0768f640f5c02e`
- Human resolution: `58e167e80ef0c937e412a5c62ac7ea9679812e26`
- Entity assertion: `c814d795a428c0a75635069eb13dbd109a5b5546`

The resolution commit modifies only `memory/wiki/aircraft/n456fc.md` and
`memory/wiki/CHANGELOG.md`. It is separate from both ingest commits and the final
development commit. No earlier history was squashed.

## Existing user checkout preserved

Started from `8ae24ee` with 12 raw notes, including the user's source-010 entity
instruction and source-011/source-012 Falcon notes. All those notes, wiki bytes, and
runtime commits remained unchanged. Existing lint still reports four unresolved
conflicts and zero other issues; they were not silently resolved for a clean report.

Live queries on the existing N456FC page returned both unresolved bases and Citation
Latitude without errors. The type answer volunteered a complete base warning; the
answer-reliance guard consequently retained it. The guard does not require that
warning for a type-only answer, as the clean acceptance run and regression prove.
Already-committed entity instructions are not retroactively compiled; a new explicit
assertion can add the missing entity with new provenance.

## Automated verification

`.venv/bin/python -m unittest discover -s tests -v`: **124 tests passed** in 25.279s.
No live provider is required by ordinary tests. Temporary real Git repositories cover:

- Complete/incomplete relevant conflicts, exactly one retry, corrected output, repeated
  failure/provider error/invalid-citation fallback, unrelated fields, unknown answers,
  both-values-but-winner rejection, hidden internal errors, read-only retries/fallback.
- All supported entity examples, inline CLI ingest, source/contributor retention,
  empty Facts, duplicate provenance merge, and rejection of ungrounded entity-only
  provider proposals for a vague person mention.
- Stable lookup, existing/custom human values, preserved evidence and metadata,
  invalid/already-resolved requests, preview before writes, yes/no/blank cancellation,
  numbered and named selection, stale evidence rejection, real scoped commits,
  commit-failure rollback, unrelated work exclusion, and the shared write lock.
- Resolved query/lint behavior, later ingest preserving a decision, new distinct
  evidence reopening the same ID, and multiple historical human decisions.
- Earlier foundation, ingest, retrieval, lint, safe-path, nine-note demo, idempotency,
  and cross-thread/process locking regressions.

`git diff --check` and `python -m compileall -q src tests` passed. No formatter/linter
is configured; no new formatting dependency was added. Architecture review checked
shared state ownership, LLM/human authority boundaries, bounded recovery, stale review,
scoped rollback, and source preservation without redesigning the application.
The editable installation was refreshed successfully to 0.5.1 using the declared
isolated build backend, and the CLI entry point was checked. A first attempt without
build isolation found no local setuptools backend; the standard isolated build succeeded.

## Remaining limits

Lexical field relevance/answer checks and the explicit command grammar are bounded,
not semantic entailment or arbitrary natural-language parsing. Extraction and synthesis
can still make semantic mistakes. Conflicts remain conservative normalized-string
comparisons; aliases, temporal policies, and multi-valued semantics are not solved.
Local reviewer labels are unauthenticated. Locks protect cooperating writers on one
filesystem, not distributed nodes or manual edits; abrupt termination can require
manual multi-file/Git recovery. Historical status-only resolved records lack a usable
current value and require review, not automatic migration. Existing memory is not
backfilled or rewritten.
