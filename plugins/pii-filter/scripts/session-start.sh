#!/usr/bin/env bash
# SessionStart (sync, fast): tell Claude the filter is active and how to call the CLI.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${PII_FILTER_ENFORCED:-}" != "1" ] && [ "$(printf '%s' "${PII_FILTER:-}" | tr 'A-Z' 'a-z')" = "off" ]; then
  pii_session_output "⚠️ PII-filter staat UIT in deze sessie (PII_FILTER=off)" \
    "PII-filter staat UIT in deze sessie (PII_FILTER=off)."; exit 0
fi
CLI="\"$PII_VENV_PY\" \"$PII_ROOT/scripts/pii.py\""
if [ -f "$PII_DATA/ready.json" ] && [ -x "$PII_VENV_PY" ]; then
  STATE="actief"; UI="🔒 PII-filter actief: databestanden worden gepseudonimiseerd"
elif [ -f "$PII_DATA/setup-failed.json" ]; then
  UI="⚠️ PII-filter NIET geïnstalleerd: databestanden worden geweigerd (zie $PII_DATA/setup-log.txt)"
  STATE="NIET geïnstalleerd (zie $PII_DATA/setup-log.txt); databestanden worden geweigerd tot dit is opgelost. Meld dit aan de gebruiker"
else
  UI="⏳ PII-filter wordt eenmalig geïnstalleerd; tot dan worden databestanden geweigerd"
  STATE="wordt op de achtergrond geïnstalleerd (eenmalig, enkele minuten); tot dan worden databestanden geweigerd"
fi
LEAKS=""
Q="$(ls "$PII_DATA/leaks/queue/"*.json 2>/dev/null | wc -l | tr -d ' ')"
[ "${Q:-0}" -gt 0 ] && UI="$UI · $Q datalekmelding(en) in wachtrij" && LEAKS="LET OP: $Q datalekmelding(en) staan nog in de lokale wachtrij (worden nu opnieuw verstuurd). Meld dit aan de gebruiker; status: CLI leaks."
if [ -z "${PII_BRIDGE_PAT:-}" ] && [ ! -f "${PII_FILTER_ENV:-$HOME/.config/pii-filter/env}" ]; then
  LEAKS="$LEAKS Geen BRIDGE-token ingesteld (~/.config/pii-filter/env): datalekmeldingen blijven lokaal tot dat is geregeld (README pii-filter)."
fi
CTX="$(cat <<MSG
PII-filter (plugin pii-filter@bronzgreen): $STATE.
Read op databestanden (csv/json/log/eml/txt/sql/xml) geeft automatisch een gepseudonimiseerde kopie als er persoonsgegevens in staan; tokens als <PERSON_1> zijn consistente pseudoniemen.
Toon databestanden nooit via shell (cat/head/Get-Content/print van records). CLI: $CLI {scan|anonymize|text|status|leaks|report-leak} — zie skills pii-filter:pii-filter en pii-filter:datalek-melden.
Glipt er toch PII door, dan meldt de plugin automatisch een datalek in BRIDGE (ISMS); zie je zelf PII die niet gefilterd is, gebruik dan skill pii-filter:datalek-melden. ${LEAKS}
MSG
)"
pii_session_output "$UI" "$CTX"
