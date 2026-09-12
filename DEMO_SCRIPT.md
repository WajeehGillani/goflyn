# Live demo — under five minutes

Choose a new, not-yet-created DEMO_ROOT using README's mktemp step; do not load twice.
Have Python/Git and the key ready; provider/install
latency varies. Measured load + CLI sequence: about 36 seconds, excluding setup/readout.

1. **0:00–0:25 — Architecture:** “Immutable notes → attributed Markdown wiki → grounded
   answers and deterministic health checks, with Git history.” Show ARCHITECTURE.md.
2. **0:25–0:45 — Schema:** show schema.md's fields and evidence/conflict rules.
3. **0:45–1:25 — Ingest:** run `python -m goflight_memory.demo --fresh "$DEMO_ROOT"`
   from README. Every note takes production ingest and creates a real commit.
4. **1:25–1:50 — Evidence:** show `$DEMO_ROOT/memory/raw/source-001.md` and
   `source-002.md`: unchanged notes and John/Sarah attribution. Open
   `$DEMO_ROOT/memory/wiki/aircraft/n123gf.md`: facts, links, sources, both bases.
5. **1:50–2:30 — Query:** `goflight-memory --user Jack` with README's environment.
   “Would Atlantic Air's aircraft fit Acme Corp's known preferences?” Show three
   pages used; class consistency is not confirmed trip suitability.
6. **2:30–3:00 — Trust:** “Does Atlantic Air allow pets?” Then “Where is N123GF
   based?” and “How much booking notice does Atlantic Air require?” Show unknown
   policy and unresolved values. Do not present the newest claim as authoritative.
7. **3:00–3:25 — Lint:** “Check the memory for problems.” then `/lint`: matching reports,
   two intended contradictions, no orphan/broken/missing references in the fresh run.
   Temporary orphan fixtures are independently demonstrated by `test_lint.py`.
8. **3:25–4:05 — Human decision:** “Show conflicts.” Pick the displayed home-base ID
   with `/resolve <id>`, enter “Westchester”, give “Operator confirmed the move”, review
   all evidence, then `yes`. Query the base again and `/lint`: that conflict is no longer
   unresolved. Other conflicts stay active. Show `/add new customer Wajeeh`: entity-only
   page with source provenance, no invented attributes.
9. **4:05–4:30 — History:** `/exit`, `git -C "$DEMO_ROOT" log --oneline`,
   `git -C "$DEMO_ROOT" show --stat HEAD`. Query/lint made no commits; the explicit
   resolution and entity assertion each did. Inspect the resolution's two-file diff.
10. **4:30–4:55 — Lock and cuts:** cooperating writes serialize; stale review is
    rejected. No UI/MCP/auth/deployment or automatic AI resolution. Explain bounded
    query/grammar and semantic-extraction limitations from SUBMISSION_NOTE.md.

Do not hide failures: the development checkout retains an extra catering-field
warning. Unsafe relevant-conflict answers are retried once, then receive a structured
fallback if necessary. Fresh loads remain probabilistic. No final wiki pages are
hardcoded; the fallback is deterministic from stored competing evidence.
