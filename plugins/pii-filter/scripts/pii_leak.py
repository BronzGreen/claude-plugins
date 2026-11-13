"""Second line of defence: detect personal data that still reached Claude, and report it
as an AVG datalek in BRIDGE (ISMS -> datalekkenregister). Standard library only.

Detection is deliberately verifiable (few false positives):
  EMAIL_ADDRESS  e-mail address (reserved example/test domains and allow-listed domains ignored)
  IBAN_CODE      IBAN with a valid mod-97 checksum (spaces, dots, dashes, lower case)
  NL_BSN         9 digits (also 1234.56.789 / 123-45-678 / 123 456 789) passing the 11-proef,
                 with a BSN keyword nearby
  PHONE_NUMBER   Dutch mobile number (06 / +31 6 / 0031 6, any separators), international +31
                 numbers, and landlines next to a phone keyword
  table columns  a header with a known column name (naam, adres, postcode, woonplaats,
                 geboortedatum, telefoon, ...) followed by rows whose values are not tokens

The report NEVER contains the detected values: it says WHICH kinds of data (type, count, column)
leaked and HOW (tool, file name, filtered copy or original), plus an assessment of whether the
leak has to be reported to the Autoriteit Persoonsgegevens. The privacy officer decides.
The full file path stays on this machine in sent.jsonl / the queue.

Credentials (per user, never in a repo):
  ~/.config/pii-filter/env        BRIDGE_PAT=bgp_...   (scope isms.datalek.melden)
                                  BRIDGE_API_BASE=https://bridge.bronzgreen.com   (optional)
  or environment variables PII_BRIDGE_PAT / PII_BRIDGE_API_BASE.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pii_config as pc

LEAK_DIR = pc.DATA_DIR / "leaks"
QUEUE_DIR = LEAK_DIR / "queue"
SENT_LOG = LEAK_DIR / "sent.jsonl"
STATE_FILE = LEAK_DIR / "seen.json"
ENV_FILE = Path(os.environ.get("PII_FILTER_ENV") or Path.home() / ".config" / "pii-filter" / "env")
DEFAULT_API = "https://bridge.bronzgreen.com"

TOKEN_RE = re.compile(r"<[A-Z][A-Z0-9_]*_\d+>")
EMAIL_RE = re.compile(
    r"(?<![\w.+-])[\w.+-]+(?:@|\s?\[at\]\s?|\(at\))([A-Za-z0-9-]+(?:(?:\.|\s?\[dot\]\s?)[A-Za-z0-9-]+)*"
    r"(?:\.|\s?\[dot\]\s?)[A-Za-z]{2,})(?![\w-])")
IBAN_COUNTRIES = "NL|BE|DE|FR|GB|LU|ES|IT|AT|CH|IE|PT|DK|SE|NO|FI|PL"
IBAN_RE = re.compile(rf"\b((?:{IBAN_COUNTRIES})\d{{2}}(?:[ .\-]?[A-Z0-9]{{4}}){{2,7}}(?:[ .\-]?[A-Z0-9]{{1,3}})?)\b")
IBAN_NL_LC_RE = re.compile(r"\b(nl\d{2}[ .\-]?[a-z]{4}(?:[ .\-]?\d){10})\b")
BSN_RE = re.compile(r"(?<![\d.,\-])(\d{2,4}(?:[ .\-]?\d{2,4}){1,3}|\d{8,9})(?![\d]|[ .\-]\d)")
BSN_CONTEXT = re.compile(r"(?i)\b(bsn|burgerservicenummer|sofi(?:nummer)?|persoonsnummer)\b")
SEP = r"[\s.\-/)]{0,2}"
MOBILE_RE = re.compile(r"(?<![\w+(])(?:(?:\+|00)\s?31[\s.\-]?(?:\(0\)[\s.\-]?)?|\(?0)6\)?(?:" + SEP + r"\d){8}(?!\d)")
INTL_RE = re.compile(r"(?<![\w+])(?:\+|00)\s?31[\s.\-]?(?:\(0\)[\s.\-]?)?[1-9](?:" + SEP + r"\d){8}(?!\d)")
LANDLINE_RE = re.compile(r"(?<![\w+(])\(?0[1-57-9]\d{1,2}\)?\s?[\s.\-/]?\s?\d(?:[\s.\-]?\d){5,6}(?!\d)")
PHONE_CONTEXT = re.compile(r"(?i)\b(tel|telefoon|telefoonnummer|mobiel|gsm|bel|phone|fax|telnr)\b")
RESERVED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "example.nl", "voorbeeld.nl",
                          "test.nl", "test.com", "localhost", "invalid", "users.noreply.github.com",
                          "anthropic.com", "noreply.github.com")
# Not personal data: role mailboxes, reserved test TLDs, and well-known example numbers that appear in
# docs and test fixtures everywhere. (The full Presidio filter on data files still replaces them.)
ROLE_MAILBOXES = re.compile(
    r"(?i)^(info|contact|no-?reply|donotreply|do-not-reply|support|helpdesk|service|klantenservice|admin|"
    r"administratie|privacy|fg|dpo|sales|verkoop|hr|personeelszaken|office|secretariaat|receptie|facturen|"
    r"factuur|invoices?|billing|boekhouding|finance|financien|team|hello|hallo|mail|post|webmaster|postmaster|"
    r"hostmaster|abuse|security|jobs|vacatures|werken|marketing|pers|press|communicatie|events?|bestellingen|"
    r"orders?|inkoop|planning|test|demo|example|voorbeeld|user|gebruiker|bot|notifications?|alerts?|ci|"
    r"devops|ict|it|servicedesk|directie|bestuur|redactie|nieuwsbrief|newsletter|aanmelden|inschrijving|"
    r"leerlingenadministratie|ouders|school|kantoor|algemeen)([.+_-].*)?$")
RESERVED_TLDS = (".test", ".example", ".invalid", ".localhost", ".local", ".internal", ".lan")
EXAMPLE_IBANS = {"NL91ABNA0417164300", "NL02ABNA0123456789", "NL20INGB0001234567", "NL69INGB0123456789",
                 "DE89370400440532013000", "GB82WEST12345698765432", "BE68539007547034", "FR1420041010050500013M02606"}
EXAMPLE_BSNS = {"123456782", "111222333", "999999990", "000000000"}


def _placeholder_digits(d: str) -> bool:
    tail = d[-8:]
    return tail in ("12345678", "87654321", "23456789", "01234567") or len(set(tail)) == 1


LABELS = {"EMAIL_ADDRESS": "e-mailadres", "IBAN_CODE": "IBAN", "NL_BSN": "BSN",
          "PHONE_NUMBER": "telefoonnummer", "PERSON": "naam", "NL_ADDRESS": "adres",
          "NL_POSTCODE": "postcode", "LOCATION": "woonplaats", "DATE_OF_BIRTH": "geboortedatum",
          "CREDIT_CARD": "creditcardnummer", "IP_ADDRESS": "IP-adres", "OTHER": "overig"}

# Column names for the table check. Stricter than the filter's column_hints: a bare "name"
# column in code/docs is usually a product or field name, not a person.
TABLE_COLUMNS = [
    (r"(voor|achter|roep|volledige|klant|contact|medewerker|werknemer|patient|patiënt)?naam|"
     r"(first|last|full|given|family|sur)name|contactpersoon|voorletters|initialen", "PERSON"),
    (r"(woon|post|bezoek|factuur)?adres(regel)?\d?|straat(naam)?|address(line)?\d?|street", "NL_ADDRESS"),
    (r"postcode|zip(code)?|postalcode", "NL_POSTCODE"),
    (r"woonplaats|plaats|city|stad|residence", "LOCATION"),
    (r"geboortedatum|geb(oorte)?datum|dateofbirth|birthdate|dob", "DATE_OF_BIRTH"),
    (r"(tel|telefoon|telefoonnummer|mobiel|mobielnummer|gsm|phone|mobile|telnr)(nummer|nr)?\d?", "PHONE_NUMBER"),
    (r"e?mail(adres)?|emailaddress", "EMAIL_ADDRESS"),
    (r"bsn|burgerservicenummer|sofinummer|ssn", "NL_BSN"),
    (r"iban|rekeningnummer|bankrekening|rekeningnr", "IBAN_CODE"),
]
TABLE_COLUMNS = [(re.compile(p), e) for p, e in TABLE_COLUMNS]
VALUE_SHAPE = {
    "PERSON": re.compile(r"[A-ZÀ-Ý][\w'’.\-]*(?:\s+[\w'’.\-]+){0,5}"),
    "NL_ADDRESS": re.compile(r"(?=.*[A-Za-z]{3})(?=.*\d).{4,80}"),
    "NL_POSTCODE": re.compile(r"[1-9]\d{3}\s?[A-Za-z]{2}"),
    "LOCATION": re.compile(r"(?:'s-)?[A-Z][\w'’\-]+(?:[\s\-][\w'’\-]+){0,4}"),
    "DATE_OF_BIRTH": re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}\s\w+\.?\s\d{4}"),
    "PHONE_NUMBER": re.compile(r"[+(]?\d[\d\s().\-/]{8,18}"),
    "EMAIL_ADDRESS": re.compile(r"\S+@\S+\.\w{2,}"),
    "NL_BSN": re.compile(r"\d[\d .\-]{7,12}"),
    "IBAN_CODE": re.compile(r"[A-Za-z]{2}\d{2}[A-Za-z0-9 .\-]{10,32}"),
}


# --------------------------------------------------------------------------- detection
def _iban_ok(raw: str) -> bool:
    s = re.sub(r"[ .\-]", "", raw).upper()
    if not 15 <= len(s) <= 34:
        return False
    num = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(num) % 97 == 1


def _bsn_ok(raw: str) -> bool:
    d = re.sub(r"\D", "", raw)
    if len(d) == 8:
        d = "0" + d
    if len(d) != 9 or d == "000000000":
        return False
    return (sum(int(x) * w for x, w in zip(d[:8], range(9, 1, -1))) - int(d[8])) % 11 == 0


def _phone_ok(raw: str) -> bool:
    d = re.sub(r"\D", "", raw)
    if raw.strip().lstrip("(").startswith("+") or d.startswith("0031"):
        d = d[4:] if d.startswith("0031") else d[2:]
        d = "0" + (d[1:] if d.startswith("0") else d)
    return len(d) == 10 and d[0] == "0" and d[1] != "0"


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9ëéï]", "", h.lower())


def _table_hits(text: str, add) -> None:
    """Header row with known column names, then rows with plain (non-token) values in those columns."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip().strip("|")
        delim = next((d for d in (";", "\t", "|", ",") if line.count(d) >= 1), None)
        raw = [c.strip().strip('"') for c in line.split(delim)] if delim else []
        # a header is a row of short labels, not a sentence with a comma in it
        if delim and all(len(c) <= 40 and len(c.split()) <= 3 for c in raw):
            header = [_norm_header(c) for c in raw]
            cols = {}
            for ci, h in enumerate(header):
                for rx, ent in TABLE_COLUMNS:
                    if h and rx.fullmatch(h):
                        cols[ci] = ent
                        break
            if cols and (delim != "," or len(cols) >= 2):
                n = line.count(delim)
                j = i + 1
                while j < len(lines) and lines[j].strip().strip("|").count(delim) == n:
                    cells = [c.strip().strip('"') for c in lines[j].strip().strip("|").split(delim)]
                    for ci, ent in cols.items():
                        if ci >= len(cells):
                            continue
                        v = cells[ci]
                        if (not v or TOKEN_RE.search(v) or re.fullmatch(r"[\s\-:=_.]+", v)
                                or v.lower() in ("null", "none", "n/a", "onbekend")):
                            continue
                        if VALUE_SHAPE[ent].fullmatch(v):
                            add(ent, v, f"kolom '{lines[i].strip().strip('|').split(delim)[ci].strip()}'")
                    j += 1
                i = j
                continue
        i += 1


