---
name: pii-filter
description: Lokale PII-filtering met Microsoft Presidio (NL + EN): pseudonimiseert namen, e-mail, telefoon, BSN, IBAN, adressen, postcodes en woonplaatsen in csv/xlsx/json/log/eml/txt vóórdat de inhoud in de chat komt. Gebruik bij elk werk met echte klant-, personeels- of gebruikersdata (exports, dumps, logs, mails, fixtures uit productie), bij "anonimiseer", "pseudonimiseer", "PII", "AVG/GDPR", "persoonsgegevens", "privacy-filter", of wanneer de PII-filter-hook een Read heeft omgeleid of een commando heeft geweigerd.
---

# PII-filter (Microsoft Presidio, volledig lokaal)

Doel: met echte data blijven ontwikkelen zonder dat persoonsgegevens in de context belanden.
Alles draait lokaal; er gaat niets naar een externe dienst.

## Wat de plugin automatisch doet (hooks, ook voor subagents)

| Tool | Gedrag |
|---|---|
| `Read` op `.csv .tsv .txt .log .json .jsonl .ndjson .xml .eml .sql .vcf` | Presidio scant lokaal. PII gevonden → je leest een gepseudonimiseerde kopie (`~/.claude/pii-vault/cache/…pii-sanitized…`). Geen PII → je leest gewoon het origineel. |
| `Bash`/`PowerShell` die een databestand rauw toont (`cat`, `head`, `Get-Content`, `Import-Csv`, `grep`, `jq`, …) | Geweigerd met instructie om de CLI te gebruiken. |
| `Grep` met `output_mode: content` op databestanden | Geweigerd. `files_with_matches`/`count` mag wel. |
| Alles rond `pii-vault/vault*` | Altijd geweigerd: daar staan de echte waarden. |

Code en config (`package.json`, `tsconfig`, `node_modules`, `.claude/`, …) worden nooit gefilterd.
Bij de sessiestart staat in je context of het filter actief is en wat het exacte CLI-commando is (`"<venv-python>" "<plugin>/scripts/pii.py"`). Dat commando staat ook in elke weigering van de hook.

## Werkafspraken

1. **Tokens zijn data, geen fouten.** `<PERSON_3>`, `<EMAIL_ADDRESS_1>`, `<NL_BSN_2>` zijn consistente pseudoniemen: dezelfde echte waarde krijgt overal hetzelfde token, dus relaties/joins kloppen. Schrijf geen code die op tokens leunt; code moet op echte waarden werken.
2. **Lees data via `Read`** of via een geanonimiseerde kopie. Nooit via shell-commando's die inhoud printen, en nooit via een Python/pandas/node-one-liner die records naar stdout print: dat ziet de hook niet, dat is jouw verantwoordelijkheid.
3. **Code die data verwerkt mag gewoon draaien** (importer, tests, migratie), zolang er geen ruwe records geprint worden. Output bekijken? Schrijf naar een bestand en lees dat met `Read`, of pipe door `<CLI> anonymize -`.
4. **Nooit echte waarden terug in de chat.** `deanonymize` schrijft alleen naar een bestand; dat bestand lees je daarna niet.
5. **Omgeleid bestand bewerken?** Een omgeleide Read telt niet als Read van het origineel, dus `Edit` faalt. Vraag de gebruiker of het bestand in `.pii-filter.json` → `hook.exclude_globs` mag.
6. **"PII-filter wordt nog geïnstalleerd"** → meld het de gebruiker; eerste installatie duurt een paar minuten. Ga niet om de weigering heen.
7. Mist het filter iets of filtert het te veel: stel een aanvulling voor in `.pii-filter.json` (zie hieronder) of meld het in `BronzGreen/claude-plugins`.

## CLI

```
<CLI> status                               # geïnstalleerd? actief? welke configs?
<CLI> scan bestand.csv                     # tellingen per type + regelnummers, GEEN waarden
<CLI> anonymize bestand.xlsx               # kopie in pii-vault/cache, print pad + tellingen
<CLI> anonymize bestand.csv -o uit.csv     # kopie naar eigen pad (bv. test-fixture)
<CLI> anonymize bestand.log --max-lines 2000
some_command | <CLI> anonymize -           # stdin -> gefilterde stdout
<CLI> text "Jan de Vries, 06-12345678"     # losse tekst
<CLI> deanonymize antwoord.txt -o echt.txt # tokens -> echte waarden (alleen naar bestand)
<CLI> vault stats
```
Opties: `--lang en` (standaard `nl`), `--project <map>` (welke `.pii-filter.json` geldt; standaard de huidige map).
`.xlsx` kan `Read` niet tonen: `anonymize` en verder werken op de kopie.

## Configuratie (lagen, later vult aan)

1. `config.default.json` in de plugin (BronzGreen-standaard)
2. `~/.claude/pii-filter.json` (persoonlijk)
3. `.pii-filter.json` in de projectroot (committen, geldt voor het hele team)

Lijsten worden aangevuld, `column_hints` samengevoegd, losse waarden vervangen. Voorbeeld `.pii-filter.json`:
```json
{
  "allow_list": ["Toteco", "Hilzijn"],
  "column_hints": { "debiteurnaam|relatie": "PERSON" },
  "hook": { "exclude_globs": ["*/src/i18n/*.json", "*/testdata/synthetic/*"] }
}
```
`entities` vervangt de lijst in z'n geheel (bv. `DATE_TIME`, `ORGANIZATION` of `URL` toevoegen).

## Wat wordt gedetecteerd

- spaCy `nl_core_news_md` via Presidio: `PERSON`, `LOCATION`
- Presidio standaard: `EMAIL_ADDRESS`, `PHONE_NUMBER` (NL/BE/DE/GB/FR/US), `IBAN_CODE`, `CREDIT_CARD`, `IP_ADDRESS`
- Eigen NL-regels: `NL_BSN` (11-proef), `NL_POSTCODE` (+ plaatsnaam), `NL_ADDRESS` (straat + huisnummer + toevoeging), NL-mobiel
- Kolomnamen: hele cel bij `naam`, `achternaam`, `email`, `telefoon`, `bsn`, `iban`, `adres`, `postcode`, `woonplaats`, `geboortedatum`, …
- Bewust niet standaard: datums in vrije tekst, organisatienamen, URL's (te veel ruis)

## Uitzetten / afdwingen

- Eén sessie uit: `PII_FILTER=off` vóór het starten van `claude`. Per project: `"enabled": false` in `.pii-filter.json`.
- Als de organisatie `PII_FILTER_ENFORCED=1` zet (managed settings), werken die uitschakelaars niet en is fail-open uitgeschakeld.

## Grenzen

Detectie is statistisch: soms wordt een naam gemist of een woord te veel vervangen. De hooks dekken `Read`, shell-viewers en `Grep`; een script dat zelf records print, MCP-tools en WebFetch vallen erbuiten. Een sterk vangnet, geen garantie.
