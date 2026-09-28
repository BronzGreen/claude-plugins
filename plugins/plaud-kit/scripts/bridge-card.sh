#!/usr/bin/env bash
# bridge-card.sh — create or look up BRIDGE kanban cards for plaud-kit.
#
# Credentials are per user and never live in a repo:
#   ~/.config/plaud-kit/env   (chmod 600)
#     BRIDGE_PAT=bgp_...                 least-privilege PAT (see README)
#     BRIDGE_API_BASE=https://bridge.bronzgreen.com
#     BRIDGE_PROJECT_ID=69f8acbcfd4cf9998111c966
#     BRIDGE_BOARD_ID=69f8acc8fd4cf9998111c96b
#     BRIDGE_INBOX_COLUMN_ID=69f8acc8fd4cf9998111c96c   # "To Do"; no sprint = backlog
#
# Usage:
#   bridge-card.sh --check                  # verify credentials + board access
#   bridge-card.sh --find "title fragment"  # existing cards whose title matches (all sprints)
#   bridge-card.sh card.json                # DRY RUN: print the payload that would be sent
#   bridge-card.sh --create card.json       # really create the card
#
# card.json: {"title": "...", "description": "...", "item_type": "task|story|bug",
#             "priority": "high|medium|low", "labels": ["plaud", ...]}
# The script always adds the "plaud" label and strips "ai-ready": a human decides
# what the sprint-loop may pick up, never a recording.
set -euo pipefail

ENV_FILE=${PLAUD_KIT_ENV:-$HOME/.config/plaud-kit/env}

die() { echo "bridge-card: $*" >&2; exit 1; }
command -v jq >/dev/null || die "jq is required (brew install jq)"
command -v curl >/dev/null || die "curl is required"

[ -f "$ENV_FILE" ] || die "no credentials at $ENV_FILE — see the plaud-kit README (Setup)"
if [ "$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")" != 600 ]; then
  die "$ENV_FILE must be chmod 600 (it holds your PAT)"
fi
set -a; . "$ENV_FILE"; set +a
: "${BRIDGE_PAT:?BRIDGE_PAT missing from $ENV_FILE}"
: "${BRIDGE_API_BASE:=https://bridge.bronzgreen.com}"
: "${BRIDGE_PROJECT_ID:?BRIDGE_PROJECT_ID missing from $ENV_FILE}"
: "${BRIDGE_BOARD_ID:?BRIDGE_BOARD_ID missing from $ENV_FILE}"
: "${BRIDGE_INBOX_COLUMN_ID:?BRIDGE_INBOX_COLUMN_ID missing from $ENV_FILE}"

TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT

get() { # get <path> -> body in $TMP, echoes http code
  curl -sS -o "$TMP" -w '%{http_code}' -H "Authorization: Bearer $BRIDGE_PAT" "$BRIDGE_API_BASE/api/v1$1"
}

fail() {
  echo "bridge-card: HTTP $1 from $2" >&2
  head -c 300 "$TMP" >&2; echo >&2
  [ "$1" = 401 ] && echo "bridge-card: PAT expired or revoked — mint a new one (README)." >&2
  [ "$1" = 403 ] && echo "bridge-card: PAT lacks a scope — see README for the scope list." >&2
  exit 1
}

payload() { # payload <card.json> -> sanitised request body on stdout
  jq -e --arg board "$BRIDGE_BOARD_ID" --arg col "$BRIDGE_INBOX_COLUMN_ID" '
    if (.title // "" | length) == 0 then error("card has no title") else . end
    | {
        title: (.title | .[0:200]),
        description: (.description // ""),
        item_type: (if (.item_type // "task") | IN("epic","story","task","bug") then (.item_type // "task") else "task" end),
        priority: (if (.priority // "medium") | IN("high","medium","low") then (.priority // "medium") else "medium" end),
        labels: (((.labels // []) + ["plaud"]) | map(select(. != "ai-ready")) | unique),
        board_id: $board,
        column_id: $col
      }' "$1"
}

case "${1:-}" in
  --check)
    code=$(get "/boards/$BRIDGE_BOARD_ID"); [ "$code" = 200 ] || fail "$code" "/boards/$BRIDGE_BOARD_ID"
    jq -r '(.data // .) | "ok: board \(.name) (project \(.project_id))"' "$TMP"
    ;;
  --find)
    [ -n "${2:-}" ] || die "--find needs a title fragment"
    code=$(get "/boards/$BRIDGE_BOARD_ID/view"); [ "$code" = 200 ] || fail "$code" "/boards/$BRIDGE_BOARD_ID/view"
    # the view can carry raw control characters inside task text; strip them before jq
    tr -d '\000-\010\013\014\016-\037' <"$TMP" | jq -r --arg q "$2" '
      (.data // .) | .tasks[]
      | select(.title | ascii_downcase | contains($q | ascii_downcase))
      | "\(.id)  [\(.status)]  \(.title)"'
    ;;
  --create)
    [ -f "${2:-}" ] || die "--create needs a card.json file"
    body=$(payload "$2")
    code=$(curl -sS -o "$TMP" -w '%{http_code}' -X POST \
      -H "Authorization: Bearer $BRIDGE_PAT" -H "Content-Type: application/json" \
      -H "Idempotency-Key: $(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid)" \
      --data "$body" "$BRIDGE_API_BASE/api/v1/projects/$BRIDGE_PROJECT_ID/tasks")
    [ "$code" = 201 ] || [ "$code" = 200 ] || fail "$code" "POST /projects/$BRIDGE_PROJECT_ID/tasks"
    jq -r '(.data // .) | "created: \(.id)  \(.title)"' "$TMP"
    ;;
  -h|--help|"")
    sed -n '2,24p' "$0"
    ;;
  *)
    [ -f "$1" ] || die "no such file: $1"
    echo "DRY RUN — would POST to $BRIDGE_API_BASE/api/v1/projects/$BRIDGE_PROJECT_ID/tasks:"
    payload "$1"
    ;;
esac