def detect(text: str, cfg: dict, details: list | None = None) -> dict:
    """Return {entity: set_of_value_hashes}. Values themselves are never kept.

    details (optional list) receives {"type", "basis"} per distinct finding, e.g. basis
    "kolom 'Naam'" or "patroon in tekst"; never the value.
    """
    lc = cfg.get("leak_check", {})
    ignore_domains = tuple(d.lower() for d in (*RESERVED_EMAIL_DOMAINS, *lc.get("ignore_email_domains", [])))
    allow = {a.lower() for a in cfg.get("allow_list", [])}
    found: dict[str, set] = {}

    def add(kind, value, basis="patroon in tekst"):
        h = hashlib.sha256(re.sub(r"[\s.\-()/]", "", value.lower()).encode()).hexdigest()[:12]
        if h in found.get(kind, set()):
            return
        found.setdefault(kind, set()).add(h)
        if details is not None:
            details.append({"type": kind, "basis": basis})

    _table_hits(text, add)
    text = TOKEN_RE.sub(" ", text)
    for m in EMAIL_RE.finditer(text):
        dom = re.sub(r"\s?\[dot\]\s?", ".", m.group(1).lower())
        local = re.split(r"@|\s?\[at\]\s?|\(at\)", m.group(0))[0]
        if (dom.endswith(ignore_domains) or dom.endswith(RESERVED_TLDS) or m.group(0).lower() in allow
                or ROLE_MAILBOXES.match(local)):
            continue
        add("EMAIL_ADDRESS", m.group(0))
    for rx in (IBAN_RE, IBAN_NL_LC_RE):
        for m in rx.finditer(text):
            v = re.sub(r"[ .\-]", "", m.group(1)).upper()
            if _iban_ok(v) and v not in EXAMPLE_IBANS and not _placeholder_digits(v):
                add("IBAN_CODE", v)
    for m in BSN_RE.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 20]
        d = re.sub(r"\D", "", m.group(1)).zfill(9)
        if _bsn_ok(m.group(1)) and BSN_CONTEXT.search(window) and d not in EXAMPLE_BSNS:
            add("NL_BSN", d)
    phones = [m for m in MOBILE_RE.finditer(text)] + [m for m in INTL_RE.finditer(text)]
    for m in LANDLINE_RE.finditer(text):
        if PHONE_CONTEXT.search(text[max(0, m.start() - 40): m.start()]):
            phones.append(m)
    for m in phones:
        d = re.sub(r"\D", "", m.group(0))
        if _phone_ok(m.group(0)) and not _placeholder_digits(d):
            add("PHONE_NUMBER", d[-9:])
    return found


