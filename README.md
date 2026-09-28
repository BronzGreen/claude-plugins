# BronzGreen Claude Code plugins

Private plugin marketplace for BronzGreen developers. Only people with read access to
this repository can install from it.

| Plugin | What it gives you |
|---|---|
| `ai-dev-team` | The AI Dev Team framework's 35 agents (`ai-dev-team:architect`, `ai-dev-team:backend-dev`, …) and its skills, from `BronzGreen/AI-Dev-Team`, pinned to a release tag |
| `plaud-kit` | Plaud recordings → BRIDGE board cards (`/plaud-kit:plaud-inbox`), meeting digests (`/plaud-kit:plaud-digest`), meeting-vs-docs checks (`/plaud-kit:plaud-to-docs`) |

## Install (once per machine)

1. GitHub access without prompts (the install runs `git` non-interactively):
   ```bash
   gh auth login && gh auth setup-git
   ```
   No SSH key on GitHub? Also set `export CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` in your shell
   profile, otherwise the install tries SSH and fails with "Could not read from remote repository".
2. In Claude Code:
   ```
   /plugin marketplace add BronzGreen/claude-plugins
   /plugin install ai-dev-team@bronzgreen
   /plugin install plaud-kit@bronzgreen
   ```
   Opening the BRIDGE repo does step 2 for you: its `.claude/settings.json` registers
   this marketplace and enables both plugins after you trust the folder.
3. Updates: `/plugin` → Marketplaces → `bronzgreen` → **Enable auto-update**, or run
   `/plugin marketplace update bronzgreen` now and then.

**Migrating from the old symlinks** (BRIDGE): remove the hand-made links, otherwise every
agent shows up twice:
```bash
find .claude/agents -type l -lname '*/.ai/.claude/agents/*' -delete
```

## plaud-kit setup

### 1. Plaud login (per person)
Run `/mcp`, pick `plugin:plaud-kit:plaud`, authenticate in the browser with **your own**
Plaud account (or the Plaud Team workspace you record into). Access is read-only: Claude can
list recordings and read notes/transcripts that Plaud already generated.

### 2. Your own BRIDGE token
Cards are created in your name, so each person uses their own PAT. Log in to
https://bridge.bronzgreen.com, open the browser DevTools console and run:

```js
(async () => {
  const res = await fetch("/api/v1/auth/tokens", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${localStorage.getItem("bridge_access_token")}`,
      "X-Session-ID": localStorage.getItem("bridge_session_id"),
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify({
      name: "plaud-kit",
      scopes: ["projects.read", "projects.boards.read", "projects.tasks.read", "projects.tasks.create"],
      expires_in_days: 90,
    }),
  });
  const data = await res.json().catch(() => ({}));
  console.log(res.ok ? data.token : `Mint failed ${res.status}: ${JSON.stringify(data)}`);
})();
```

The token is shown once. Store it (never in a repo):

```bash
mkdir -p ~/.config/plaud-kit
cat > ~/.config/plaud-kit/env <<'EOF'
BRIDGE_PAT=bgp_paste_here
BRIDGE_API_BASE=https://bridge.bronzgreen.com
BRIDGE_PROJECT_ID=69f8acbcfd4cf9998111c966
BRIDGE_BOARD_ID=69f8acc8fd4cf9998111c96b
BRIDGE_INBOX_COLUMN_ID=69f8acc8fd4cf9998111c96c
EOF
chmod 600 ~/.config/plaud-kit/env
```

Needs `jq` and `curl` (`brew install jq`).

### 3. Use it
```
/plaud-kit:plaud-inbox this week
/plaud-kit:plaud-digest today
/plaud-kit:plaud-to-docs "Toteco overleg 2026-09-25"
```

Optional daily digest from cron/launchd: `claude -p "/plaud-kit:plaud-digest today"`.

## Data rules (built into the skills)

- Plaud access is read-only and per user; nobody sees someone else's recordings.
- Cards contain a paraphrased summary and `Bron: Plaud-opname <date> (<id>)` — no verbatim
  quotes, no names of external people, no transcript excerpts.
- Transcripts are never written to disk, a card, a commit or a PR.
- Cards land in the backlog with label `plaud`. `ai-ready` is always stripped: a human decides
  what the sprint-loop may build.
- Local state is a ledger of recording ids + dates only, in the plugin's data directory.
- Tell people when you record them. Recording customers is subject to BronzGreen's recording policy (AVG).

## Maintaining

- `claude plugin validate .` before every push.
- `plaud-kit`: bump `version` in `plugins/plaud-kit/.claude-plugin/plugin.json` to release.
- `ai-dev-team`: edit `.claude/agents/` or `skills/` in `BronzGreen/AI-Dev-Team`, run
  `bash scripts/build-plugin.sh`, merge, tag a release, then bump the `ref` in
  `.claude-plugin/marketplace.json` here.
- Changes go through a PR; nothing personal (tokens, transcripts, personal tooling) belongs here.
