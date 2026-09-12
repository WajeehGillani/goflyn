# Final challenge validation — 2026-09-12

## Verified requirement checklist

- [x] Compact architecture document with Mermaid diagram — ARCHITECTURE.md.
- [x] Schema document aligned with generated sections and allowed fields — schema.md.
- [x] Ingest — nine fictional notes passed through production `ingest`, using the real LLM.
- [x] Query — real multi-page, unknown-policy, home-base, and booking-notice queries ran.
- [x] Lint — natural requests and `/lint` invoke the same deterministic core.
- [x] Query returns wiki pages used — operator/customer/aircraft in the comparison.
- [x] Lint reports contradictions — both intended conflicts in fresh memory.
- [x] Lint reports orphan pages — temporary fixture tests, without main-memory damage.
- [x] 8–10 fictional raw sources — nine, with exact bodies checked against samples/demo.json.
- [x] At least two contributors — John (four notes), Sarah (five notes).
- [x] At least one real-ingest contradiction — base and notice conflicts retain both sources.
- [x] README setup — fresh Python 3.12 venv and editable installation succeeded.
- [x] Under-five-minute demo path — timed load/read sequence below; scripted walkthrough budgets 4:30.
- [x] Change history with attribution — source IDs/contributors in real runtime commits.
- [x] Concurrent-write strategy documented — one shared-repository/filesystem POSIX lock.
- [x] Raw source attribution — immutable metadata plus exact original UTF-8 bodies.
- [x] Fact source citations — canonical wiki validation and manual page inspection.
- [x] Real Git history — earlier milestones preserved; nine runtime commits in this checkout.

## Audit and scoped changes

Inspected CLI/router, core operations, source storage, wiki compilation/parsing,
links/conflicts, lock/Git adapters, LLM boundary, models, schema, docs, and tests.
No existing DECISIONS.md was present; no retrospective decision log was invented.
Verified gaps: only three sample sources; no loader/fresh-demo workflow; concurrency
test did not force overlap; final handoff documentation missing. Addressed those gaps.

One reproducible path defect: `/status` followed a symlink entity page. It now uses
the shared safe wiki reader and read-only lock; regression test proves rejection
and no lock-file creation. No changes to core query, ingest, or lint algorithms.

The first real source-008 extraction put catering in aircraft_preferences. Added
field definitions and prompt guidance for future loads; no stored source/evidence
was overwritten or resolved. All six historical entity pages still pass canonical
parser/render validation. Structured output cannot prove semantic correctness.

## Real end-to-end acceptance

Followed README's new-directory workflow with `python -m goflight_memory.demo --fresh`.
A fresh temporary virtual environment installed package 0.5.0 successfully; ordinary
tests also ran with that installation. The configured model remained gpt-4.1-mini.
This host's system Python is 3.9, so installation used the existing Python 3.12.14
interpreter (`.venv/bin/python -m venv <temporary>/venv`), as allowed by README's
interpreter-path note, followed by `<temporary>/venv/bin/python -m pip install -e .`.
The new repository had one actual initialization commit and nine actual ingest commits.
All raw bodies/contributors matched the sample manifest exactly. Inspected generated
wiki facts, evidence, related links, conflicts, index/changelog, and Git messages.

Fresh result: **9 sources, 6 entities, 8 Markdown pages, 2 unresolved conflicts**;
zero orphan pages, broken links, or missing sources. Home base is Teterboro vs
Westchester; notice is 24 vs 48 hours, with John/source-001 and Sarah/source-002.
Acme catering was correctly classified under travel_preferences in this run.

Ran the actual CLI as Wajeeh with `/help`/`/status` and the README query/lint sequence:

| Input | Observed outcome |
| --- | --- |
| Would Atlantic Air's aircraft fit Acme Corp's known preferences? | Consulted operators/atlantic-air.md, customers/acme-corp.md, aircraft/n123gf.md; class/airport comparison and unresolved notices |
| Does Atlantic Air allow pets? | Information absent; operator page cited; no pet policy invented |
| Where is N123GF based? | Both bases, explicitly unresolved; aircraft page cited |
| How much booking notice does Atlantic Air require? | Both 24/48 hours, unresolved; operator page cited |
| Check the memory for problems. / /lint | Identical counts and attributed contradiction details |

Fresh bootstrap-to-final-ingest-commit: **24 seconds**. Actual CLI sequence: **11.3
seconds**, excluding human reading. Installation was tested separately, not included
in those timings. Five minutes is a practical walkthrough budget, not a guarantee
against provider/network delay or time obtaining credentials.

Before/after snapshots verified identical memory-file SHA-256 hashes, Git status,
and HEAD for query/lint in both repositories. No query/lint runtime commits occurred.
The original checkout retains **three** conflict warnings: the two intended conflicts
and the source-008 field misclassification. Its first comparison attempt safely
rejected a one-sided answer; other queries passed. This failure is disclosed, not
counted as a successful comparison. The fresh comparison succeeded. Even successful
model prose needs review: class/location consistency or prior use is not proof of
current operational suitability, availability, or catering capability.

## Automated, concurrency, and security checks

`python -m unittest discover -s tests -v`: **101 tests passed**, without API access.
The nine-source test uses mock extraction only; production persistence/Git is real.
It also checks idempotent replay, a failed-load retry, three-page query, and read-only
behavior. The deterministic orphan, broken-link, missing-source, and malformed-page
fixtures stay inside temporary directories.

The overlapping-ingest test holds A inside extraction while B attempts ingest;
B cannot enter extraction until A releases. Both contributors' facts, distinct
source IDs, conflicts, and real commits survive. A separate subprocess lock test
confirms cross-process blocking/release. No distributed-concurrency claim is made.

Failure tests cover missing key, invalid/refused extraction, rollback/Git failure,
malformed wiki, empty query, invalid selected paths, and unsafe links/symlinks.
Git history patches were scanned for the configured key and common credential
patterns; none found. `.env` is ignored/untracked. Runtime staging remains limited
to ingest-owned memory paths; earlier development and runtime history is preserved.

No optional UI, MCP, authentication, deployment, or human-resolution feature was added.
Remaining limitations are documented in README; no required workflow is omitted.
