---
name: datalek-melden
description: Meld een (mogelijk) datalek in BRIDGE (ISMS → datalekkenregister) wanneer persoonsgegevens ongefilterd bij Claude zijn terechtgekomen, met wat er gelekt is, hoe, en standaard een inschatting van de meldplicht. Gebruik wanneer je in tool-output, een geplakt bericht of een bestand echte namen, e-mailadressen, BSN's, IBAN's, adressen, postcodes, woonplaatsen, geboortedata of telefoonnummers ziet die NIET als <TOKEN_n> zijn gepseudonimiseerd; bij "datalek", "PII gelekt", "dat had niet door het filter mogen komen", "meld dit"; of om de status van eerdere meldingen te zien.
---

# Datalek melden (BRIDGE ISMS)

De plugin meldt **automatisch** na elke Read, shell-output en Grep-uitvoer:
harde kenmerken (e-mail van een persoon, geldige IBAN, BSN met 11-proef, 06/+31-nummer, vast nummer naast
"tel") én tabellen met persoonskolommen (`Naam`, `adres`, `postcode`, `woonplaats`, `geboortedatum`, …)
waarvan de waarden niet zijn vervangen. Deze skill is voor wat de automaat niet ziet: vooral **namen,
adressen en geboortedata in vrije tekst**, en gegevens die via een andere weg binnenkwamen (geplakt in de
chat, een MCP-tool, een script dat records printte).

Elke melding komt in BRIDGE → ISMS → Datalekken met status *open*, rol en meldbeslissing
*nog te bepalen*; BRIDGE mailt de privacy officer. Die neemt de meldbeslissing (72 uur als
verwerkingsverantwoordelijke). Jij geeft **altijd** een inschatting met motivering mee, maar beslist niet.

## Wat er in elke melding staat

In het BRIDGE-overzicht staat per melding één regel, `WAT · HOE · bij WIE`, bijvoorbeeld
`Naam, postcode, woonplaats · Read testdata.txt (filter miste) · bij Sanne de Wit`, met referentie
`DL-AI-<datum>-<4 letters>`. "Bij wie" is de medewerker bij wie het lek optrad: de eigenaar van het BRIDGE-token
(`/api/v1/auth/me`), of `MELDER=` in `~/.config/pii-filter/env`, of `--melder`. Nooit een betrokkene.
De toelichting heeft vaste kopjes: WAT, HOE, BIJ WIE, INSCHATTING MELDPLICHT, OVERIG.

- **WAT**: soort gegevens, aantal en vindplaats (bv. `naam 1x (kolom 'Naam')`, `postcode 1x (patroon in tekst)`).
  **Nooit de waarden zelf**: het register mag geen identificerende gegevens bevatten (BRIDGE-regel) en een
  kopie van het lek in het register is een tweede lek.
- **HOE**: tool (Read / shell / Grep / plak in chat / MCP), gefilterde kopie of origineel, bestandsnaam en
  -type, project. Een bestandsnaam die zelf persoonsgegevens lijkt te bevatten wordt weggelaten.
- **Inschatting meldplicht** (standaard, art. 33/34 AVG): `niet_melden` / `beoordelen` / `wel_melden`, met
  motivering en of betrokkenen geïnformeerd moeten worden. Automatische regel:
  - eigen gegevens van de melder (bewuste test) → niet melden;
  - BSN of creditcard bij 10+ betrokkenen → wel melden + betrokkenen informeren;
  - BSN/creditcard (minder betrokkenen), IBAN/geboortedata bij 10+, of 100+ betrokkenen → beoordelen;
  - anders (enkele contactgegevens bij verwerker Anthropic, niet verder verspreid) → niet melden, wel registreren;
  - `leak_check.verwerkersovereenkomst_anthropic: false` in de config → een niveau zwaarder.
- Het volledige bestandspad staat alleen lokaal (`leaks/sent.jsonl` in de plugin-datamap).