def describe(found: dict, details: list | None = None) -> str:
    """'naam 1x (kolom 'Naam'), postcode 1x (kolom 'postcode')' -- types and where, never values."""
    parts = []
    for k in _ordered(found):
        bases = sorted({d["basis"] for d in (details or []) if d["type"] == k})
        where = f" ({', '.join(bases)})" if bases else ""
        parts.append(f"{LABELS.get(k, k)} {len(found[k])}x{where}")
    return ", ".join(parts)


# --------------------------------------------------------------------------- assessment
ADVIES_LABEL = {"niet_melden": "niet melden aan de AP (wel registreren)",
                "beoordelen": "twijfelgeval: privacy officer beoordeelt of melden aan de AP nodig is",
                "wel_melden": "melden aan de AP aanbevolen (binnen 72 uur na constatering)"}
HIGH_RISK = {"NL_BSN", "CREDIT_CARD"}
MEDIUM_RISK = {"IBAN_CODE", "DATE_OF_BIRTH"}


def assess(counts: dict, cfg: dict | None = None, eigen: bool = False, betrokkenen: int | None = None) -> dict:
    """Default assessment of the meldplicht (AVG art. 33/34). Advice only; BRIDGE keeps
    meldbeslissing 'nog_te_bepalen' until the privacy officer decides."""
    cfg = cfg or {}
    dpa = cfg.get("leak_check", {}).get("verwerkersovereenkomst_anthropic")
    n = betrokkenen if betrokkenen is not None else max([0, *counts.values()])
    types = set(counts)
    high, medium = types & HIGH_RISK, types & MEDIUM_RISK
    soort = ", ".join(LABELS.get(t, t) for t in sorted(types)) or "onbekend"
    ontvanger = ("Anthropic (Claude Code), verwerker onder de zakelijke voorwaarden"
                 + (" met verwerkersovereenkomst" if dpa else
                    " (verwerkersovereenkomst NIET vastgesteld)" if dpa is False else
                    "; controleer of de verwerkersovereenkomst (DPA) van kracht is"))
    redenen = [f"Ontvanger: {ontvanger}; geen aanwijzing voor verdere verspreiding of publicatie.",
               f"Soort gegevens: {soort}; geschat aantal betrokkenen: {n}."]
    if eigen:
        advies = "niet_melden"
        redenen.insert(0, "Het gaat om eigen gegevens van de melder, bewust ingebracht (test); er is geen "
                          "risico voor rechten en vrijheden van anderen.")
    elif high and n >= 10:
        advies = "wel_melden"
        redenen.append(f"{', '.join(LABELS[t] for t in sorted(high))} is een gevoelig identificerend gegeven "
                       "(risico op identiteitsfraude) en het gaat om 10 of meer betrokkenen.")
    elif high or (medium and n >= 10) or n >= 100:
        advies = "beoordelen"
        if high:
            redenen.append(f"{', '.join(LABELS[t] for t in sorted(high))} is een gevoelig identificerend gegeven; "
                           "ook bij weinig betrokkenen kan het risico niet op voorhand worden uitgesloten.")
        if medium and n >= 10:
            redenen.append("Financiële gegevens of geboortedata van 10 of meer betrokkenen.")
        if n >= 100:
            redenen.append("Groot aantal betrokkenen (100 of meer).")
    else:
        advies = "niet_melden"
        redenen.append("Beperkte (contact)gegevens van weinig betrokkenen bij een verwerker onder contract: "
                       "het datalek leidt waarschijnlijk niet tot een risico voor de betrokkenen.")
    if dpa is False and advies != "wel_melden" and not eigen:
        advies = "beoordelen" if advies == "niet_melden" else "wel_melden"
        redenen.append("Zonder verwerkersovereenkomst is Anthropic een derde: hoger risico.")
    informeren = advies == "wel_melden" and bool(high)
    return {"advies": advies, "label": ADVIES_LABEL[advies], "redenen": redenen,
            "betrokkenen_informeren": informeren,
            "tekst": (f"Inschatting meldplicht (advies PII-filter, geen besluit): {ADVIES_LABEL[advies]}. "
                      f"Motivering: {' '.join(redenen)} Betrokkenen informeren (art. 34): "
                      f"{'ja, aanbevolen' if informeren else 'nee, geen hoog risico'}. "
                      "Altijd registreren in het datalekkenregister (art. 33 lid 5). "
                      "De meldbeslissing neemt de privacy officer.")}


