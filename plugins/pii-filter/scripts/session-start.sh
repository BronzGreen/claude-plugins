#!/usr/bin/env bash
# SessionStart (sync, fast): tell Claude the filter is active and how to call the CLI.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${PII_FILTER_ENFORCED:-}" != "1" ] && [ "$(printf '%s' "${PII_FILTER:-}" | tr 'A-Z' 'a-z')" = "off" ]; then
  echo "PII-filter staat UIT in deze sessie (PII_FILTER=off)."; exit 0
fi
CLI="\"$PII_VENV_PY\" \"$PII_ROOT/scripts/pii.py\""
if [ -f "$PII_DATA/ready.json" ] && [ -x "$PII_VENV_PY" ]; then
  STATE="actief"
elif [ -f "$PII_DATA/setup-failed.json" ]; then
  STATE="NIET geïnstalleerd (zie $PII_DATA/setup-log.txt); databestanden worden geweigerd tot dit is opgelost. Meld dit aan de gebruiker"
else
  STATE="wordt op de achtergrond geïnstalleerd (eenmalig, enkele minuten); tot dan worden databestanden geweigerd"
fi
cat <<MSG
PII-filter (plugin pii-filter@bronzgreen): $STATE.
Read op databestanden (csv/json/log/eml/txt/sql/xml) geeft automatisch een gepseudonimiseerde kopie als er persoonsgegevens in staan; tokens als <PERSON_1> zijn consistente pseudoniemen.
Toon databestanden nooit via shell (cat/head/Get-Content/print van records). CLI: $CLI {scan|anonymize|text|status} — zie skill pii-filter:pii-filter.
MSG
