---
name: plaud-to-docs
description: >-
  Compare what was said in a Plaud recording (customer meeting, requirements session,
  domain discussion) with the current repository's documentation, and propose doc
  updates on a branch. Use when someone says "check this meeting against the docs",
  "did the customer say something that contradicts our rules", "update the domain
  docs from yesterday's meeting". Invoke as /plaud-kit:plaud-to-docs <recording or date>.
---

# plaud-to-docs — meeting vs. documentation

Goal: catch the moment a customer or domain expert says something that differs from
what the repo documents, before it turns into a wrong implementation.

1. **Find the recording** with `list_files` (name or date). Read `get_note`; read
   `get_transcript` for this one — details matter here. The transcript stays in context
   only.
2. **Find the relevant docs** in the current repo. In BRIDGE start with
   `context/domain/` (`bridge-enterprise.md`, `rules-*.md`), `context/modules/` and
   `architecture/adrs/`; elsewhere look for a `docs/`, `context/` or ADR folder. Only
   read what the meeting touched.
3. **Compare** and report in three groups, each item with the doc path and line:
   - **Tegenstrijdig** — the meeting says X, the doc says Y.
   - **Nieuw** — a rule or requirement the docs don't have.
   - **Bevestigd** — only when useful (e.g. a doc marked as uncertain).
   Paraphrase; no verbatim quotes, no names of external people.
4. **Ask before editing.** If the user agrees, make the edits on a new branch in a git
   worktree branched from the repo's integration branch (BRIDGE: from `origin/dev`),
   and use the repo's normal commit flow (BRIDGE: `/commit`). The PR description cites
   "Plaud-opname <date>" as source — never transcript text.
5. Contradictions that need a decision from the customer or product owner become a list
   of questions, not doc edits.
