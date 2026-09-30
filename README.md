# BronzGreen Claude Code plugins

Private plugin marketplace for BronzGreen developers. Only people with read access to
this repository can install from it.

| Plugin | What it gives you |
|---|---|
| `ai-dev-team` | The AI Dev Team framework's 35 agents (`ai-dev-team:architect`, `ai-dev-team:backend-dev`, …) and its skills, from `BronzGreen/AI-Dev-Team`, pinned to a release tag |
| `plaud-kit` | Plaud recordings → BRIDGE board cards (`/plaud-kit:plaud-inbox`), meeting digests (`/plaud-kit:plaud-digest`), meeting-vs-docs checks (`/plaud-kit:plaud-to-docs`) |

## Install (once per machine)

Claude Code clones this repository and `BronzGreen/AI-Dev-Team` with `git`, without
prompts, so your GitHub login has to be stored before you start. Everything goes over HTTPS;
you don't need an SSH key and you don't need a `git config url.…insteadOf` rewrite.

1. Install the GitHub CLI (`brew install gh` on macOS, `winget install GitHub.cli` on Windows),
   then log in and let git use that login. Run the two commands one at a time (Windows
   PowerShell 5 doesn't understand `&&`):
   ```
   gh auth login
   gh auth setup-git
   ```
2. Tell Claude Code to clone over HTTPS instead of trying SSH first, then **restart your
   terminal** so the variable is picked up.

   macOS / Linux (zsh or bash):
   ```bash
   echo 'export CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1' >> ~/.zshrc   # or ~/.bashrc
   ```
   Windows (PowerShell or cmd):
   ```powershell
   setx CLAUDE_CODE_PLUGIN_PREFER_HTTPS 1
   ```
   Without it, a machine with any SSH setup for github.com tries SSH and can fail with
   "Could not read from remote repository". If you earlier added the workaround
   `git config --global url."https://github.com/".insteadOf "git@github.com:"`, you can leave
   it or remove it with `git config --global --unset url."https://github.com/".insteadOf`.
3. In Claude Code:
   ```
   /plugin marketplace add BronzGreen/claude-plugins
   /plugin install ai-dev-team@bronzgreen
   /plugin install plaud-kit@bronzgreen
   ```
   Opening the BRIDGE repo does step 3 for you: its `.claude/settings.json` registers
   this marketplace and enables both plugins after you trust the folder.
4. Updates: `/plugin` → Marketplaces → `bronzgreen` → **Enable auto-update**, or run
   `/plugin marketplace update bronzgreen` now and then.

**Migrating from the old symlinks** (BRIDGE): remove the hand-made links, otherwise every
agent shows up twice.

macOS / Linux:
```bash
find .claude/agents -type l -lname '*/.ai/.claude/agents/*' -delete
```
Windows (PowerShell, in the BRIDGE folder):
```powershell
Get-ChildItem .claude\agents | Where-Object { $_.LinkType -and "$($_.Target)" -match '[\\/]\.ai[\\/]\.claude[\\/]agents' } | Remove-Item
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

The token is shown once. Store it (never in a repo).

macOS / Linux:
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
Windows (PowerShell) — same file, under your user folder:
```powershell
New-Item -ItemType Directory -Force "$HOME\.config\plaud-kit" | Out-Null
@"
BRIDGE_PAT=bgp_paste_here
BRIDGE_API_BASE=https://bridge.bronzgreen.com
BRIDGE_PROJECT_ID=69f8acbcfd4cf9998111c966
BRIDGE_BOARD_ID=69f8acc8fd4cf9998111c96b
BRIDGE_INBOX_COLUMN_ID=69f8acc8fd4cf9998111c96c
"@ | Set-Content -Encoding ascii "$HOME\.config\plaud-kit\env"
```

Needs `jq` and `curl` (`brew install jq`; on Windows `winget install jqlang.jq` — `curl`
ships with Windows and Git for Windows).

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
- Write every git-based plugin source as a full `https://github.com/…git` URL, never the
  `owner/repo` shorthand: the shorthand makes Claude Code try SSH first, which breaks
  installs on machines without a GitHub SSH key (most Windows setups).
- `plaud-kit`: bump `version` in `plugins/plaud-kit/.claude-plugin/plugin.json` to release.
- `ai-dev-team`: edit `.claude/agents/` or `skills/` in `BronzGreen/AI-Dev-Team`, run
  `bash scripts/build-plugin.sh`, merge, tag a release, then bump the `ref` in
  `.claude-plugin/marketplace.json` here.
- Changes go through a PR; nothing personal (tokens, transcripts, personal tooling) belongs here.
