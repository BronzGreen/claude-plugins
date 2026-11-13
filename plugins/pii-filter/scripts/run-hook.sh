#!/usr/bin/env bash
# PreToolUse entry point: find a Python and hand the hook payload (stdin) to pii_hook.py.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if ! PY="$(pii_host_python)"; then
  echo "pii-filter: geen Python gevonden; PII-filtering staat UIT. Installeer Python 3.12 of uv." >&2
  exit 0
fi
eval "exec $PY \"\$PII_ROOT/scripts/pii_hook.py\""
