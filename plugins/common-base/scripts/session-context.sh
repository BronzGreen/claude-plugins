#!/usr/bin/env bash
# SessionStart: one line of context so the common-base rule is in force in every
# project, not only where a CLAUDE.md repeats it. Prints nothing outside a git repo.
set -u
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
remote=$(git -C "$root" remote get-url origin 2>/dev/null || true)
case "$remote" in
  *[Bb]ron[zZ][gG]reen/common-base*)
    echo "common-base: this IS the BronzGreen/common-base repository. Keep every change product-neutral (no product names, tenants, customer hosts or domain vocabulary; product-specific behaviour is an option with a neutral default), update CHANGELOG.md, and release by tag."
    exit 0 ;;
esac
if grep -qs 'github.com/bronzgreen/common-base' "$root"/go.mod "$root"/*/go.mod \
  || grep -qs '"@bronzgreen/' "$root"/package.json "$root"/*/package.json; then
  echo "common-base: this repo consumes BronzGreen/common-base. Never change common-base code here (no copies, forks or edits of installed @bronzgreen/* or Go module cache files); such changes go to the common-base repo by PR + tag, then a pin bump here. Before building a new helper, component, hook, middleware, client or workflow, check common-base first with /common-base:waar-hoort-dit."
  exit 0
fi
case "$remote" in
  *[Bb]ron[zZ][gG]reen/*|"")
    echo "common-base: BronzGreen products are built on BronzGreen/common-base (Go module github.com/bronzgreen/common-base + @bronzgreen/* npm packages + a product template). When designing or scaffolding this project or a new feature area, run /common-base:nieuw-product first and reuse what common-base provides instead of rebuilding it." ;;
esac
exit 0