# --------------------------------------------------------------------------- credentials
def credentials() -> tuple[str | None, str]:
    pat = os.environ.get("PII_BRIDGE_PAT")
    api = os.environ.get("PII_BRIDGE_API_BASE")
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            v = v.strip().strip('"').strip("'")
            if k == "BRIDGE_PAT" and not pat:
                pat = v
            elif k == "BRIDGE_API_BASE" and not api:
                api = v
    return (pat or None), (api or DEFAULT_API).rstrip("/")


# --------------------------------------------------------------------------- report
def _no_long_digits(s: str) -> str:
    """BRIDGE rejects free text with 8-9 digit runs (possible BSN); break any long digit run."""
    return re.sub(r"\d(?:[ .\-]?\d){5,}",
                  lambda m: " / ".join(re.findall(r"\d{1,4}", re.sub(r"\D", "", m.group(0)))), s)


def safe_file_name(name: str, cfg: dict | None = None) -> str:
    """File name for the report, or a neutral placeholder if the name itself may hold personal data."""
    name = re.sub(r"\.pii-sanitized\.[0-9a-f]{10}", "", name or "")
    if not name:
        return ""
    if detect(name, cfg or {}) or re.search(r"@|\d{6,}", name):
        return "(bestandsnaam bevat mogelijk persoonsgegevens)"
    return name


