"""Claude Code PostToolUse hook: did personal data reach Claude anyway? Standard library only.

Checks what the model actually received from:
  Read   of any file (pseudonymised copy, or an original the filter let through); images and
         excluded paths are skipped
  Bash / PowerShell commands that reference a data/document file
  Grep   in content mode
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
    return pc.plugin_version()


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


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}


def _orig_name(p: Path) -> tuple[str, str]:
    """(original file name, extension) for a path, also for a cached pseudonymised copy
    (<stem>.pii-sanitized.<hash><ext>[.txt])."""
    name = re.sub(r"\.pii-sanitized\.[0-9a-f]{10}", "", p.name)
    if norm(p).startswith(norm(pc.CACHE_DIR)) and name.endswith(".txt") and name.count(".") >= 2:
        name = name[:-4]  # document delivered as text: report.pdf.txt -> report.pdf
    return name, Path(name).suffix.lstrip(".").lower()


def source_for(tool: str, inp: dict, cfg: dict) -> dict | None:
    hcfg = cfg["hook"]
    if tool == "Read":
        p = Path(inp.get("file_path") or "")
        name, ext = _orig_name(p)
        if norm(p).startswith(norm(pc.CACHE_DIR)):
            return {"key": norm(p), "ext": ext, "filtered": True, "file_name": name}
        if p.suffix.lower() in IMAGE_EXTS or is_excluded(p, hcfg["exclude_globs"]):
            return None
        return {"key": norm(p), "ext": ext, "filtered": False, "file_name": name}
    if tool in ("Bash", "PowerShell"):
        cmd = inp.get("command") or ""
        if "pii.py" in cmd.lower():
            return None
        exts = "|".join(re.escape(e.lstrip(".")) for e in hcfg["data_extensions_for_shell"])
        m = re.search(rf"{PATH_TOKEN}\.({exts})\b", cmd, re.I)
        if m and not is_excluded(Path(m.group(0)), hcfg["exclude_globs"]):
            first = (cmd.strip().split() or ["?"])[0].strip("'\"&")
            return {"key": norm(m.group(0)), "ext": m.group(1).lower(), "filtered": False,
                    "file_name": Path(m.group(0)).name, "command_name": Path(first).name[:40]}
    if tool == "Grep" and (inp.get("output_mode") or "files_with_matches") == "content":
        target = str(inp.get("path") or inp.get("glob") or "")
        return {"key": "grep|" + norm(target) + "|" + str(inp.get("pattern", ""))[:80],
                "ext": Path(target).suffix.lstrip(".").lower() or "meerdere", "filtered": False,
                "file_name": Path(target).name if Path(target).suffix else "",
                "command_name": "Grep (zoekresultaten)"}
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
    details: list = []
    found = leak.detect(response_text(payload.get("tool_response")), cfg, details)
    if not found:
        return

    session = payload.get("session_id") or "?"
    if leak.seen_before(f"{session}|{src['key']}"):
        return
    source = {"tool": tool, "ext": src["ext"], "project": Path(cwd).name, "session_id": session,
              "plugin_version": plugin_version(), "filtered_copy": src["filtered"], "automatic": True,
              "file_name": src.get("file_name", ""), "command_name": src.get("command_name"),
              "path": src["key"]}  # full path stays local (queue/sent log), never in the BRIDGE body
    report = leak.build_report(found, source, details=details, cfg=cfg)
    leak.enqueue(report)
    res = leak.flush()
    wat = leak.describe(found, details)
    advies = report["assessment"]["label"]
    ref = report["body"]["referentie"]
    if any(r["local_ref"] == report["local_ref"] for r in res["sent"]):
        status = "geregistreerd in BRIDGE, privacy officer gemaild"
    else:
        status = (f"in lokale wachtrij ({res['error'] or 'onbekende fout'}); "
                  "wordt bij de volgende sessie opnieuw verstuurd")
    emit(f"⚠️ PII-filter datalek {ref}: {report['body']['samenvatting']} — {status}. Advies: {advies}.",
         f"PII-filter: in de zojuist ontvangen output van {tool} zitten waarschijnlijk persoonsgegevens "
         f"({wat}) die het filter niet heeft vervangen. Hoe: {leak.route_text(source)}. "
         f"Datalekmelding {ref}: {status}. {report['assessment']['tekst']} "
         "Herhaal deze gegevens niet in je antwoord, gebruik ze niet in code of commits, en meld het kort aan "
         "de gebruiker: welke soort gegevens, hoe ze binnenkwamen, de referentie en de inschatting van de "
         "meldplicht met motivering. Stel indien zinvol een aanvulling voor in .pii-filter.json.")


if __name__ == "__main__":
    main()
