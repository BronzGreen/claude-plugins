---
name: datalek-melden
description: Meld een (mogelijk) datalek in BRIDGE (ISMS → datalekkenregister) wanneer persoonsgegevens ongefilterd bij Claude zijn terechtgekomen. Gebruik wanneer je in tool-output, een geplakt bericht of een bestand echte namen, e-mailadressen, BSN's, IBAN's, adressen of telefoonnummers ziet die NIET als <TOKEN_n> zijn gepseudonimiseerd; bij "datalek", "PII gelekt", "dat had niet door het filter mogen komen", "meld dit"; of om de status van eerdere meldingen te zien.
---

# Datalek melden (BRIDGE ISMS)

De plugin meldt harde kenmerken (e-mail, geldige IBAN, BSN met 11-proef, NL-mobiel) **automatisch**
na elke Read/shell-output van databestanden. Deze skill is voor wat de automaat niet ziet:
vooral **namen, adressen en geboortedata**, en gegevens die via een andere weg binnenkwamen
(geplakt in de chat, een MCP-tool, een script dat records printte).

Elke melding komt in BRIDGE → ISMS → Datalekken met status *open*, rol en meldbeslissing
*nog te bepalen*; BRIDGE mailt de privacy officer. Die beoordeelt binnen de termijn (72 uur
als verwerkingsverantwoordelijke) of het meldplichtig is. Jij beslist dat niet.

## Stappen

1. **Stop met de gegevens werken.** Herhaal ze niet in je antwoord, niet in code, commits, tests of bestanden.
2. **Bepaal wat je zag, zonder de waarden:** soorten en aantallen (`PERSON=3,EMAIL_ADDRESS=1`),
   hoe het binnenkwam (`Read`, `Bash-output`, `plak in chat`, `MCP <naam>`) en het bestandstype.
   Toegestane typen: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `NL_BSN`, `IBAN_CODE`, `NL_ADDRESS`,
   `NL_POSTCODE`, `LOCATION`, `DATE_OF_BIRTH`, `CREDIT_CARD`, `IP_ADDRESS`, `OTHER`.
3. **Vraag de gebruiker kort om bevestiging** ("Ik zag 3 namen ongefilterd in de output van X; zal ik
   dit als datalek melden in BRIDGE?"). Bij de automatische melding is dit al gebeurd; meld dan niet dubbel.
4. **Meld** met het CLI-commando uit je sessiecontext (`"<venv-python>" "<plugin>/scripts/pii.py"`):
   ```
   <CLI> report-leak --types PERSON=3 --source "Bash-output" --ext csv --note "importscript print klantregels naar stdout"
   ```
   `--note` beschrijft de situatie, **nooit** de gegevens (de CLI weigert e-mail/IBAN/BSN in de toelichting;
   BRIDGE weigert BSN-achtige nummers). Geen namen van betrokkenen.
5. **Rapporteer** aan de gebruiker: referentie (`DL-AI-…`), geregistreerd of in wachtrij, en de termijn.
6. **Voorkom herhaling:** stel een aanvulling voor in `.pii-filter.json` (kolomnaam in `column_hints`,
   bestand niet meer in `exclude_globs`), of pas het script aan zodat het geen records print.

## Status en problemen

```
<CLI> leaks            # token ingesteld? wachtrij? laatst verzonden meldingen
<CLI> leaks --flush    # wachtrij nu versturen
```
- **Geen token / HTTP 401/403:** de melding staat veilig in de lokale wachtrij en gaat mee bij de volgende
  sessie. De gebruiker moet een BRIDGE-token met scope `isms.datalek.melden` in `~/.config/pii-filter/env`
  zetten (README pii-filter). Zeg dat; omzeil het niet.
- **BRIDGE onbereikbaar:** idem, wachtrij.
- Lokale details (welk bestandspad hoort bij welke referentie) staan alleen op deze machine in de
  plugin-datamap (`leaks/sent.jsonl`); de privacy officer kan de melder ernaar vragen.