MELDER_CACHE = LEAK_DIR / "melder.json"


def _bridge_name(timeout: float = 4.0) -> str:
    """First + last name of the owner of the BRIDGE token (GET /api/v1/auth/me), cached per token."""
    pat, api = credentials()
    if not pat:
        return ""
    key = hashlib.sha256(f"{api}|{pat}".encode()).hexdigest()[:16]
    try:
        cache = json.loads(MELDER_CACHE.read_text(encoding="utf-8"))
        if cache.get("key") == key and cache.get("name"):
            return cache["name"]
    except (OSError, ValueError):
        pass
    try:
        req = urllib.request.Request(f"{api}/api/v1/auth/me", headers={"Authorization": f"Bearer {pat}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return ""
    u = d.get("user", d) if isinstance(d, dict) else {}
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()
    if name:
        MELDER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        MELDER_CACHE.write_text(json.dumps({"key": key, "name": name}), encoding="utf-8")
    return name


def melder() -> str:
    """Who the leak happened to (the employee, not a data subject):
    MELDER in the env file / PII_FILTER_MELDER, else the owner of the BRIDGE token,
    else git user.name, else the OS user."""
    name = os.environ.get("PII_FILTER_MELDER")
    if not name and ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            if k == "MELDER":
                name = v.strip().strip('"').strip("'")
    if not name:
        name = _bridge_name()
    if not name:
        try:
            import subprocess
            r = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, timeout=3)
            name = r.stdout.decode("utf-8", "replace").strip()
        except (OSError, subprocess.SubprocessError):
            name = ""
    if not name:
        import getpass
        try:
            name = getpass.getuser()
        except Exception:  # noqa: BLE001
            name = "onbekend"
    return name[:80]


# Display order: who first, then the sensitive identifiers, then contact and location data.
ORDER = ["PERSON", "NL_BSN", "CREDIT_CARD", "IBAN_CODE", "DATE_OF_BIRTH", "EMAIL_ADDRESS", "PHONE_NUMBER",
         "NL_ADDRESS", "NL_POSTCODE", "LOCATION", "IP_ADDRESS", "OTHER"]


def _ordered(keys):
    return sorted(keys, key=lambda k: (ORDER.index(k) if k in ORDER else len(ORDER), k))


def what_short(found: dict) -> str:
    """'Naam, woonplaats, postcode' / 'E-mailadres (3), BSN' -- for the one-line summary."""
    parts = [LABELS.get(k, k) + (f" ({len(found[k])})" if len(found[k]) > 1 else "") for k in _ordered(found)]
    s = ", ".join(parts) or "Persoonsgegevens"
    return s[:1].upper() + s[1:]


def how_short(source: dict, fname: str) -> str:
    tool = source.get("tool", "?")
    f = f" {fname}" if fname else ""
    if not source.get("automatic", True):
        return (source.get("hoe_kort") or tool)[:60] + (f" ({fname})" if fname and fname not in tool else "")
    if tool == "Read" and source.get("filtered_copy"):
        return f"Read{f} (filter miste)"
    if tool == "Read":
        return f"Read{f} (niet gefilterd)"
    if tool == "Grep":
        return f"Grep-zoekresultaat{f}"
    cmd = source.get("command_name")
    return f"{cmd or tool}-uitvoer{f}"


def route_text(source: dict) -> str:
    tool = source.get("tool", "?")
    if not source.get("automatic", True):
        return f"handmatig gemeld; binnengekomen via: {tool}"
    if tool == "Read" and source.get("filtered_copy"):
        return ("Claude las een door het PII-filter gepseudonimiseerde kopie; het filter heeft deze gegevens "
                "niet herkend en dus niet vervangen")
    if tool == "Read":
        return ("Claude las het originele bestand; het PII-filter heeft het niet gepseudonimiseerd "
                "(niets herkend vooraf, of het bestand is uitgezonderd)")
    if tool == "Grep":
        return "zoekresultaten (Grep) met regels uit het bestand"
    cmd = source.get("command_name")
    return f"uitvoer van een shell-commando via {tool}" + (f" ('{cmd}')" if cmd else "")


def _where(found: dict, details: list | None) -> list[str]:
    lines = []
    for k in _ordered(found):
        bases = sorted({d["basis"] for d in (details or []) if d["type"] == k})
        label = LABELS.get(k, k)
        lines.append(f"- {label[:1].upper() + label[1:]}: {len(found[k])}" + (f" ({'; '.join(bases)})" if bases else ""))
    return lines


def _reference(now: dt.datetime) -> str:
    # letters only after the date, so BRIDGE never sees a BSN-like digit run
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(4))
    return f"DL-AI-{now:%Y-%m-%d}-{code}"


