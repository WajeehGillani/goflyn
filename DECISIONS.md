# Milestone 5.1 decisions — 2026-09-12

No earlier decision log existed. These entries describe only this milestone; they
do not invent or rewrite earlier decisions. The local Markdown/Git architecture stays.

### Human-only conflict resolution

Truth resolution requires an explicit human decision. The conversational layer
previews evidence, reviewer, exact value, and reason, then requires `yes`. The core
write command accepts an existing value or a qualified statement; no LLM tool exposes
this operation. Reviewer is an identified local-session label, not authentication.

Preserve fact rows and raw sources instead of overwriting either side. Append a typed
decision with reviewed values/sources and UTC time to the existing conflict block.
Reuse the existing entity/type/field hash ID. One parser/model serves ingest/query/
lint/resolve; a resolved field uses the latest human value, while original claims stay
available as evidence. New distinct facts reopen the same ID; repeat evidence for
reviewed values does not. Past decisions are retained.

Confirmation holds no lock. Recheck the full evidence revision under the existing
write lock before mutating; reject stale review. Commit only the affected page and
changelog, roll back owned files/staging on caught failures, and require inspection
after an ambiguous HEAD change. This is not a crash-safe multi-file transaction.

### Conflict-safe query recovery

Unsafe partial conflict answers are automatically corrected or safely synthesized
from structured conflict evidence. Field relevance considers both question and answer,
not simply whether a retrieved page contains any conflict. This permits an unconflicted
aircraft-type answer while still guarding a conflicting base.

Use exactly one corrective answer call with all relevant values/evidence, rather than
an unbounded loop. On invalid correction or provider failure, build an attributed
unresolved response directly from the shared model. Synthesis receives current human
decisions in place of historical resolved alternatives; it never writes memory.
Keep the current provider/model and strict structured schema. Structured output is
not semantic validation, as the [official guidance](https://developers.openai.com/api/docs/guides/structured-outputs)
notes. Lexical relevance/answer checks are inspectable but cannot prove entailment.

### Explicit entity assertions

Direct human assertions may create supported entity pages while still preserving
the original instruction as immutable evidence. A small explicit grammar yields a
structured entity after raw storage, then uses normal reconciliation/index/changelog/
Git. It does not introduce a CRUD store or bypass ingest.

Entity-only pages use typed source/contributor evidence, an empty Facts table, and
the same canonical identity/duplicate rules. Only customer, operator, and aircraft are
supported. Incidental person mentions do not establish a customer; normal notes still
use semantic extraction. Exact committed retries stay idempotent, so this change does
not silently backfill old committed instructions.
