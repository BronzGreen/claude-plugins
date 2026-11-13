#!/usr/bin/env bash
# Hook entry point: find a Python and hand the hook payload (stdin) to a hook script.
# Usage: run-hook.sh [pre|post|flush]   (default: pre)
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if ! PY="$(pii_host_python)"; then
  echo "pii-filter: geen Python gevonden; PII-filtering staat UIT. Installeer Python 3.12 of uv." >&2
  exit 0
fi
case "${1:-pre}" in
  post)  eval "exec $PY \"\$PII_ROOT/scripts/pii_posthook.py\"" ;;
  flush) eval "exec $PY \"\$PII_ROOT/scripts/pii_posthook.py\" --flush" ;;
  *)     eval "exec $PY \"\$PII_ROOT/scripts/pii_hook.py\"" ;;
esac