def build_report(found: dict, source: dict, note: str = "", details: list | None = None,
                 cfg: dict | None = None, assessment: dict | None = None) -> dict:
    """One clean line in the overview (WAT · HOE · BIJ WIE), details under fixed headings."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    ref = _reference(now)
    local_ref = ref.rsplit("-", 1)[-1].lower() + secrets.token_hex(2)
    counts = {k: len(v) for k, v in found.items()}
    ext = source.get("ext") or "onbekend"
    project = source.get("project") or "onbekend"
    fname = safe_file_name(source.get("file_name") or "", cfg)
    automatic = source.get("automatic", True)
    wie = source.get("melder") or melder()
    host = socket.gethostname()
    n = source.get("betrokkenen") or max([0, *counts.values()])
    a = assessment or assess(counts, cfg, eigen=source.get("eigen", False), betrokkenen=n)

    summary = f"{what_short(found)} · {how_short(source, fname)} · bij {wie}"
    toelichting = "\n".join([
        "WAT",
        *_where(found, details),
        "(waarden staan bewust niet in het register)",
        "",
        "HOE",
        f"- Route: {route_text(source)}",
        f"- Bestand: {fname or 'onbekend'} (type {ext}), project {project}",
        f"- Ontdekt: {'automatisch door de PII-filter-plugin' if automatic else 'handmatig gemeld via de PII-filter-plugin'}",
        "",
        "BIJ WIE",
        f"- Medewerker: {wie}",
        f"- Werkplek: {host}, sessie {str(source.get('session_id', ''))[:8] or 'onbekend'}",
        "- Ontvanger: Anthropic (Claude Code), verwerker",
        "",
        "INSCHATTING MELDPLICHT (advies, geen besluit)",
        f"- Advies: {a['label']}",
        *[f"- {r}" for r in a["redenen"] if not r.startswith(("Ontvanger:", "Soort gegevens:"))],
        *(["- Aanname: Anthropic verwerkt als verwerker onder de zakelijke voorwaarden; controleer of de "
           "verwerkersovereenkomst van kracht is (leak_check.verwerkersovereenkomst_anthropic)."]
          if (cfg or {}).get("leak_check", {}).get("verwerkersovereenkomst_anthropic") is None else []),
        f"- Betrokkenen informeren: {'ja, aanbevolen' if a['betrokkenen_informeren'] else 'nee'}",
        "",
        "OVERIG",
        f"- PII-filter {source.get('plugin_version', '?')}, lokale referentie {local_ref} "
        "(volledig pad staat alleen lokaal in de meldingenlog)",
        *([f"- Opmerking melder: {note}"] if note else []),
    ])
    body = {
        "referentie": ref,
        "samenvatting": _no_long_digits(summary),
        "geconstateerd_op": now.isoformat().replace("+00:00", "Z"),
        "aard": ["vertrouwelijkheid"],
        "rol": "nog_te_bepalen",
        "ontdekt_door": "PII-filter (automatisch)" if automatic else "Medewerker via PII-filter",
        "aantal_betrokkenen_schatting": n,
        "gevolgen": ("Eigen gegevens van de medewerker, bewust ingebracht als test." if source.get("eigen") else
                     "Persoonsgegevens verwerkt door Anthropic (verwerker) in één Claude Code-sessie; "
                     "geen aanwijzing voor verdere verspreiding."),
        "getroffen_maatregelen": "Geregistreerd; AI-sessie opgedragen de gegevens niet te herhalen of te gebruiken.",
        "toelichting": _no_long_digits(toelichting),
        "meldbeslissing": "nog_te_bepalen",
        "status": "open",
    }
    return {"local_ref": local_ref, "created": now.isoformat(), "source": {**source, "melder": wie},
            "body": body, "assessment": a}


# --------------------------------------------------------------------------- queue / send
def enqueue(report: dict) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    p = QUEUE_DIR / f"{report['created'][:19].replace(':', '')}-{report['local_ref']}.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _post(api: str, pat: str, body: dict, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{api}/api/v1/isms/datalekken", method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json",
                 "Idempotency-Key": str(uuid.uuid5(uuid.NAMESPACE_URL, body["referentie"]))})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            detail = {}
        return e.code, detail


def flush(timeout: float = 8.0) -> dict:
    """Send every queued report. Returns {'sent': [...], 'pending': n, 'error': str|None}."""
    out = {"sent": [], "pending": 0, "error": None}
    files = sorted(QUEUE_DIR.glob("*.json")) if QUEUE_DIR.exists() else []
    if not files:
        return out
    pat, api = credentials()
    if not pat:
        out["pending"] = len(files)
        out["error"] = f"geen BRIDGE-token ({ENV_FILE})"
        return out
    for f in files:
        rep = json.loads(f.read_text(encoding="utf-8"))
        try:
            code, resp = _post(api, pat, rep["body"], timeout)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            out["error"] = f"BRIDGE onbereikbaar ({type(e).__name__})"
            break
        if code in (200, 201) or (code == 409 and "referentie" in json.dumps(resp).lower()):
            rec = {"local_ref": rep["local_ref"], "referentie": rep["body"]["referentie"],
                   "bridge_id": resp.get("id"), "termijn_uiterlijk": resp.get("termijn_uiterlijk"),
                   "bridge_api": api, "advies": (rep.get("assessment") or {}).get("advies"),
                   "sent": dt.datetime.now(dt.timezone.utc).isoformat(), "source": rep["source"]}
            SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(SENT_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.unlink()
            out["sent"].append(rec)
        else:
            hint = {401: "token verlopen of ingetrokken", 403: "token mist scope isms.datalek.melden"}.get(code, "")
            out["error"] = f"BRIDGE HTTP {code} {hint} {json.dumps(resp)[:200]}".strip()
            if code in (401, 403):
                break  # same for every report; keep them queued
    out["pending"] = len(list(QUEUE_DIR.glob("*.json")))
    return out


# --------------------------------------------------------------------------- dedupe
def seen_before(key: str) -> bool:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if key in state:
        return True
    state[key] = dt.datetime.now(dt.timezone.utc).isoformat()
    if len(state) > 2000:  # keep it small
        state = dict(sorted(state.items(), key=lambda kv: kv[1])[-1000:])
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    return False


def quick_scan(text: str, cfg: dict) -> bool:
    """Fast pre-check for files outside the data extensions (code, docs, unknown text):
    True when hard identifiers or a personal-data table are present."""
    return bool(detect(text, cfg))
