"""Recognizer coverage: many ways of writing Dutch personal data (all values fictional).

Run with the plugin venv python:  <venv>/python tests/test_formats.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("CLAUDE_PLUGIN_ROOT", str(ROOT))
os.environ["PII_VAULT_DIR"] = tempfile.mkdtemp()

import pii_config as pc  # noqa: E402
import pii_core as core  # noqa: E402

# (text, value that must disappear)
MUST = [
    # BSN (111222333 and 123456782 pass the 11-proef)
    ("BSN: 123456782", "123456782"),
    ("bsn 1234.56.782", "1234.56.782"),
    ("bsn 123-45-6782", "123-45-6782"),
    ("bsn 123 456 782", "123 456 782"),
    ("burgerservicenummer 1234 56 782", "1234 56 782"),
    ("BSN 12345672", "12345672"),  # 8 digits, leading 0 lost: 012345672 passes
    # postcode
    ("postcode 6461 AB", "6461 AB"),
    ("6461AB", "6461AB"),
    ("6461ab", "6461ab"),
    ("6461-AB", "6461-AB"),
    ("postcode: 6461 ab", "6461 ab"),
    # phone
    ("bel 06-12345678", "12345678"),
    ("06 12 34 56 78", "34 56 78"),
    ("0612345678", "0612345678"),
    ("(06) 1234 5678", "1234 5678"),
    ("+31 6 12345678", "12345678"),
    ("+31612345678", "+31612345678"),
    ("+31 (0)6 1234 5678", "1234 5678"),
    ("0031 6 1234 5678", "1234 5678"),
    ("045-5671234", "5671234"),
    ("(045) 567 12 34", "567 12 34"),
    ("+31 45 567 1234", "567 1234"),
    ("tel. 0455671234", "0455671234"),
    ("06.12.34.56.78", "06.12.34.56.78"),
    # IBAN
    ("NL91ABNA0417164300", "NL91ABNA0417164300"),
    ("NL91 ABNA 0417 1643 00", "0417 1643"),
    ("nl91abna0417164300", "nl91abna0417164300"),
    ("NL91-ABNA-0417-1643-00", "0417-1643"),
    # e-mail
    ("mail jan.devries@bedrijf-x.nl", "jan.devries@bedrijf-x.nl"),
    ("jan [at] bedrijf-x [dot] nl", "bedrijf-x"),
    ("jan(at)bedrijf-x.nl", "bedrijf-x"),
    # address
    ("Hoofdstraat 12", "Hoofdstraat 12"),
    ("hoofdstraat 12a", "hoofdstraat 12a"),
    ("Hoofdstr. 12", "Hoofdstr. 12"),
    ("Kerkplein 4-II", "Kerkplein 4"),
    ("Molenweg 8 bus 3", "Molenweg 8"),
    ("Laan van Meerdervoort 120", "Meerdervoort 120"),
    ("Jan van Galenstraat 4 hs", "Galenstraat 4"),
    ("Dorpsstraat nr. 7", "Dorpsstraat nr. 7"),
    # places
    ("Hij woont in Eygelshoven.", "Eygelshoven"),
    ("Kerkrade", "Kerkrade"),
    ("woonplaats: Best", "Best"),
    # date of birth
    ("geboren op 12-03-1985", "12-03-1985"),
    ("geboortedatum 1985-03-12", "1985-03-12"),
    ("geb. 12 maart 1985", "12 maart 1985"),
    # names (spaCy)
    ("Jan de Vries belt morgen terug.", "de Vries"),
]

# Must stay untouched (no false positives that break normal text/code)
KEEP = [
    "Het duurde 1500ms en 1024px breed.",
    "kleur #1234ab en 0x1234ab",
    "In 2026 is alles anders.",
    "versie 3.12.10 op poort 8080",
    "ordernummer 987654321",
    "Best practice: test eerst.",
    "Het is 12:30 uur.",
]


def main():
    flt = core.Filter(config=pc.load_config(None))
    fails = 0
    with core.Vault() as v:
        for text, secret in MUST:
            out = flt.filter_text(text, v)
            ok = secret not in out
            fails += not ok
            print(("ok   " if ok else "FOUT ") + f"{text!r:45} -> {out!r}")
        for text in KEEP:
            out = flt.filter_text(text, v)
            ok = out == text
            fails += not ok
            print(("ok   " if ok else "FOUT ") + f"blijft: {text!r:40} -> {out!r}")

        # tabular .txt (the case that slipped through: header on line 1, ';' separated)
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "testdata.txt"
        src.write_text("Naam;adres;postcode\nPietje;Kerkstraat 5 Eygelshoven;6461ab\n", encoding="utf-8")
        flt.counts.clear()
        core.filter_file(flt, src, tmp / "uit.txt", v)
        out = (tmp / "uit.txt").read_text(encoding="utf-8")
        ok = all(s not in out for s in ("Pietje", "Kerkstraat", "Eygelshoven", "6461ab")) and "Naam;adres" in out
        fails += not ok
        print(("ok   " if ok else "FOUT ") + f"tabel in .txt -> {out!r}")
    print("fouten:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
