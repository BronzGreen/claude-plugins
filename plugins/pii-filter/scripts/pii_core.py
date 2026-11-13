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
def _nl_recognizers(lang: str):
    from presidio_analyzer import Pattern, PatternRecognizer

    CASE_SENSITIVE = re.DOTALL | re.MULTILINE  # Presidio defaults to IGNORECASE

    class BsnRecognizer(PatternRecognizer):
        def validate_result(self, pattern_text):
            digits = re.sub(r"\D", "", pattern_text)
            if len(digits) != 9 or digits == "000000000":
                return False
            total = sum(int(d) * w for d, w in zip(digits[:8], range(9, 1, -1)))
            total -= int(digits[8])
            # None = keep the pattern score (don't bump to 1.0), False = drop
            return None if total % 11 == 0 else False

    bsn = BsnRecognizer(
        supported_entity="NL_BSN",
        supported_language=lang,
        patterns=[
            Pattern("bsn_plain", r"\b\d{9}\b", 0.5),
            Pattern("bsn_dotted", r"\b\d{4}\.\d{2}\.\d{3}\b", 0.6),
        ],
        context=["bsn", "burgerservicenummer", "sofinummer", "sofi", "persoonsnummer"],
    )
    postcode = PatternRecognizer(
        supported_entity="NL_POSTCODE",
        supported_language=lang,
        global_regex_flags=CASE_SENSITIVE,
        patterns=[
            # postcode, optionally followed by the place name: "1071 AZ Amsterdam",
            # "2900 AB Capelle aan den IJssel", "2511 CV 's-Gravenhage"
            Pattern(
                "postcode",
                r"\b[1-9]\d{3}\s?(?!SA|SD|SS)[A-Z]{2}\b"
                r"(?:\s{1,2}(?:'s-)?[A-Z][\w'-]+(?:\s(?:aan\s(?:de|den)\s)?[A-Z][\w'-]+)?)?",
                0.6,
            )
        ],
        context=["postcode", "adres", "woonplaats"],
    )
    street_suffix = (
        r"(?:straat|laan|weg|plein|gracht|kade|singel|dijk|steeg|hof|park|dreef|pad|"
        r"markt|ring|baan|haven|veld|wal|erf|akker|hoeve|lei|dam|burg|berg|bos|tuin)"
    )
    # huisnummer + toevoeging: 12, 12a, 12 A, 12-3, 12-II, 12 bis
    huisnr = r"\s+\d{1,5}(?:[a-zA-Z]{1,2}\b|-\d{1,3}\b|-[a-zA-Z]{1,4}\b|\s[A-Z]\b|\sbis\b)?"
    address = PatternRecognizer(
        supported_entity="NL_ADDRESS",
        supported_language=lang,
        global_regex_flags=CASE_SENSITIVE,
        patterns=[
            Pattern("straat_huisnummer", r"\b[A-Z][\w'-]*" + street_suffix + huisnr, 0.65),
            # "Van Baerlestraat 12", "Jan van Galenstraat 4", "Burgemeester de Withstraat 9"
            Pattern(
                "lange_straatnaam_huisnummer",
                r"\b[A-Z][a-z'-]+\s(?:(?:[A-Z][a-z'-]+|van|de|der|den|het|ter|ten|te)\s){0,3}[A-Z]?[\w'-]*"
                + street_suffix + huisnr,
                0.6,
            ),
        ],
        context=["adres", "straat", "woont", "wonende"],
    )
    mobile = PatternRecognizer(
        supported_entity="PHONE_NUMBER",
        supported_language=lang,
        patterns=[Pattern("nl_mobiel", r"(?<![\d+])(?:\+31|0031|0)[\s-]?6(?:[\s-]?\d){8}(?!\d)", 0.6)],
        context=["telefoon", "tel", "mobiel", "bel", "bereikbaar"],
    )
    return [bsn, postcode, address, mobile]


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
        self.entities = self.cfg["entities"]
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
                if not cell or not str(cell).strip() or TOKEN_RE.fullmatch(str(cell)):
                    continue
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


def filter_file(flt: Filter, src: Path, dst: Path, vault: Vault, max_lines: int | None = None) -> dict:
    """Write a pseudonymised copy of src to dst. Returns stats."""
    ext = src.suffix.lower()
    truncated = False
    if ext in (".xlsx", ".xlsm"):
        flt.filter_xlsx(src, dst, vault, max_rows=max_lines)
    else:
        text = read_text(src)
        if max_lines is not None:
            lines = text.splitlines(keepends=True)
            if len(lines) > max_lines:
                text, truncated = "".join(lines[:max_lines]), True
        if ext in TABULAR:
            out = flt.filter_csv_text(text, vault, delimiter="\t" if ext == ".tsv" else None)
        else:
            out = flt.filter_text(text, vault)
        if truncated:
            out += f"\n[pii-filter: bestand afgekapt na {max_lines} regels]\n"
        dst.write_text(out, encoding="utf-8")
    return {"replacements": sum(flt.counts.values()), "by_entity": dict(flt.counts),
            "truncated": truncated}
