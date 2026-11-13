---
name: pii-filter
description: Lokale PII-filtering met Microsoft Presidio (NL + EN): pseudonimiseert namen, e-mail, telefoon, BSN, IBAN, adressen, postcodes, woonplaatsen en geboortedata in elk bestand dat Claude leest (csv/xlsx/json/log/eml/txt, pdf/docx/pptx, en code/markdown met persoonsgegevens) vóórdat de inhoud in de chat komt. Gebruik bij elk werk met echte klant-, personeels- of gebruikersdata (exports, dumps, logs, mails, fixtures uit productie), bij "anonimiseer", "pseudonimiseer", "PII", "AVG/GDPR", "persoonsgegevens", "privacy-filter", of wanneer de PII-filter-hook een Read heeft omgeleid of een commando heeft geweigerd.
---

# PII-filter (Microsoft Presidio, volledig lokaal)

Doel: met echte data blijven ontwikkelen zonder dat persoonsgegevens in de context belanden.
Alles draait lokaal; er gaat niets naar een externe dienst.

## Wat de plugin automatisch doet (hooks, ook voor subagents)

| Tool | Gedrag |
|---|---|
| `Read` op `.csv .tsv .txt .log .json .jsonl .ndjson .xml .eml .sql .vcf` | Presidio scant lokaal. PII gevonden → je leest een gepseudonimiseerde kopie (`~/.claude/pii-vault/cache/…pii-sanitized…`). Geen PII → je leest gewoon het origineel. Een `.txt`/`.log` die eigenlijk een tabel is (kopregel + `;`/tab/`\|`) wordt als tabel behandeld, dus kolomnamen gelden. |
| `Read` op `.pdf .docx .pptx .xlsx .odt .ods` | Tekst (ook tabellen, kop/voettekst, opmerkingen, notities) wordt eruit gehaald en gefilterd; je leest een `.txt`-versie. Schone pdf → origineel. Pdf met alleen scans (geen tekstlaag) → geweigerd; gedeeltelijk gescand → die pagina's worden overgeslagen en genoemd. |
| `Read` op alle andere tekst (code, markdown, html, yaml, …) | Snelle controle op harde kenmerken (e-mail van een persoon, IBAN, BSN, 06/+31-nummer) en tabellen met persoonskolommen. Treffer → volledig gefilterd zoals hierboven. Functionele adressen (`info@`, `noreply@`), testdomeinen (`.test`, `example.com`) en bekende voorbeeldnummers tellen niet. |
| `Bash`/`PowerShell` die een data- of documentbestand rauw toont (`cat`, `head`, `Get-Content`, `Import-Csv`, `grep`, `jq`, `pdftotext`, `pandoc`, …) | Geweigerd met instructie om de CLI te gebruiken. Uitgezonderde bestanden (`requirements.txt`, `package.json`, …) mogen wel. |
| `Grep` met `output_mode: content` op databestanden | Geweigerd. `files_with_matches`/`count` mag wel. Andere Grep-uitvoer wordt achteraf gecontroleerd. |
| Alles rond `pii-vault/vault*` | Altijd geweigerd: daar staan de echte waarden. |
| Afbeeldingen | Doorgelaten (geen OCR). `hook.block_images: true` blokkeert ze. |

Uitgezonderd (`exclude_globs`): `node_modules`, `.git`, `.claude/`, `package.json`, `tsconfig`, lockfiles, … Na elke Read/shell/Grep controleert de plugin wat je echt ontving; zie skill `pii-filter:datalek-melden`.
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
- Woonplaatsenlijst (CBS, 2.426 plaatsen): `LOCATION`; plaatsnamen die ook gewone woorden zijn (Best, Born, Hoek, …) alleen met context ("woont in", "woonplaats")
- Presidio standaard: `EMAIL_ADDRESS`, `PHONE_NUMBER` (NL/BE/DE/GB/FR/US), `IBAN_CODE`, `CREDIT_CARD`, `IP_ADDRESS`
- Eigen NL-regels, in veel schrijfwijzen:
  - `NL_BSN` (11-proef): `123456782`, `1234.56.782`, `123-45-678`, `123 456 782`, 8 cijfers (voorloopnul kwijt) met context
  - `NL_POSTCODE`: `1234 AB`, `1234AB`, `1234-AB`, `1234ab` (+ plaatsnaam); `1234 ab` alleen met context. Eenheden (`1500ms`, `1024px`) en kleurcodes niet
  - `PHONE_NUMBER`: `06-12345678`, `06 12 34 56 78`, `(06) 1234 5678`, `06.12.34.56.78`, `+31 6 …`, `+31 (0)6 …`, `0031 …`, `045-1234567`, `(045) 123 45 67`; kale 10 cijfers alleen met context
  - `IBAN_CODE`: ook kleine letters en met punten/streepjes (`nl91abna…`, `NL91-ABNA-…`), mod-97
  - `NL_ADDRESS`: `Hoofdstraat 12`, `hoofdstraat 12a`, `Hoofdstr. 12`, `Kerkplein 4-II`, `Molenweg 8 bus 3`, `Dorpsstraat nr. 7`, `Laan van Meerdervoort 120`
  - `EMAIL_ADDRESS` verhuld: `jan [at] bedrijf [dot] nl`, `jan(at)bedrijf.nl`
  - `DATE_OF_BIRTH`: datums (`12-03-1985`, `1985-03-12`, `12 maart 1985`) alleen met context ("geboren", "geb.", "geboortedatum")
- Kolomnamen: hele cel bij `naam`, `achternaam`, `email`, `telefoon`, `bsn`, `iban`, `adres`, `postcode`, `woonplaats`, `geboortedatum`, …, in csv/tsv, tabel-achtige txt/log, xlsx/docx-tabellen
- Bewust niet standaard: losse datums zonder context, organisatienamen, URL's (te veel ruis)

## Uitzetten / afdwingen

- Eén sessie uit: `PII_FILTER=off` vóór het starten van `claude`. Per project: `"enabled": false` in `.pii-filter.json`.
- Als de organisatie `PII_FILTER_ENFORCED=1` zet (managed settings), werken die uitschakelaars niet en is fail-open uitgeschakeld.

## Grenzen

Detectie is statistisch: soms wordt een naam gemist (vooral een losse voornaam in vrije tekst) of een woord te veel vervangen. De hooks dekken `Read`, shell-viewers en `Grep`; een script dat zelf records print, MCP-tools, WebFetch en tekst in afbeeldingen vallen erbuiten. Een sterk vangnet, geen garantie.

Gevolg van "alle bestanden": een code- of markdownbestand met persoonsgegevens wordt omgeleid en is dan niet met `Edit` te bewerken. Gaat het om verzonnen testdata, vraag de gebruiker dan of het bestand in `hook.exclude_globs` mag (of `leak_check.ignore_email_domains` voor een testdomein).
