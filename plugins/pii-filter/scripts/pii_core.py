"""Core PII-filtering on top of Microsoft Presidio.

- Presidio AnalyzerEngine with spaCy NL (and optionally EN) models
- Extra Dutch recognizers: BSN (11-proef), postcode, street+huisnummer, NL phone
- Reversible pseudonymisation via a local vault: "Jan de Vries" -> <PERSON_1>,
  same value always gets the same token, so joins/relations stay intact.

Nothing in here sends data anywhere; everything runs locally.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from pathlib import Path

from pii_config import CACHE_DIR, VAULT_DIR, VAULT_PATH, load_config  # noqa: F401

TOKEN_RE = re.compile(r"<([A-Z][A-Z0-9_]*?)_(\d+)>")

SPACY_MODELS = {"nl": "nl_core_news_md", "en": "en_core_web_md"}


# --------------------------------------------------------------------------- vault
class Vault:
    """value <-> token mapping, persisted as JSON with a simple lock file."""

    def __init__(self, path: Path = VAULT_PATH):
        self.path = path
        self.lock_path = path.with_suffix(".lock")
        self.data = {"forward": {}, "reverse": {}, "counters": {}}
        self.dirty = False

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(value.split()).casefold()

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + 30
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                # stale lock (crashed process) -> break it after 60s
                try:
                    if time.time() - self.lock_path.stat().st_mtime > 60:
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() > deadline:
                    raise TimeoutError(f"vault lock busy: {self.lock_path}")
                time.sleep(0.1)
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        return self

    def __exit__(self, *exc):
        try:
            if self.dirty:
                tmp = self.path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
        finally:
            self.lock_path.unlink(missing_ok=True)

    def token_for(self, entity: str, value: str) -> str:
        key = f"{entity}|{self._norm(value)}"
        tok = self.data["forward"].get(key)
        if tok:
            return tok
        n = self.data["counters"].get(entity, 0) + 1
        self.data["counters"][entity] = n
        tok = f"<{entity}_{n}>"
        self.data["forward"][key] = tok
        self.data["reverse"][tok] = value
        self.dirty = True
        return tok

    def reveal(self, text: str) -> tuple[str, int]:
        count = 0

        def sub(m):
            nonlocal count
            orig = self.data["reverse"].get(m.group(0))
            if orig is None:
                return m.group(0)
            count += 1
            return orig

        return TOKEN_RE.sub(sub, text), count

    def stats(self) -> dict:
        return dict(sorted(self.data["counters"].items()))


# --------------------------------------------------------------------------- engine
DATA_DIR_PLUGIN = Path(__file__).resolve().parent.parent / "data"

# Woonplaatsen that are also ordinary words or common name parts: only recognised with context
# ("woont in Best"). Names of 4 letters or fewer are treated the same way.
AMBIGUOUS_PLACES = {
    "Best", "Born", "Hoek", "Lent", "Well", "Loon", "Ens", "Son", "Putten", "Haren", "Lith", "Wouw",
    "Echt", "Ee", "Mill", "Elst", "Wijk", "Gemert", "Rijs", "Nes", "Sluis", "Beek", "Bergen", "Laren",
    "Halle", "Doorn", "Linde", "Huis", "Berg", "Holten", "Dijk", "Vaart", "Hall", "Stad", "Dorst",
    "Eden", "Nieuwland", "Oosterend", "Westerland", "Kamp", "Boer", "Dam", "Gaast", "Lage", "Hoge",
    "Midden", "Noord", "Oost", "Zuid", "West", "Eck", "Esch", "Nij", "Ter", "Venhuizen", "Kolham",
    "Raard", "Molenend", "Vlijmen", "Steenbergen", "Weert", "Hengelo",
}


def _place_names() -> list[str]:
    f = DATA_DIR_PLUGIN / "woonplaatsen-nl.txt"
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def _nl_phone_digits(raw: str) -> str | None:
    """Normalise a Dutch phone number to 10 digits starting with 0, or None."""
    d = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+") or d.startswith("0031"):
        d = d[4:] if d.startswith("0031") else d[2:]  # drop (00)31
        if d.startswith("0"):  # +31 (0)6 ...
            d = d[1:]
        d = "0" + d
    return d if len(d) == 10 and d[0] == "0" and d[1] != "0" else None


def _nl_recognizers(lang: str):
    from presidio_analyzer import Pattern, PatternRecognizer

    CASE_SENSITIVE = re.DOTALL | re.MULTILINE  # Presidio defaults to IGNORECASE
    IGNORE_CASE = re.DOTALL | re.MULTILINE | re.IGNORECASE

    class BsnRecognizer(PatternRecognizer):
        def validate_result(self, pattern_text):
            digits = re.sub(r"\D", "", pattern_text)
            if len(digits) == 8:
                digits = "0" + digits  # leading zero lost (Excel)
            if len(digits) != 9 or digits == "000000000":
                return False
            total = sum(int(d) * w for d, w in zip(digits[:8], range(9, 1, -1)))
            total -= int(digits[8])
            # None = keep the pattern score (don't bump to 1.0), False = drop
            return None if total % 11 == 0 else False

    sep = r"[ .\-]"
    bsn = BsnRecognizer(
        supported_entity="NL_BSN",
        supported_language=lang,
        patterns=[
            Pattern("bsn_plain", r"(?<![\d.,\-])\d{9}(?!\d|[.,\-]\d)", 0.5),
            # 1234.56.789, 123-45-678, 123 456 789, 1234 56 789, 12.34.56.789 ...
            Pattern("bsn_separated",
                    rf"(?<![\d.,\-])(?<!\d )\d{{2,4}}(?:{sep}\d{{2,4}}){{1,3}}(?!\d|{sep}\d)", 0.5),
            # 8 digits (leading zero lost): only with context
            Pattern("bsn_8", r"(?<![\d.,\-])\d{8}(?!\d|[.,\-]\d)", 0.2),
        ],
        context=["bsn", "burgerservicenummer", "sofinummer", "sofi", "persoonsnummer"],
    )

    # Postcodes. Upper case is common and safe; lower case / glued needs care (units, hex colours).
    units = (r"(?!(?:px|pt|em|ms|mg|kg|km|cm|mm|ml|cl|dl|gb|mb|kb|tb|hz|kw|mw|gw|wh|ah|ma|mv|kv|nm|um|ns|"
             r"us|ps|st|nd|rd|th|am|pm|sa|sd|ss|de|en|in|op|is|te|om|al|nu|er|ik|je|we|ze|na|of|"
             r"ga|ja|zo|af|uur|jr)\b)")
    place = r"(?:\s{1,2}(?:'s-)?[A-Z][\w'-]+(?:\s(?:aan\s(?:de|den)\s)?[A-Z][\w'-]+)?)?"
    postcode = PatternRecognizer(
        supported_entity="NL_POSTCODE",
        supported_language=lang,
        global_regex_flags=CASE_SENSITIVE,
        patterns=[
            # "1071 AZ Amsterdam", "2900 AB Capelle aan den IJssel", "2511 CV 's-Gravenhage", "1071-AZ"
            Pattern("postcode", r"\b[1-9]\d{3}[\s\-]?(?!SA|SD|SS)[A-Z]{2}\b" + place, 0.6),
        ],
        context=["postcode", "adres", "woonplaats", "wonend", "woont"],
    )
    postcode_lc = PatternRecognizer(
        supported_entity="NL_POSTCODE",
        supported_language=lang,
        global_regex_flags=IGNORE_CASE,
        patterns=[
            # "6060cp", "6060Cp": glued, not a unit, not a hex colour / 0x value
            Pattern("postcode_vast", r"(?<![#\w])[1-9]\d{3}" + units + r"[a-z]{2}\b", 0.5),
            # "6060 cp": too much like normal text ("2026 is"), only with context
            Pattern("postcode_spatie", r"(?<![#\w])[1-9]\d{3}\s" + units + r"[a-z]{2}\b", 0.2),
        ],
        context=["postcode", "adres", "woonplaats", "wonend", "woont", "pc"],
    )

    street_suffix = (
        r"(?:straat|laan|weg|plein|gracht|kade|singel|dijk|steeg|hof|park|dreef|pad|"
        r"markt|ring|baan|haven|veld|wal|erf|akker|hoeve|lei|dam|burg|berg|bos|tuin|"
        r"str\.|ln\.|pln?\.|wg\.|sngl\.|gr\.)"
    )
    # huisnummer + toevoeging: 12, 12a, 12 A, 12-3, 12/3, 12-II, 12 bis, 12 hs, 12 bus 3, nr. 12, 12-14
    huisnr = (r"\s*,?\s*(?:nr\.?\s*|no\.?\s*)?\d{1,5}"
              r"(?:\s?[a-zA-Z]{1,2}\b|[-/]\d{1,4}\b|-[a-zA-Z]{1,4}\b|"
              r"\s(?:hs|bis|huis|boven|beneden|bg|I{1,3}|IV|bus\s?\d{1,4})\b|\s[A-Z]\b)?")
    address = PatternRecognizer(
        supported_entity="NL_ADDRESS",
        supported_language=lang,
        global_regex_flags=CASE_SENSITIVE,
        patterns=[
            Pattern("straat_huisnummer", r"\b[A-Z][\w'-]*" + street_suffix + huisnr + r"(?!\d)", 0.65),
            # "Van Baerlestraat 12", "Jan van Galenstraat 4", "Burgemeester de Withstraat 9"
            Pattern(
                "lange_straatnaam_huisnummer",
                r"\b[A-Z][a-z'-]+\s(?:(?:[A-Z][a-z'-]+|van|de|der|den|het|ter|ten|te)\s){0,3}[A-Z]?[\w'-]*"
                + street_suffix + huisnr + r"(?!\d)",
                0.6,
            ),
            # "Laan van Meerdervoort 12", "Kade Oost 4"
            Pattern(
                "straat_vooraan",
                r"\b(?:Laan|Plein|Kade|Dijk|Singel|Weg|Straat|Markt|Burgwal|Gracht|Dreef|Hof)"
                r"(?:\s(?:van|de|der|den|het|op|ter|ten|naar|[A-Z][\w'-]+)){1,4}" + huisnr + r"(?!\d)",
                0.55,
            ),
        ],
        context=["adres", "straat", "woont", "wonende", "woonadres", "postadres"],
    )
    address_lc = PatternRecognizer(
        supported_entity="NL_ADDRESS",
        supported_language=lang,
        global_regex_flags=IGNORE_CASE,
        patterns=[
            # "hoofdstraat 12", "KERKSTRAAT 4A"
            Pattern("straat_klein", r"(?<![\w'-])[a-z][\w'-]*" + street_suffix + huisnr + r"(?!\d)", 0.55),
        ],
        context=["adres", "straat", "woont", "wonende"],
    )

    class NlPhoneRecognizer(PatternRecognizer):
        def validate_result(self, pattern_text):
            return None if _nl_phone_digits(pattern_text) else False

    psep = r"[\s.\-/)]{0,2}"
    phone = NlPhoneRecognizer(
        supported_entity="PHONE_NUMBER",
        supported_language=lang,
        patterns=[
            # +31 6 12345678, +31 (0)45 123 45 67, 0031-6-1234 5678, +316-12345678
            Pattern("nl_internationaal",
                    r"(?<![\w+])(?:\+|00)\s?31[\s.\-]?(?:\(0\)[\s.\-]?)?[1-9](?:" + psep + r"\d){8}(?!\d)", 0.65),
            # 06-12345678, 06 12 34 56 78, (06) 1234 5678, 0612345678, 06.12.34.56.78
            Pattern("nl_mobiel", r"(?<![\w+(])\(?06\)?(?:" + psep + r"\d){8}(?!\d)", 0.6),
            # 045-1234567, (045) 123 45 67, 020 - 555 1234, 010/1234567
            Pattern("nl_vast_opgemaakt",
                    r"(?<![\w+(])\(?0[1-57-9]\d{1,2}\)?\s?[\s.\-/]\s?\d(?:[\s.\-]?\d){5,6}(?!\d)", 0.5),
            # 0451234567 (no formatting): could be any number, only with context
            Pattern("nl_vast_kaal", r"(?<![\w+])0[1-57-9]\d{8}(?!\d)", 0.2),
        ],
        context=["telefoon", "tel", "mobiel", "gsm", "bel", "bereikbaar", "phone", "telnr", "fax"],
    )

    class IbanRecognizer(PatternRecognizer):
        def validate_result(self, pattern_text):
            s = re.sub(r"[\s.\-]", "", pattern_text).upper()
            if not 15 <= len(s) <= 34:
                return False
            num = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
            return True if int(num) % 97 == 1 else False

    iban = IbanRecognizer(
        supported_entity="IBAN_CODE",
        supported_language=lang,
        global_regex_flags=IGNORE_CASE,
        patterns=[
            # nl91abna0417164300, NL91 ABNA 0417 1643 00, NL91-ABNA-0417-1643-00, NL91.ABNA.0417.1643.00
            Pattern("iban_nl", r"\bNL\d{2}[\s.\-]?[A-Z]{4}(?:[\s.\-]?\d){10}\b", 0.8),
            Pattern("iban_be", r"\bBE\d{2}(?:[\s.\-]?\d){12}\b", 0.8),
            Pattern("iban_de", r"\bDE\d{2}(?:[\s.\-]?\d){18}\b", 0.8),
        ],
    )

    email_obf = PatternRecognizer(
        supported_entity="EMAIL_ADDRESS",
        supported_language=lang,
        global_regex_flags=IGNORE_CASE,
        patterns=[
            # jan [at] bedrijf [dot] nl, jan(at)bedrijf.nl, jan @ bedrijf . nl
            Pattern("email_verhuld",
                    r"\b[\w.+-]+\s?(?:\[at\]|\(at\)|\{at\}|\s@\s)\s?[\w-]+"
                    r"(?:\s?(?:\[dot\]|\(dot\)|\{dot\}|\.|\spunt\s)\s?[\w-]+)+\b", 0.6),
        ],
    )

    months = (r"(?:jan(?:uari)?|feb(?:ruari)?|maart|mrt|apr(?:il)?|mei|jun(?:i)?|jul(?:i)?|aug(?:ustus)?|"
              r"sep(?:t(?:ember)?)?|okt(?:ober)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
              r"january|february|march|may|june|july|august|october|december)")
    dob = PatternRecognizer(
        supported_entity="DATE_OF_BIRTH",
        supported_language=lang,
        global_regex_flags=IGNORE_CASE,
        patterns=[
            Pattern("datum_dmj", r"\b\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d{2}\b", 0.15),
            Pattern("datum_jmd", r"\b(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b", 0.15),
            Pattern("datum_tekst", r"\b\d{1,2}\s" + months + r"\.?\s(?:19|20)\d{2}\b", 0.15),
        ],
        context=["geboren", "geb", "geboortedatum", "gebdatum", "geboorte", "verjaardag", "jarig",
                 "dob", "birth", "born", "birthday", "leeftijd"],
    )

    recognizers = [bsn, postcode, postcode_lc, address, address_lc, phone, iban, email_obf, dob]

    places = _place_names()
    clear = [n for n in places if n not in AMBIGUOUS_PLACES and len(n) > 4]
    ambiguous = [n for n in places if n in AMBIGUOUS_PLACES or len(n) <= 4]

    def gazetteer(items, score, name):
        alt = "|".join(re.escape(n) for n in sorted(items, key=len, reverse=True))
        return Pattern(name, rf"(?<![\w'-])(?:{alt})(?![\w'-])", score)

    if places:
        recognizers.append(PatternRecognizer(
            supported_entity="LOCATION",
            supported_language=lang,
            global_regex_flags=CASE_SENSITIVE,
            patterns=[gazetteer(clear, 0.55, "woonplaats"), gazetteer(ambiguous, 0.2, "woonplaats_dubbelzinnig")],
            context=["woonplaats", "woont", "wonend", "wonende", "plaats", "verhuisd", "geboorteplaats",
                     "adres"],
        ))
    return recognizers


def build_analyzer(languages: list[str]):
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import (
        CreditCardRecognizer,
        EmailRecognizer,
        IbanRecognizer,
        IpRecognizer,
        PhoneRecognizer,
        SpacyRecognizer,
    )

    nlp_conf = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": l, "model_name": SPACY_MODELS[l]} for l in languages],
        "ner_model_configuration": {
            "model_to_presidio_entity_mapping": {
                "PERSON": "PERSON", "PER": "PERSON",
                "GPE": "LOCATION", "LOC": "LOCATION", "FAC": "LOCATION",
                "ORG": "ORGANIZATION", "NORP": "NRP",
                "DATE": "DATE_TIME", "TIME": "DATE_TIME",
            },
            "low_confidence_score_multiplier": 0.4,
            "low_score_entity_names": ["ORGANIZATION"],
            "labels_to_ignore": ["CARDINAL", "ORDINAL", "QUANTITY", "MONEY", "PERCENT",
                                 "PRODUCT", "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE", "MISC"],
        },
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=nlp_conf).create_engine()

    registry = RecognizerRegistry(supported_languages=languages)
    for lang in languages:
        registry.add_recognizer(SpacyRecognizer(supported_language=lang))
        registry.add_recognizer(EmailRecognizer(supported_language=lang))
        registry.add_recognizer(IbanRecognizer(supported_language=lang))
        registry.add_recognizer(CreditCardRecognizer(supported_language=lang))
        registry.add_recognizer(IpRecognizer(supported_language=lang))
        registry.add_recognizer(
            PhoneRecognizer(supported_language=lang,
                            supported_regions=("NL", "BE", "DE", "GB", "FR", "US"),
                            context=["telefoon", "tel", "mobiel", "gsm", "phone", "bel"])
        )
        for r in _nl_recognizers(lang):
            registry.add_recognizer(r)

    return AnalyzerEngine(registry=registry, nlp_engine=nlp_engine,
                          supported_languages=languages)


# --------------------------------------------------------------------------- filtering
def _resolve_overlaps(results):
    """Where spans overlap keep the longest (e.g. street+number over street), then strongest."""
    ordered = sorted(results, key=lambda r: (-(r.end - r.start), -r.score))
    kept = []
    for r in ordered:
        if all(r.end <= k.start or r.start >= k.end for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: r.start)


class Filter:
    def __init__(self, config: dict | None = None, language: str | None = None):
        self.cfg = config or load_config()
        self.language = language or self.cfg.get("default_language", "nl")
        self.analyzer = build_analyzer([self.language])
        self.entities = list(self.cfg["entities"])
        if "DATE_OF_BIRTH" not in self.entities and self.cfg.get("detect_birthdates", True):
            self.entities.append("DATE_OF_BIRTH")
        self.threshold = float(self.cfg.get("score_threshold", 0.5))
        self.allow_list = self.cfg.get("allow_list", [])
        self.column_hints = [(re.compile(p, re.I), ent)
                             for p, ent in self.cfg.get("column_hints", {}).items()]
        self.counts: dict[str, int] = {}

    def _count(self, entity: str):
        self.counts[entity] = self.counts.get(entity, 0) + 1

    def _apply(self, text: str, results, vault: Vault) -> str:
        for r in reversed(_resolve_overlaps(results)):
            value = text[r.start:r.end]
            if TOKEN_RE.fullmatch(value):
                continue
            text = text[:r.start] + vault.token_for(r.entity_type, value) + text[r.end:]
            self._count(r.entity_type)
        return text

    def analyze_many(self, texts: list[str]):
        from presidio_analyzer import BatchAnalyzerEngine

        batch = BatchAnalyzerEngine(analyzer_engine=self.analyzer)
        return batch.analyze_iterator(
            texts, language=self.language, entities=self.entities,
            score_threshold=self.threshold, allow_list=self.allow_list,
        )

    def scan_text(self, text: str):
        res = self.analyzer.analyze(text=text, language=self.language, entities=self.entities,
                                    score_threshold=self.threshold, allow_list=self.allow_list)
        return _resolve_overlaps(res)

    # -- plain text, line by line (keeps line numbers identical)
    def filter_lines(self, lines: list[str], vault: Vault) -> list[str]:
        bodies = [l.rstrip("\r\n") for l in lines]
        endings = [l[len(b):] for l, b in zip(lines, bodies)]
        idx = [i for i, b in enumerate(bodies) if b.strip()]
        out = list(bodies)
        for i, res in zip(idx, self.analyze_many([bodies[i] for i in idx])):
            if res:
                out[i] = self._apply(bodies[i], res, vault)
        return [o + e for o, e in zip(out, endings)]

    def filter_text(self, text: str, vault: Vault) -> str:
        return "".join(self.filter_lines(text.splitlines(keepends=True), vault))

    # -- tabular: column-name hints first, Presidio for the rest
    def _hint_for(self, header: str):
        h = re.sub(r"[^a-z0-9]", "", header.lower())
        for rx, ent in self.column_hints:
            if rx.fullmatch(h):
                return ent
        return None

    def filter_rows(self, rows: list[list[str]], vault: Vault, has_header: bool = True):
        if not rows:
            return rows
        header = rows[0] if has_header else []
        hints = [self._hint_for(h) for h in header]
        body = rows[1:] if has_header else rows
        cells, pos = [], []
        out = [list(r) for r in body]
        for ri, row in enumerate(body):
            for ci, cell in enumerate(row):
                if not cell or not str(cell).strip() or TOKEN_RE.fullmatch(str(cell).strip()):
                    continue
                if re.fullmatch(r"[\s\-:=_.|]+|n/?a|null|none|onbekend|-", str(cell).strip(), re.I):
                    continue  # markdown separator rows, empty markers
                ent = hints[ci] if ci < len(hints) else None
                if ent:
                    out[ri][ci] = vault.token_for(ent, str(cell))
                    self._count(ent)
                else:
                    cells.append(str(cell))
                    pos.append((ri, ci))
        for (ri, ci), text, res in zip(pos, cells, self.analyze_many(cells)):
            if res:
                out[ri][ci] = self._apply(text, res, vault)
        return ([list(header)] if has_header else []) + out

    def filter_csv_text(self, text: str, vault: Vault, delimiter: str | None = None) -> str:
        sample = text[:20000]
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        try:
            has_header = csv.Sniffer().has_header(sample)
        except csv.Error:
            has_header = True
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if rows and not has_header and any(self._hint_for(c) for c in rows[0]):
            has_header = True  # sniffer misses all-text tables; known column names win
        # header row is kept as-is and drives column hints; without header all rows are scanned
        rows = self.filter_rows(rows, vault, has_header=has_header)
        buf = io.StringIO()
        csv.writer(buf, delimiter=delimiter, lineterminator="\n").writerows(rows)
        return buf.getvalue()

    def filter_xlsx(self, src: Path, dst: Path, vault: Vault, max_rows: int | None = None):
        import openpyxl

        wb = openpyxl.load_workbook(src, data_only=True)
        for ws in wb.worksheets:
            rows = [["" if v is None else str(v) for v in r]
                    for r in ws.iter_rows(values_only=True, max_row=max_rows)]
            new = self.filter_rows(rows, vault, has_header=True)
            for r_i, (old_r, new_r) in enumerate(zip(rows, new), start=1):
                for c_i, (o, n) in enumerate(zip(old_r, new_r), start=1):
                    if o != n:
                        ws.cell(row=r_i, column=c_i, value=n)
        wb.save(dst)


# --------------------------------------------------------------------------- file helpers
TABULAR = {".csv", ".tsv"}


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def looks_tabular(text: str, flt: Filter | None = None) -> str | None:
    """Delimiter if a non-.csv text is really a table (header + rows), else None.

    ';', tab and '|' are rare in prose: 2 lines with the same count suffice.
    ',' is common in prose: needs 3+ consistent lines and a header that matches a column hint.
    """
    lines = [l for l in text.splitlines()[:30] if l.strip()]
    if len(lines) < 2:
        return None
    for d in (";", "\t", "|", ","):
        n = lines[0].strip().strip("|").count(d)
        if n < 1:
            continue
        same = sum(1 for l in lines[1:] if l.strip().strip("|").count(d) == n)
        if same < max(1, int(0.8 * (len(lines) - 1))):
            continue
        header = [c.strip() for c in lines[0].strip().strip("|").split(d)]
        hinted = flt is not None and any(flt._hint_for(h) for h in header)
        if d == ",":
            if len(lines) >= 3 and hinted:
                return d
            continue
        if hinted or all(h and not re.search(r"\d", h) for h in header):
            return d
    return None


def _render_table(rows: list[list[str]]) -> str:
    return "".join("\t".join(c.replace("\t", " ") for c in r) + "\n" for r in rows)


def filter_document(flt: Filter, src: Path, dst: Path, vault: Vault, max_lines: int | None = None) -> dict:
    """pdf/docx/pptx/xlsx/odf -> extracted, pseudonymised plain text in dst."""
    import pii_extract

    ex = pii_extract.extract(src, max_lines=max_lines)
    parts = [f"[pii-filter: tekst uit {src.name}, gepseudonimiseerd; opmaak en afbeeldingen zijn weggelaten]\n"]
    for kind, content in ex.blocks:
        if kind == "table":
            parts.append(_render_table(flt.filter_rows(content, vault, has_header=True)))
        else:
            parts.append(flt.filter_text(content, vault))
    for n in ex.notes:
        parts.append(f"\n[pii-filter: {n}]\n")
    dst.write_text("".join(parts), encoding="utf-8")
    return {"replacements": sum(flt.counts.values()), "by_entity": dict(flt.counts),
            "truncated": any("afgekapt" in n for n in ex.notes), "document": True,
            "pages": ex.pages, "unreadable_pages": ex.unreadable_pages}


def filter_file(flt: Filter, src: Path, dst: Path, vault: Vault, max_lines: int | None = None) -> dict:
    """Write a pseudonymised copy of src to dst. Returns stats."""
    import pii_extract

    ext = src.suffix.lower()
    truncated = False
    if ext in pii_extract.DOC_EXTENSIONS and not (ext in (".xlsx", ".xlsm") and dst.suffix.lower() == ext):
        return filter_document(flt, src, dst, vault, max_lines=max_lines)
    if ext in (".xlsx", ".xlsm"):  # CLI: anonymize x.xlsx -o y.xlsx keeps the workbook
        flt.filter_xlsx(src, dst, vault, max_rows=max_lines)
    else:
        text = read_text(src)
        if max_lines is not None:
            lines = text.splitlines(keepends=True)
            if len(lines) > max_lines:
                text, truncated = "".join(lines[:max_lines]), True
        delim = ("\t" if ext == ".tsv" else None) if ext in TABULAR else looks_tabular(text, flt)
        if ext in TABULAR or delim:
            out = flt.filter_csv_text(text, vault, delimiter=delim)
        else:
            out = flt.filter_text(text, vault)
        if truncated:
            out += f"\n[pii-filter: bestand afgekapt na {max_lines} regels]\n"
        dst.write_text(out, encoding="utf-8")
    return {"replacements": sum(flt.counts.values()), "by_entity": dict(flt.counts),
            "truncated": truncated}
