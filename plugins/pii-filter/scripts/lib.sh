# Shared helpers for pii-filter hook scripts (bash; Git Bash on Windows).

# Paths in "mixed" form (C:/Users/..) so both bash and native Windows Python understand them.
_mixed() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

PII_ROOT="$(_mixed "${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}")"
PII_DATA="$(_mixed "${CLAUDE_PLUGIN_DATA:-$HOME/.claude/pii-filter}")"
PII_VENV="$PII_DATA/venv"
if [ -x "$PII_VENV/Scripts/python.exe" ] || [ -d "$PII_VENV/Scripts" ]; then
  PII_VENV_PY="$PII_VENV/Scripts/python.exe"
else
  PII_VENV_PY="$PII_VENV/bin/python"
fi
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) PII_VENV_PY="$PII_VENV/Scripts/python.exe";; esac
export CLAUDE_PLUGIN_ROOT="$PII_ROOT" CLAUDE_PLUGIN_DATA="$PII_DATA" PYTHONIOENCODING=utf-8

# Run a python candidate ("py -3.12", "python3", ...) and check its version is within [min,max].
_py_ok() { # $1=candidate words, $2=min minor, $3=max minor
  # shellcheck disable=SC2086
  $1 -c "import sys; sys.exit(0 if sys.version_info[0]==3 and $2<=sys.version_info[1]<=$3 else 1)" >/dev/null 2>&1
}

# Any Python >= 3.8 for the stdlib-only hook; venv python preferred. Cached per machine.
pii_host_python() {
  if [ -x "$PII_VENV_PY" ]; then printf '%s' "\"$PII_VENV_PY\""; return 0; fi
  local cache="$PII_DATA/hostpython" c
  if [ -f "$cache" ]; then c="$(cat "$cache")"; if _py_ok "$c" 8 99; then printf '%s' "$c"; return 0; fi; fi
  for c in python3 python "py -3"; do
    if _py_ok "$c" 8 99; then mkdir -p "$PII_DATA"; printf '%s' "$c" >"$cache"; printf '%s' "$c"; return 0; fi
  done
  return 1
}