## Stappen

1. **Stop met de gegevens werken.** Herhaal ze niet in je antwoord, niet in code, commits, tests of bestanden.
2. **Bepaal wat je zag, zonder de waarden:** soorten en aantallen (`PERSON=3,EMAIL_ADDRESS=1`), waar het stond
   (kolom, regel, sectie), hoe het binnenkwam en het bestand. Toegestane typen: `PERSON`, `EMAIL_ADDRESS`,
   `PHONE_NUMBER`, `NL_BSN`, `IBAN_CODE`, `NL_ADDRESS`, `NL_POSTCODE`, `LOCATION`, `DATE_OF_BIRTH`,
   `CREDIT_CARD`, `IP_ADDRESS`, `OTHER`.
3. **Maak je inschatting** (niet_melden / beoordelen / wel_melden) met een korte motivering: wiens gegevens
   (eigen test, klant, medewerker), hoeveel betrokkenen, hoe gevoelig, verder verspreid of niet.
4. **Vraag de gebruiker kort om bevestiging** en noem daarbij al wat, hoe en je inschatting ("Ik zag 3 namen
   ongefilterd in de output van X; inschatting: niet melden aan de AP omdat …; zal ik dit registreren in
   BRIDGE?"). Bij de automatische melding is dit al gebeurd; meld dan niet dubbel.
5. **Meld** met het CLI-commando uit je sessiecontext (`"<venv-python>" "<plugin>/scripts/pii.py"`):
   ```
   <CLI> report-leak --types PERSON=3,NL_POSTCODE=1 \
     --waar "PERSON=kolom 'klantnaam'" --waar "NL_POSTCODE=regel 12" \
     --source "Bash-output importscript" --ext csv --file-name klanten.csv --betrokkenen 3 \
     --advies niet_melden --motivering "3 klantnamen, alleen in deze sessie bij verwerker Anthropic, niet verder gedeeld" \
     --note "importscript print klantregels naar stdout"
   ```
   - `--eigen-gegevens` als het gegevens van de melder zelf zijn (bv. een bewuste test).
   - Zonder `--advies` gebruikt de CLI de automatische inschatting; met `--advies` is `--motivering` verplicht
     en staat de automatische inschatting er ter vergelijking bij.
   - `--note`, `--motivering` en `--waar` beschrijven de situatie, **nooit** de gegevens (de CLI weigert
     e-mail/IBAN/BSN/telefoonnummers en persoonsgegevens-tabellen daarin; BRIDGE weigert BSN-achtige nummers).
     Geen namen van betrokkenen.
6. **Rapporteer** aan de gebruiker: referentie (`DL-AI-…`), geregistreerd of in wachtrij (en in welk BRIDGE:
   productie of `test.bridge…`), de termijn, wat er gelekt is, hoe, en de inschatting met motivering.
7. **Voorkom herhaling:** stel een aanvulling voor in `.pii-filter.json` (kolomnaam in `column_hints`,
   bestand niet meer in `exclude_globs`), pas het script aan zodat het geen records print, of meld een
   gemiste schrijfwijze in `BronzGreen/claude-plugins`.

## Status en problemen

```
<CLI> leaks            # token ingesteld? welk BRIDGE? wachtrij? laatst verzonden meldingen
<CLI> leaks --flush    # wachtrij nu versturen
```
- **Geen token / HTTP 401/403:** de melding staat veilig in de lokale wachtrij en gaat mee bij de volgende
  sessie. De gebruiker moet een BRIDGE-token met scope `isms.datalek.melden` in `~/.config/pii-filter/env`
  zetten (README pii-filter). Zeg dat; omzeil het niet.
- **BRIDGE onbereikbaar:** idem, wachtrij.
- Lokale details (welk bestandspad hoort bij welke referentie) staan alleen op deze machine in de
  plugin-datamap (`leaks/sent.jsonl`); de privacy officer kan de melder ernaar vragen.
