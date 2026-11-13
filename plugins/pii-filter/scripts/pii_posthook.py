"""Claude Code PostToolUse hook: did personal data reach Claude anyway? Standard library only.

Checks what the model actually received from:
  Read   of a pseudonymised copy (pii-vault/cache) or of a data file the filter let through
  Bash / PowerShell commands that reference a data file
On a hit: register an AVG datalek in BRIDGE (queued locally when BRIDGE/token is unavailable),
tell the user (systemMessage) and Claude (additionalContext). One report per source per session.

Also usable as:  pii_posthook.py --flush   (send queued reports; async SessionStart hook)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pii_config as pc  # noqa: E402
import pii_leak as leak  # noqa: E402
from pii_hook import PATH_TOKEN, is_excluded, norm  # noqa: E402


def plugin_version() -> str:
    try:
        return json.loads((pc.PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return "?"


def response_text(resp) -> str:
    """Collect every string in the tool response (shape differs per tool/version)."""
    parts: list[str] = []

    def walk(x):
        if isinstance(x, str):
            parts.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(resp)
    return "\n".join(parts)


def source_for(tool: str, inp: dict, cfg: dict) -> dict | None:
    hcfg = cfg["hook"]
    if tool == "Read":
        p = Path(inp.get("file_path") or "")
        in_cache = norm(p).startswith(norm(pc.CACHE_DIR))
        if in_cache:
            # sanitized copy: name is <stem>.pii-sanitized.<hash><ext>
            return {"key": norm(p), "ext": p.suffix.lstrip(".").lower(), "filtered": True}
        if p.suffix.lower() in hcfg["read_extensions"] and not is_excluded(p, hcfg["exclude_globs"]):
            return {"key": norm(p), "ext": p.suffix.lstrip(".").lower(), "filtered": False}
        return None
    if tool in ("Bash", "PowerShell"):
        cmd = inp.get("command") or ""
        if "pii.py" in cmd.lower():
            return None
        exts = "|".join(re.escape(e.lstrip(".")) for e in hcfg["data_extensions_for_shell"])
        m = re.search(rf"{PATH_TOKEN}\.({exts})\b", cmd, re.I)
        if m:
            return {"key": norm(m.group(0)), "ext": m.group(1).lower(), "filtered": False}
    return None


def emit(user_msg: str, context: str):
    sys.stdout.write(json.dumps({
        "systemMessage": user_msg,
        "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context},
    }, ensure_ascii=False))
    sys.exit(0)


def main():
    if "--flush" in sys.argv:
        res = leak.flush()
        if res["sent"] or res["error"]:
            print(json.dumps({"verzonden": len(res["sent"]), "wachtrij": res["pending"],
                              "fout": res["error"]}, ensure_ascii=False))
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        cwd = payload.get("cwd") or os.getcwd()
        cfg = pc.load_config(cwd)
    except Exception as e:  # noqa: BLE001
        print(f"pii-filter posthook: {e}", file=sys.stderr)
        return
    if not pc.is_enabled(cfg) or not cfg.get("leak_check", {}).get("enabled", True):
        return
    tool = payload.get("tool_name", "")
    src = source_for(tool, payload.get("tool_input") or {}, cfg)
    if not src:
        return
    found = leak.detect(response_text(payload.get("tool_response")), cfg)
    if not found:
        return

    session = payload.get("session_id") or "?"
    if leak.seen_before(f"{session}|{src['key']}"):
        return
    source = {"tool": tool, "ext": src["ext"], "project": Path(cwd).name, "session_id": session,
              "plugin_version": plugin_version(), "filtered_copy": src["filtered"], "automatic": True,
              "path": src["key"]}  # path stays local (queue/sent log), never in the BRIDGE body
    report = leak.build_report(found, source)
    leak.enqueue(report)
    res = leak.flush()
    counts = ", ".join(f"{leak.LABELS.get(k, k)} {len(v)}x" for k, v in sorted(found.items()))
    ref = report["body"]["referentie"]
    if any(r["local_ref"] == report["local_ref"] for r in res["sent"]):
        status = f"datalek {ref} geregistreerd in BRIDGE (ISMS → datalekken); de privacy officer wordt gemaild"
    else:
        status = (f"datalek {ref} staat in de lokale wachtrij ({res['error'] or 'onbekende fout'}); "
                  "wordt bij de volgende sessie opnieuw verstuurd")
    emit(f"⚠️ PII-filter: mogelijk persoonsgegevens doorgelekt ({counts}) — {status}.",
         f"PII-filter: in de zojuist ontvangen output van {tool} zitten waarschijnlijk persoonsgegevens "
         f"({counts}) die het filter niet heeft vervangen. Er is automatisch een datalekmelding gedaan: {status}. "
         "Herhaal deze gegevens niet in je antwoord, gebruik ze niet in code of commits, en meld het kort aan "
         "de gebruiker. Stel indien zinvol een aanvulling voor in .pii-filter.json.")


if __name__ == "__main__":
    main()
