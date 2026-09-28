#!/usr/bin/env bash
# ledger.sh — remember which Plaud recordings were already turned into cards.
# Stores ids and dates only (never titles, summaries or transcripts), per user:
#   ~/.local/state/plaud-kit/ledger.tsv   <recording_id> TAB <processed_at> TAB <card_ids|skipped>
#
# Usage:
#   ledger.sh seen <recording_id>              # exit 0 if already processed
#   ledger.sh add <recording_id> <card_ids|skipped>
#   ledger.sh last                             # date (YYYY-MM-DD) of the most recent entry
set -euo pipefail

DIR=${PLAUD_KIT_STATE:-$HOME/.local/state/plaud-kit}
LEDGER="$DIR/ledger.tsv"
mkdir -p "$DIR"; chmod 700 "$DIR"; touch "$LEDGER"; chmod 600 "$LEDGER"

case "${1:-}" in
  seen) [ -n "${2:-}" ] || exit 2; cut -f1 "$LEDGER" | grep -qxF "$2" ;;
  add)  [ -n "${2:-}" ] && [ -n "${3:-}" ] || exit 2
        printf '%s\t%s\t%s\n' "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" >>"$LEDGER" ;;
  last) cut -f2 "$LEDGER" | sort | tail -1 | cut -c1-10 ;;
  *)    sed -n '2,10p' "$0"; exit 2 ;;
esac
