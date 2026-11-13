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

        empty = tmp / "notready"; empty.mkdir()
        out, err = run(read(proj / "klanten.csv"), empty, vault)
        hso = out.get("hookSpecificOutput", {})
        check("nog niet geïnstalleerd -> weigeren", hso.get("permissionDecision") == "deny"
              and "geïnstalleerd" in hso.get("permissionDecisionReason", ""), out or err)

    print("fouten:", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
