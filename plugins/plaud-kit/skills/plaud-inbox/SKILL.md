---
name: plaud-inbox
description: >-
  Turn recent Plaud recordings (meetings, calls, voice memos) into proposed BRIDGE
  board cards, and create the ones the user picks. Use when someone says "process my
  Plaud recordings", "what came out of my meetings", "turn that meeting into cards",
  "plaud inbox", or asks to put action items from a recording on the board.
  Invoke as /plaud-kit:plaud-inbox, optionally with a range ("this week", "since
  Monday", "2026-09-20..2026-09-27") or a recording name.
---

# plaud-inbox — recordings → proposed BRIDGE cards

You read the user's own Plaud recordings through the `plaud` MCP server (read-only)
and propose kanban cards. **You never create a card the user did not pick.**

## 0. Preconditions (stop and explain if one fails)

1. The `plaud` MCP tools are available. If a call says the user is not logged in,
   tell them to run `/mcp`, select `plugin:plaud-kit:plaud`, and authenticate.
2. Credentials check:
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/bridge-card.sh" --check
   ```
   On "no credentials", point the user to the Setup section of the plaud-kit README
   (mint a PAT, write `~/.config/plaud-kit/env`, `chmod 600`).

## 1. Pick the recordings

- Range given → use it. Otherwise start the day after
  `PLAUD_KIT_STATE="${CLAUDE_PLUGIN_DATA}" bash "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.sh" last`
  (or the last 7 days if the ledger is empty).
- `list_files` with `date_from` / `date_to`. Drop recordings for which
  `ledger.sh seen <id>` succeeds, unless the user named that recording explicitly.
- More than 15 left → list them (name, date, duration) and ask which ones.
- Recordings that are clearly private (not work) → skip, and say you skipped them
  without describing their content.

## 2. Read — notes first, transcripts only when needed

- `get_note` per recording (summary, action items, key topics).
- Call `get_transcript` only when the note has no usable action items and the
  recording is clearly a work meeting. Keep the transcript in context only; **never
  write a transcript, or any part of one, to a file, a card, a commit or a PR.**

## 3. Propose

Show one table per recording, then stop and ask which to create:

| # | Title | Type | Prio | Summary (1–3 sentences) |
|---|---|---|---|---|

Rules for proposals:
- Only real, actionable work for the BRIDGE product/team. Not every remark is a card;
  zero proposals is a fine outcome.
- **Language:** Dutch, matching the board.
- **Title:** imperative, ≤ 80 chars, specific ("Exportknop km-declaraties naar xlsx").
- **Description:** your own paraphrase of *what* and *why*, plus acceptance hints if
  the meeting stated them. End with `Bron: Plaud-opname <YYYY-MM-DD> (<recording id>)`.
- **Privacy:** no verbatim quotes, no names of customers' employees or other external
  people, no personal data (health, salary, private matters), no transcript excerpts.
  A customer *organisation* name is fine when the work is for that customer.
- **Type:** `bug` for broken behaviour, `story` for user-facing features, else `task`.
  **Priority:** `medium` unless the meeting made urgency explicit.
- Check duplicates: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/bridge-card.sh" --find "<keyword>"`
  for the main keyword of each proposal; mark likely duplicates in the table.

## 4. Create what the user picked

For each picked card, write the JSON to a temp file in the session scratchpad (not the
repo), show the dry run once for the first card, then create:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/bridge-card.sh" /path/card.json          # dry run
bash "${CLAUDE_PLUGIN_ROOT}/scripts/bridge-card.sh" --create /path/card.json # create
```

The script puts cards in the To Do column without a sprint (= backlog), always adds the
`plaud` label and strips `ai-ready` — tagging a card for the sprint-loop is a human
decision. Delete the temp files afterwards.

## 5. Record

For every processed recording (created or not):
```bash
PLAUD_KIT_STATE="${CLAUDE_PLUGIN_DATA}" bash "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.sh" add <recording_id> <card_id,card_id|skipped>
```

Finish with a short list: created cards (id + title), skipped recordings, duplicates found.
