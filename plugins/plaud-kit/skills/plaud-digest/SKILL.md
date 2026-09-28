---
name: plaud-digest
description: >-
  Summarise the user's Plaud recordings over a period into one digest: decisions,
  action items (with owner if stated), open questions and follow-ups. Use when
  someone asks "what did I record today", "recap of this week's meetings", "plaud
  digest", "what did we decide with <customer>", or wants a roll-up of several
  recordings. Invoke as /plaud-kit:plaud-digest [range].
---

# plaud-digest — a roll-up of recordings

Read-only. Nothing is written anywhere unless the user asks for it afterwards.

1. **Window.** Use the given range; default is today. Relative phrases ("this week",
   "since Monday") resolve against today's date, weeks start Monday.
2. **Corpus.** `list_files` with `date_from` / `date_to`. More than 40 → ask to narrow.
   Leave out recordings that are clearly private, and say how many you left out.
3. **Notes.** `get_note` per recording. `get_transcript` only for a recording whose
   note is empty and whose content the user explicitly wants.
4. **Digest** (answer in the user's language):
   - **Kern** — one line on the theme of the period.
   - **Per opname** — `• name (date) — one-sentence takeaway`.
   - **Besluiten** — decisions, each with its source recording.
   - **Actiepunten** — deduplicated; owner and deadline only if the recording states them.
   - **Open vragen / follow-ups** — including things promised to customers.
   - **Niet samengevat** — recordings without a note.
5. **Offer, don't do:** end with one line offering `/plaud-kit:plaud-inbox` for the
   action items that belong on the board.

Rules: only aggregate what the notes say — never invent owners, dates or decisions.
No verbatim quotes of external people. If the user asks to save or share the digest,
write it where they ask, but never into a git repository unless they name the file.
