#!/usr/bin/env bash
# PreToolUse guard (Edit|Write|MultiEdit|NotebookEdit), every project: never edit an
# installed copy of common-base. Those edits are lost on the next install and never
# reach anyone else; the change belongs in the BronzGreen/common-base repository.
# Exit 2 = blocked (stderr goes back to Claude). Fails open on anything unexpected.
set -u
input=$(cat)
if command -v jq >/dev/null 2>&1; then
  file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' 2>/dev/null)
else
  file=$(printf '%s' "$input" | sed -nE 's/.*"(file_path|notebook_path)"[[:space:]]*:[[:space:]]*"([^"]*)".*/\2/p' | head -1)
fi
[ -n "${file:-}" ] || exit 0
file=${file//\\//}
case "$file" in
  */node_modules/@bronzgreen/*|*/pkg/mod/github.com/bronzgreen/common-base*) ;;
  *) exit 0 ;;
esac
cat >&2 <<MSG
BLOCKED: $file is an installed copy of common-base (@bronzgreen/* or the Go module cache).
common-base has one home, the BronzGreen/common-base repository. Do not patch it here:
  1. /common-base:waar-hoort-dit to confirm the change and its product-neutral shape;
  2. change it in a clone of BronzGreen/common-base: PR, CHANGELOG, tag;
  3. CVS takes the tag first, then bump the pins (go.mod, @bronzgreen/* in package.json) in this product.
Product-specific values belong in the product's own common-base adapter, not in the base.
MSG
exit 2
