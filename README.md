# BronzGreen Claude Code plugins

Private plugin marketplace for BronzGreen developers. Only people with read access to
this repository can install from it.

| Plugin | What it gives you |
|---|---|
| `ai-dev-team` | The AI Dev Team framework's 35 agents (`ai-dev-team:architect`, `ai-dev-team:backend-dev`, …) and its skills, from `BronzGreen/AI-Dev-Team`, pinned to a release tag |
| `plaud-kit` | Plaud recordings → BRIDGE board cards (`/plaud-kit:plaud-inbox`), meeting digests (`/plaud-kit:plaud-digest`), meeting-vs-docs checks (`/plaud-kit:plaud-to-docs`) |
| `common-base` | Keeps `BronzGreen/common-base` the one home of shared platform code in **every** project: `/common-base:waar-hoort-dit` (common-base or product?), `/common-base:nieuw-product` (start a new product on common-base, reuse before building), `/common-base:upstream-pr` (open the neutral common-base PR for a change a product needs) and `/common-base:release-sweep` (after a human merges: tag, CVS bump, product pin bumps), agent `common-base:placement`, a guard that blocks edits to installed `@bronzgreen/*` / Go-module-cache copies, and a session note that puts the rule in force in every BronzGreen repo. Install it globally (user scope) so it also applies to new projects. |
| `pii-filter` | Automatic, local PII filtering with Microsoft Presidio (Dutch + English). Reading a data file (csv/json/log/eml/txt/sql/xml) that contains personal data gives Claude a pseudonymised copy (`<PERSON_1>`, `<NL_BSN_1>`, …); raw shell/Grep views of data files are blocked; the local vault with real values is off-limits; personal data that still slips through is reported automatically as a datalek in BRIDGE ISMS (`/pii-filter:datalek-melden` for manual reports). Applies to subagents too. Code files are never touched. Install it globally (user scope). See [pii-filter](#pii-filter). |
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
   /plugin install common-base@bronzgreen
   /plugin install pii-filter@bronzgreen
   ```
   Opening the BRIDGE repo does step 3 for you: its `.claude/settings.json` registers
   this marketplace and enables the plugins after you trust the folder. Install `common-base` from your
   home directory (user scope) as well, so new projects get it too.
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

## pii-filter

### What happens
- **Read** of `.csv .tsv .txt .log .json .jsonl .ndjson .xml .eml .sql .vcf`: Presidio scans the file locally.
  If it contains personal data, Claude reads a pseudonymised copy instead (`Jan de Vries` → `<PERSON_1>`;
  the same value gets the same token everywhere, so relations survive). Clean files are read as-is.
- **Bash / PowerShell** commands that print a data file (`cat`, `head`, `Get-Content`, `Import-Csv`, `grep`, `jq`, …)
  and **Grep** with `output_mode: content` on data files are refused with a pointer to the CLI.
- The **vault** with real values (`~/.claude/pii-vault/`) is never readable by Claude. Restoring real values
  (`pii.py deanonymize … -o file`) only writes to a file.
- Code and config (`package.json`, `tsconfig`, `node_modules`, `.claude/`, …) are never filtered.
- Hooks also apply to subagents. Nothing leaves the machine.

### Requirements and first run
Git Bash on Windows (same as `common-base`) and either [uv](https://docs.astral.sh/uv/)
(`winget install astral-sh.uv` / `brew install uv`, recommended) or Python 3.10–3.13.
On the first session the plugin installs Presidio + the spaCy NL/EN models (~300 MB) into its own data
directory in the background (a few minutes, log: `~/.claude/plugins/data/pii-filter*/setup-log.txt`).
Until that is done, data files are **refused**, not passed through. Ask Claude for `pii.py status` to check.

### Per-project settings
Commit a `.pii-filter.json` in the repo root; lists extend the defaults:
```json
{
  "allow_list": ["Toteco"],
  "column_hints": { "debiteurnaam|relatie": "PERSON" },
  "hook": { "exclude_globs": ["*/src/i18n/*.json", "*/testdata/synthetic/*"] }
}
```
Personal additions go in `~/.claude/pii-filter.json`. One session without filter: start `claude` with
`PII_FILTER=off`.

### Enforce it for everyone (admins)
Managed settings win over user settings, so the plugin can be switched on centrally and can't be
switched off. Either in claude.ai → Organization settings → Claude Code → Managed settings (Teams/Enterprise,
Owner role), or in the managed settings file (`C:\Program Files\ClaudeCode\managed-settings.json` on Windows,
`/Library/Application Support/ClaudeCode/managed-settings.json` on macOS):
```json
{
  "extraKnownMarketplaces": {
    "bronzgreen": { "source": { "source": "github", "repo": "BronzGreen/claude-plugins" } }
  },
  "enabledPlugins": { "pii-filter@bronzgreen": true },
  "env": { "PII_FILTER_ENFORCED": "1" }
}
```
`PII_FILTER_ENFORCED=1` makes the plugin ignore `PII_FILTER=off`, `"enabled": false` and `fail_mode: "open"`.
Users still need read access to this repo plus `gh auth setup-git` (see Install). The hooks only exist in
Claude Code and the Agent SDK (load the plugin with `plugins=[{"type": "local", "path": …}]`); claude.ai chat,
desktop chat and mobile are not covered.

### Datalek reporting (BRIDGE ISMS)
A second check runs **after** every Read of a data file and every shell command that touches one: it scans what
the model actually received for hard identifiers (e-mail address, IBAN with valid checksum, BSN passing the
11-proef next to a BSN keyword, Dutch mobile number). On a hit it automatically creates an AVG datalek in
BRIDGE → ISMS → Datalekken (`aard: vertrouwelijkheid`, `rol` and `meldbeslissing`: *nog te bepalen*,
`status: open`), and BRIDGE e-mails the tenant's privacy officer. The 72-hour clock is then visible in the register.
- The report holds **counts per type, project name, file type, timestamp, session and plugin version**, never
  the values and never the file path. Path ↔ reference stays local in the plugin data dir (`leaks/sent.jsonl`).
- One report per file per session. If BRIDGE is unreachable or no token is set, the report waits in a local
  queue and is sent at the next session start.
- Names, addresses and other things the automatic check can't see: Claude uses the skill
  `/pii-filter:datalek-melden` (asks you first, then `pii.py report-leak`).

**One-time setup per person: a BRIDGE token** with scope `isms.datalek.melden` (report-only, every employee
has it). Log in to https://bridge.bronzgreen.com, open the browser DevTools console and run:
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
    body: JSON.stringify({ name: "pii-filter", scopes: ["isms.datalek.melden"], expires_in_days: 365 }),
  });
  const data = await res.json().catch(() => ({}));
  console.log(res.ok ? data.token : `Mint failed ${res.status}: ${JSON.stringify(data)}`);
})();
```
Store it (never in a repo) in `~/.config/pii-filter/env`:
```
BRIDGE_PAT=bgp_paste_here
BRIDGE_API_BASE=https://bridge.bronzgreen.com
```
macOS/Linux: `chmod 600 ~/.config/pii-filter/env`. Check with Claude: "draai pii.py leaks".
The privacy officer is set per tenant in BRIDGE under ISMS (*Privacy officer (FG)*).

### Limits
Detection is statistical: a name can slip through or a word gets replaced needlessly. A script that prints
records itself, MCP tools and WebFetch are outside the hooks. Treat it as a strong safety net, not a guarantee.
The automatic datalek check only sees hard identifiers; it will not notice a leaked name on its own.

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
- `pii-filter`: run `python plugins/pii-filter/tests/test_hook_shell.py` and
  `python plugins/pii-filter/tests/test_hook_e2e.py <plugin-data-dir>` (after `scripts/setup.sh`), then bump
  `version` in its `plugin.json`. Bumping `scripts/requirements.txt` makes every machine reinstall on next start.
- `plaud-kit`: bump `version` in `plugins/plaud-kit/.claude-plugin/plugin.json` to release.
- `ai-dev-team`: edit `.claude/agents/` or `skills/` in `BronzGreen/AI-Dev-Team`, run
  `bash scripts/build-plugin.sh`, merge, tag a release, then bump the `ref` in
  `.claude-plugin/marketplace.json` here.
- Changes go through a PR; nothing personal (tokens, transcripts, personal tooling) belongs here.
