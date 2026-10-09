---
name: release-sweep
description: >-
  Finishes common-base releases after a human has merged the change: tags the
  version the merged PR claimed (release.yml then publishes the Go module and
  the @bronzgreen/* npm packages), opens the CVS pin-bump PR and waits for it to
  go green, then opens the product pin-bump PRs that the merged PRs listed under
  "Consumers waiting". Use at the start of every sprint-loop run, when someone
  says "release common-base", "the common-base PR is merged, now what", or
  "bump common-base", and whenever /common-base:upstream-pr work has been
  merged. Safe to run when there is nothing to do. Never merges a product PR;
  the CVS pin-bump PR merges itself through GitHub auto-merge once CVS CI is green.
---

# /common-base:release-sweep

Recipe C-7 after the merge: **tag → CVS PR green → product pins**. The human's
merge of a `release:*` PR in common-base is the approval to release it; this
skill does the mechanical rest so nobody has to remember the order.

**It never merges a PR itself.** It tags, because tagging a merged, reviewed
change is the release step that merge approved. The one PR that lands without a
human is the CVS pin-bump: it changes nothing but pins, CVS CI is its review, so
the sweep turns on GitHub auto-merge for it and the required `verify` check
decides. Every product PR (BRIDGE and others) still waits for a human.

## 1. Anything to release?

```bash
W="${TMPDIR:-/tmp}/common-base-sweep"
rm -rf "$W" && gh repo clone BronzGreen/common-base "$W" -- -q
LATEST=$(git -C "$W" tag --sort=-v:refname | head -1)
TOP=$(grep -m1 -oE '^## v[0-9]+\.[0-9]+\.[0-9]+' "$W/CHANGELOG.md" | cut -c4-)
```

- `TOP` already tagged (`git -C "$W" rev-parse -q --verify "refs/tags/$TOP"`)
  → no release pending. Go to step 4 anyway: a product bump may still be
  waiting from an earlier sweep that stopped.
- `TOP` not tagged → candidates are the PRs merged since `LATEST`:
  `gh pr list -R BronzGreen/common-base --state merged --search "merged:>=<LATEST tag date>" --json number,title,labels,body,mergeCommit`.
  Every one with a `release:*` label belongs in `TOP`.

Stop and report (do not tag) when:
- `TOP` is not strictly greater than `LATEST`, or skips a number without a
  reservation explaining it;
- the default branch's CI (`verify.yml`) is not green on the commit to tag;
- a merged `release:major` PR has no migration note in its CHANGELOG entry.

## 2. Tag

```bash
git -C "$W" tag -a "$TOP" -m "$TOP" <commit at the top of the default branch>
git -C "$W" push origin "$TOP"
```

Then wait for `release.yml` on that tag (`gh run list -R BronzGreen/common-base
--workflow release.yml --limit 1`, then `gh run watch <id>`). It publishes the
npm packages; a product cannot install the version before it is green. A red
release run stops the sweep: report the failed job, do not delete the tag.

## 3. CVS first (the pilot consumer)

In a fresh clone of `bronzgreen/cvs`, branch `chore/common-base-$TOP`:
- `backend/go.mod`: `go get github.com/bronzgreen/common-base@$TOP && go mod tidy`
  (needs `GOPRIVATE=github.com/bronzgreen/*` and git auth to GitHub);
- `web/package.json`: every `@bronzgreen/*` pin to the new version, then
  `npm install` to refresh the lockfile (needs `GH_PAT=$(gh auth token)` with
  `read:packages`);
- every `uses: BronzGreen/common-base/...@vX` reference in `.github/workflows`.

Run its checks, open the PR with the CHANGELOG entries in the body, and wait for
its CI (`gh pr checks <n> --watch`). **Red CVS CI stops the sweep before any
other product pins** — report the failure; fixing CVS is a normal CVS change.
Turn on auto-merge as soon as the PR is open, so it lands the moment CVS CI is
green:

```bash
gh pr merge <n> -R bronzgreen/cvs --auto --squash --delete-branch
```

CVS `main` requires the `verify` check, which only passes when the Go, vuln and
web jobs all pass, so auto-merge cannot skip a red job. Only ever enable it on
the sweep's own `chore/common-base-*` PR, and only when the diff is limited to
pins and lockfiles (`go.mod`, `go.sum`, `package.json`, `package-lock.json`,
workflow `uses:` refs); anything else in the diff means a human merges it. If
the repo refuses auto-merge (setting off), leave the PR for a human and say so.
Green means continue.

## 4. Product bumps

Collect the `## Consumers waiting` lines from every PR in this release (and from
earlier releases whose product bump has no open or merged PR yet):

```
- repo: BronzGreen/BRIDGE | card: <board id> | wire: <what to do>
```

Per product repo, open **one** PR that bumps every pin (Go module, `@bronzgreen/*`,
workflow `uses:` refs) to `$TOP` and does each listed `wire:` item. Work in an
isolated checkout (a worktree subagent, never the human's live tree) from the
product's integration branch, and use the product's own landing path (BRIDGE:
the `/commit` skill, PR into `dev`). Read every CHANGELOG entry between the
product's current pin and `$TOP`: a bump can carry other releases' behaviour
changes, and those belong in the PR body under `## Reviewer must decide`.

The PR body lists the cards it completes. The caller (for BRIDGE, the
sprint-loop orchestrator) moves those cards on once the PR is open.

## 5. Report

One line per step: version tagged (or why not), release run, CVS PR and its CI,
each product PR, and the cards it completes. Nothing merged.
