#!/usr/bin/env bash
# One-time (and after requirement bumps) install of Presidio + spaCy models into the plugin data dir.
# Runs as an async SessionStart hook, so it never blocks the session. Safe to run by hand.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
mkdir -p "$PII_DATA"
LOG="$PII_DATA/setup-log.txt"
REQ="$PII_ROOT/scripts/requirements.txt"
READY="$PII_DATA/ready.json"
WANT="$( (cat "$REQ"; uname -s) | cksum | cut -d' ' -f1)"

if [ -f "$READY" ] && [ -x "$PII_VENV_PY" ] && grep -q "\"$WANT\"" "$READY"; then exit 0; fi

LOCK="$PII_DATA/setup.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  # another session is installing; break the lock only if it is older than 30 minutes
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then rm -rf "$LOCK"; mkdir "$LOCK" || exit 0; else exit 0; fi
fi
trap 'rm -rf "$LOCK"' EXIT
rm -f "$READY"
exec >>"$LOG" 2>&1
echo "=== $(date) pii-filter setup (req $WANT) ==="

if command -v uv >/dev/null 2>&1; then
  echo "using uv"
  uv venv --python 3.12 --allow-existing "$PII_VENV" || exit 1
  PII_VENV_PY="$( [ -x "$PII_VENV/Scripts/python.exe" ] && echo "$PII_VENV/Scripts/python.exe" || echo "$PII_VENV/bin/python")"
  uv pip install --python "$PII_VENV_PY" -r "$REQ" || exit 1
else
  BASEPY=""
  for c in "py -3.12" "py -3.13" "py -3.11" "py -3.10" python3.12 python3.13 python3.11 python3.10 python3 python; do
    if _py_ok "$c" 10 13; then BASEPY="$c"; break; fi
  done
  if [ -z "$BASEPY" ]; then
    echo "FOUT: geen Python 3.10-3.13 gevonden. Installeer uv (brew install uv / winget install astral-sh.uv) of Python 3.12."
    echo '{"error":"no suitable python"}' >"$PII_DATA/setup-failed.json"
    exit 1
  fi
  echo "using $BASEPY"
  # shellcheck disable=SC2086
  $BASEPY -m venv "$PII_VENV" || exit 1
  PII_VENV_PY="$( [ -x "$PII_VENV/Scripts/python.exe" ] && echo "$PII_VENV/Scripts/python.exe" || echo "$PII_VENV/bin/python")"
  "$PII_VENV_PY" -m pip install -q --upgrade pip
  "$PII_VENV_PY" -m pip install -q -r "$REQ" || exit 1
fi

# smoke test: must find a person and an e-mail address
OUT="$("$PII_VENV_PY" "$PII_ROOT/scripts/pii.py" status >/dev/null && \
  PII_VAULT_DIR="$PII_DATA/selftest-vault" "$PII_VENV_PY" "$PII_ROOT/scripts/pii.py" text "Jan de Vries mailt naar jan@voorbeeld.nl")"
rm -rf "$PII_DATA/selftest-vault"
echo "selftest: $OUT"
case "$OUT" in *"<EMAIL_ADDRESS_1>"*) ;; *) echo "FOUT: selftest mislukt"; exit 1;; esac
rm -f "$PII_DATA/setup-failed.json"
printf '{"req":"%s","date":"%s"}\n' "$WANT" "$(date +%F)" >"$READY"
echo "=== klaar ==="
