"""End-to-end: feed PreToolUse payloads through scripts/run-hook.sh (bash) like Claude Code does.

Run: python tests/test_hook_e2e.py <plugin-data-dir-with-finished-setup>
Uses only fictional data in a temp dir and a temp vault.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CSV = (
    "klantnr;voornaam;achternaam;email;telefoon;bsn;opmerking\n"
    "1001;Jan;de Vries;jan.devries@example.nl;06-12345678;111222333;Belt na 17u, vrouw Marieke Jansen\n"
    "1002;Fatima;El Amrani;f.elamrani@voorbeeld.com;+31 20 555 1234;123456782;Toteco levert\n"
)
CLEAN_CSV = "id,product,prijs\n1,Schroef,0.10\n2,Moer,0.05\n"


def _bash():
    # On Windows plain "bash" can resolve to WSL; Claude Code itself uses Git Bash.
    for c in (os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), r"C:\Program Files\Git\bin\bash.exe"):
        if c and Path(c).exists():
            return c
    return "bash"


BASH = _bash()


def make_pdf(lines, image=False) -> bytes:
    """Minimal valid PDF: one page with text lines (Helvetica), or only an image (a 'scan')."""
    if image:
        content = b"q 200 0 0 200 50 500 cm /Im1 Do Q"
        res = b"<< /XObject << /Im1 5 0 R >> >>"
    else:
        ops = ["BT /F1 12 Tf 50 750 Td 14 TL"] + [
            "(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for l in lines] + ["ET"]
        content = "\n".join(ops).encode("latin-1")
        res = b"<< /Font << /F1 4 0 R >> >>"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources " + res + b" /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8 "
        b"/Length 4 >>\nstream\n\x00\xff\xff\x00\nendstream",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def run(payload, data_dir, vault_dir, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PII_FILTER")}
    env.update({"CLAUDE_PLUGIN_ROOT": str(ROOT), "CLAUDE_PLUGIN_DATA": str(data_dir),
                "PII_VAULT_DIR": str(vault_dir), **(extra_env or {})})
    r = subprocess.run([BASH, str(ROOT / "scripts" / "run-hook.sh")], input=json.dumps(payload).encode(),
                       capture_output=True, env=env, timeout=180)
    out = r.stdout.decode("utf-8").strip()
    return (json.loads(out) if out else {}), r.stderr.decode("utf-8", "replace")


def main():
    data_dir = Path(sys.argv[1])
    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "proj"; proj.mkdir(); (proj / ".git").mkdir()
        (proj / "klanten.csv").write_text(FIXTURE_CSV, encoding="utf-8")
        (proj / "producten.csv").write_text(CLEAN_CSV, encoding="utf-8")
        (proj / ".pii-filter.json").write_text(json.dumps({"allow_list": ["Toteco"]}), encoding="utf-8")
        vault = tmp / "vault"

        def check(name, cond, detail=""):
            nonlocal fails
            print(("ok   " if cond else "FOUT ") + name + ("" if cond else f"  -> {detail}"))
            fails += not cond

        read = lambda p, **kw: {"tool_name": "Read", "cwd": str(proj), "tool_input": {"file_path": str(p), **kw}}

        out, err = run(read(proj / "klanten.csv"), data_dir, vault)
        hso = out.get("hookSpecificOutput", {})
        new = hso.get("updatedInput", {}).get("file_path", "")
        check("PII-csv wordt omgeleid", hso.get("permissionDecision") == "allow" and new, out or err)
        if new:
            txt = Path(new).read_text(encoding="utf-8")
            check("namen/email/bsn weg", all(x not in txt for x in ["Jan", "Vries", "jan.devries", "111222333", "Marieke"]), txt)
            check("projectconfig allow_list (Toteco blijft)", "Toteco" in txt, txt)
            check("additionalContext voor Claude", "pseudoniem" in hso.get("additionalContext", ""), hso)
        out, _ = run(read(proj / "klanten.csv"), data_dir, vault)
        check("tweede keer uit cache, zelfde pad", out.get("hookSpecificOutput", {}).get("updatedInput", {}).get("file_path") == new)

        out, err = run(read(proj / "producten.csv"), data_dir, vault)
        check("schone csv -> origineel", out == {}, out or err)
        out, _ = run(read(ROOT / "scripts" / "pii.py"), data_dir, vault)
        check("codebestand ongemoeid", out == {}, out)
        out, _ = run(read(vault / "vault.json"), data_dir, vault)
        check("vault geweigerd", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out)

        shell = {"tool_name": "Bash", "cwd": str(proj), "tool_input": {"command": "head -3 klanten.csv"}}
        out, _ = run(shell, data_dir, vault)
        check("shell-viewer geweigerd", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out)
        out, _ = run({**shell, "tool_input": {"command": "npm test"}}, data_dir, vault)
        check("gewoon commando vrij", out == {}, out)

        out, _ = run(shell, data_dir, vault, {"PII_FILTER": "off"})
        check("PII_FILTER=off schakelt uit", out == {}, out)
        out, _ = run(shell, data_dir, vault, {"PII_FILTER": "off", "PII_FILTER_ENFORCED": "1"})
        check("ENFORCED negeert PII_FILTER=off", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out)

        # ---- 0.3.0: every file is checked
        def redirected(p, *forbidden, must=()):
            o, e = run(read(p), data_dir, vault)
            h = o.get("hookSpecificOutput", {})
            nf = h.get("updatedInput", {}).get("file_path", "")
            if not (h.get("permissionDecision") == "allow" and nf):
                return False, o or e
            t = Path(nf).read_text(encoding="utf-8")
            return all(x not in t for x in forbidden) and all(x in t for x in must), t

        (proj / "testdata.txt").write_text("Naam;adres;postcode\nPietje;Kerkstraat 5 Eygelshoven;6461ab\n",
                                           encoding="utf-8")
        ok, d = redirected(proj / "testdata.txt", "Pietje", "Kerkstraat", "Eygelshoven", "6461ab")
        check(".txt met tabel (kolomnamen) gefilterd", ok, d)
        (proj / "notities.md").write_text("# Notities\nContact: piet.pietersen@bedrijf-x.nl, 06-12345678\n",
                                          encoding="utf-8")
        ok, d = redirected(proj / "notities.md", "piet.pietersen", "29384756")
        check("markdown met e-mail/06 gefilterd", ok, d)
        (proj / "seed.py").write_text('USERS = [("Piet", "piet.pietersen@bedrijf-x.nl", "NL68RABO0312874659")]\n',
                                      encoding="utf-8")
        ok, d = redirected(proj / "seed.py", "piet.pietersen", "NL68RABO0312874659")
        check("code met e-mail/IBAN gefilterd", ok, d)
        (proj / "README.md").write_text("# Project\nInstalleer met npm install.\n", encoding="utf-8")
        out, _ = run(read(proj / "README.md"), data_dir, vault)
        check("schone markdown -> origineel", out == {}, out)
        (proj / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        out, _ = run(read(proj / "logo.png"), data_dir, vault)
        check("afbeelding standaard doorgelaten", out == {}, out)

        import docx as _docx
        d = _docx.Document()
        d.add_paragraph("Verslag: Jan de Vries woont in Kerkrade, bel 06-12345678.")
        t = d.add_table(rows=2, cols=3)
        for i, v in enumerate(["Naam", "Email", "Postcode"]):
            t.cell(0, i).text = v
        for i, v in enumerate(["Fatima El Amrani", "f.elamrani@bedrijf-x.nl", "6461ab"]):
            t.cell(1, i).text = v
        d.save(proj / "verslag.docx")
        ok, d = redirected(proj / "verslag.docx", "Vries", "Kerkrade", "12345678", "Fatima", "elamrani", "6461ab",
                           must=("Verslag", "Naam"))
        check("docx (tekst + tabel) als gefilterde tekst", ok, d)

        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(["klantnr", "achternaam", "telefoon"]); ws.append([1001, "Jansen", "+31 (0)6 1234 5678"])
        wb.save(proj / "export.xlsx")
        ok, d = redirected(proj / "export.xlsx", "Jansen", "1234 5678", must=("achternaam",))
        check("xlsx als gefilterde tekst", ok, d)

        (proj / "brief.pdf").write_bytes(make_pdf(["Geachte heer Jansen,", "uw BSN is 123456782.",
                                                    "Hoofdstraat 12, 6461 AB Kerkrade"]))
        ok, d = redirected(proj / "brief.pdf", "Jansen", "123456782", "Hoofdstraat", must=("Geachte",))
        check("pdf als gefilterde tekst", ok, d)
        (proj / "offerte.pdf").write_bytes(make_pdf(["Offerte schroeven en moeren", "Totaal 12 euro"]))
        out, _ = run(read(proj / "offerte.pdf"), data_dir, vault)
        check("schone pdf -> origineel (Read toont pdf zelf)", out == {}, out)
        (proj / "scan.pdf").write_bytes(make_pdf([], image=True))
        out, _ = run(read(proj / "scan.pdf"), data_dir, vault)
        check("gescande pdf zonder tekstlaag geweigerd",
              out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out)

        sh = lambda c: {"tool_name": "Bash", "cwd": str(proj), "tool_input": {"command": c}}
        out, _ = run(sh("cat notities.txt"), data_dir, vault)
        check("cat van .txt geweigerd", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out)
        out, _ = run(sh("pdftotext brief.pdf -"), data_dir, vault)
        check("pdftotext geweigerd", out.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", out)
        out, _ = run(sh("cat requirements.txt"), data_dir, vault)
        check("cat van uitgezonderd bestand (requirements.txt) vrij", out == {}, out)

        empty = tmp / "notready"; empty.mkdir()
        out, err = run(read(proj / "klanten.csv"), empty, vault)
        hso = out.get("hookSpecificOutput", {})
        check("nog niet geïnstalleerd -> weigeren", hso.get("permissionDecision") == "deny"
              and "geïnstalleerd" in hso.get("permissionDecisionReason", ""), out or err)

    print("fouten:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
