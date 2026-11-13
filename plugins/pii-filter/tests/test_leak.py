"""Leak detection + datalek reporting against a fake BRIDGE (stdlib only, fictional data).

Run: python tests/test_leak.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LEAKY = ("Contact: piet.pietersen@bedrijf-x.nl, IBAN NL91ABNA0417164300, BSN 123456782, "
         "mobiel 06-12345678. Al gefilterd: <PERSON_1> <EMAIL_ADDRESS_2>. Test: a@example.com, "
         "ordernr 987654321, rekening NL00XXXX0000000000.")
SECRET_VALUES = ["piet.pietersen", "bedrijf-x", "NL91ABNA0417164300", "123456782", "12345678"]

received = []


class FakeBridge(BaseHTTPRequestHandler):
    status = 201

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        received.append({"path": self.path, "auth": self.headers.get("Authorization"),
                         "idem": self.headers.get("Idempotency-Key"), "body": body})
        self.send_response(FakeBridge.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "abc123", "referentie": body["referentie"],
                                     "termijn_uiterlijk": "2026-11-16T12:00:00Z"}).encode())

    def log_message(self, *a):
        pass


def bash():
    for c in (os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"), r"C:\Program Files\Git\bin\bash.exe"):
        if c and Path(c).exists():
            return c
    return "bash"


def main():
    fails = 0

    def check(name, cond, detail=""):
        nonlocal fails
        print(("ok   " if cond else "FOUT ") + name + ("" if cond else f"  -> {detail}"))
        fails += not cond

    srv = HTTPServer(("127.0.0.1", 0), FakeBridge)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{srv.server_port}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        proj = tmp / "klantproject"; proj.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PII_", "CLAUDE_PLUGIN"))}
        env.update({"CLAUDE_PLUGIN_ROOT": str(ROOT), "CLAUDE_PLUGIN_DATA": str(tmp / "data"),
                    "PII_VAULT_DIR": str(tmp / "vault"), "PII_FILTER_ENV": str(tmp / "noenv"),
                    "PII_BRIDGE_API_BASE": api, "PII_BRIDGE_PAT": "bgp_test"})
        os.environ.update(env)
        import pii_leak as leak  # after env, so paths point to tmp

        # --- detection
        found = leak.detect(LEAKY, {"allow_list": []})
        check("detectie: e-mail/IBAN/BSN/mobiel", set(found) == {"EMAIL_ADDRESS", "IBAN_CODE", "NL_BSN", "PHONE_NUMBER"}, found)
        check("example.com, ordernummer, ongeldige IBAN en tokens genegeerd",
              {k: len(v) for k, v in found.items()} == {"EMAIL_ADDRESS": 1, "IBAN_CODE": 1, "NL_BSN": 1, "PHONE_NUMBER": 1}, found)
        check("BSN zonder context niet gemeld", "NL_BSN" not in leak.detect("nummer 123456782", {}))

        def hook(payload, extra=None):
            r = subprocess.run([bash(), str(ROOT / "scripts" / "run-hook.sh"), "post"],
                               input=json.dumps(payload).encode(), capture_output=True,
                               env={**env, **(extra or {})}, timeout=60)
            out = r.stdout.decode("utf-8").strip()
            return (json.loads(out) if out else {}), r.stderr.decode("utf-8", "replace")

        read_payload = {"tool_name": "Read", "session_id": "sess-1", "cwd": str(proj),
                        "tool_input": {"file_path": str(proj / "export.csv")},
                        "tool_response": {"type": "text", "file": {"content": LEAKY}}}

        # --- automatic report via PostToolUse
        out, err = hook(read_payload)
        check("hook meldt lek", "datalek" in out.get("systemMessage", ""), out or err)
        check("Claude krijgt instructie", "Herhaal deze gegevens niet" in
              out.get("hookSpecificOutput", {}).get("additionalContext", ""), out)
        check("1 POST naar /api/v1/isms/datalekken", len(received) == 1 and received[0]["path"] == "/api/v1/isms/datalekken", received)
        if received:
            r0 = received[0]
            b = r0["body"]
            blob = json.dumps(b)
            check("Bearer-token + Idempotency-Key", r0["auth"] == "Bearer bgp_test" and r0["idem"], r0)
            check("verplichte velden", all(b.get(k) for k in ("referentie", "samenvatting", "geconstateerd_op", "aard", "rol")), b)
            check("rol/meldbeslissing/status", (b["rol"], b["meldbeslissing"], b["status"]) == ("nog_te_bepalen", "nog_te_bepalen", "open"), b)
            check("GEEN persoonsgegevens in melding", not any(s.lower() in blob.lower() for s in SECRET_VALUES), blob)
            check("geen bestandspad in melding", "export.csv" not in blob and str(tmp) not in blob, blob)
            check("geen 8+ cijferreeksen (BSN-guard BRIDGE)", not re.search(r"\d{8,}", blob.replace(b["geconstateerd_op"], "")), blob)
            check("projectnaam en aantallen staan erin", "klantproject" in b["samenvatting"] and "IBAN 1x" in b["samenvatting"], b["samenvatting"])

        out, _ = hook(read_payload)
        check("zelfde bestand zelfde sessie: geen tweede melding", out == {} and len(received) == 1, (out, len(received)))
        clean = {**read_payload, "session_id": "sess-2", "tool_response": {"file": {"content": "<PERSON_1> woont in <LOCATION_2>"}}}
        out, _ = hook(clean)
        check("gefilterde output: geen melding", out == {} and len(received) == 1, out)
        code = {**read_payload, "session_id": "sess-3", "tool_input": {"file_path": str(proj / "main.go")}}
        out, _ = hook(code)
        check("codebestand niet gecontroleerd", out == {}, out)

        # --- queue when BRIDGE refuses, flush later
        FakeBridge.status = 403
        out, _ = hook({**read_payload, "session_id": "sess-4"})
        check("403 -> lokale wachtrij", "wachtrij" in out.get("systemMessage", ""), out)
        check("melding staat in wachtrij", len(list((tmp / "data" / "leaks" / "queue").glob("*.json"))) == 1)
        FakeBridge.status = 201
        r = subprocess.run([bash(), str(ROOT / "scripts" / "run-hook.sh"), "flush"], capture_output=True, env=env, timeout=60)
        check("flush verstuurt wachtrij", '"verzonden": 1' in r.stdout.decode() and not list((tmp / "data" / "leaks" / "queue").glob("*.json")), r.stdout)

        # --- manual report refuses PII in the note
        py = sys.executable
        r = subprocess.run([py, str(ROOT / "scripts" / "pii.py"), "report-leak", "--types", "PERSON=2",
                            "--note", "zag jan@bedrijf-x.nl"], capture_output=True, env=env, cwd=proj)
        check("handmatig: PII in toelichting geweigerd", r.returncode != 0 and len(received) == 3, r.stderr)
        r = subprocess.run([py, str(ROOT / "scripts" / "pii.py"), "report-leak", "--types", "PERSON=2",
                            "--source", "Bash-output", "--ext", "csv", "--note", "script printte klantregels"],
                           capture_output=True, env=env, cwd=proj)
        res = json.loads(r.stdout.decode() or "{}")
        check("handmatig melden werkt", res.get("status") == "geregistreerd in BRIDGE" and len(received) == 4, (res, r.stderr))
        if len(received) == 4:
            check("handmatig: ontdekt_door medewerker", received[3]["body"]["ontdekt_door"].startswith("Medewerker"), received[3]["body"])

    srv.shutdown()
    print("fouten:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
