"""Claude Code PreToolUse hook: automatische PII-filtering. Standard library only.

Read   -> elk bestand wordt gecontroleerd:
          databestanden (csv/json/log/eml/...) gaan altijd lokaal door Presidio (plugin-venv);
          documenten (pdf/docx/pptx/xlsx/odf) worden naar tekst omgezet en gefilterd;
          overige tekst (code, markdown, html, ...) krijgt eerst een snelle controle op harde
          kenmerken en persoonsgegevens-tabellen, en gaat bij een treffer ook door Presidio.
          Bevat het bestand PII, dan leest Claude een gepseudonimiseerde kopie.
          Geen PII -> het origineel wordt gewoon gelezen (Edit blijft werken).
Bash / PowerShell -> commando's die een databestand rauw tonen worden geweigerd.
Grep   -> content-zoekopdrachten in databestanden worden geweigerd.
Altijd -> de vault (echte waarden) is niet leesbaar voor Claude.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pii_config as pc  # noqa: E402


def emit(decision: str, reason: str = "", updated: dict | None = None,
         user_msg: str | None = None, context: str | None = None):
    hso = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if reason:
        hso["permissionDecisionReason"] = reason
    if updated is not None:
        hso["updatedInput"] = updated
    if context:
        hso["additionalContext"] = context
    out = {"hookSpecificOutput": hso}
    if user_msg:
        out["systemMessage"] = user_msg
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(0)


def norm(p) -> str:
    return str(p).replace("\\", "/").lower()


def is_excluded(path: Path, globs: list) -> bool:
    p = "/" + norm(path).lstrip("/")
    return any(fnmatch.fnmatch(p, g.lower()) for g in globs)


def touches_vault(text: str) -> bool:
    t = norm(text)
    return norm(pc.VAULT_DIR) + "/vault" in t or "pii-vault/vault" in t or "vault.json" in t


# --------------------------------------------------------------------------- Read
DOC_EXTS = {".pdf", ".docx", ".docm", ".pptx", ".xlsx", ".xlsm", ".odt", ".ods", ".odp"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}


def needs_full_filter(path: Path, cfg: dict) -> bool:
    """Files outside the data/document extensions (code, markdown, html, unknown text):
    a fast stdlib check for hard identifiers and personal-data tables decides."""
    hcfg = cfg["hook"]
    if not hcfg.get("scan_all_files", True):
        return False
    cap = int(hcfg.get("prescan_max_bytes", 5_000_000))
    try:
        with open(path, "rb") as f:
            raw = f.read(cap)
    except OSError:
        return False
    if b"\x00" in raw[:8192]:
        return False  # binary
    import pii_leak as leak
    return leak.quick_scan(raw.decode("utf-8", "replace"), cfg)


def handle_read(inp: dict, cfg: dict, cwd: str):
    hcfg = cfg["hook"]
    path = Path(inp.get("file_path") or "")
    if touches_vault(str(path)):
        emit("deny", "De PII-vault bevat echte persoonsgegevens en is niet leesbaar voor Claude. "
                     "Echte waarden terugzetten doet de gebruiker met `pii.py deanonymize <bestand> -o <uit>`.")
    if is_excluded(path, hcfg["exclude_globs"]) or not path.is_file():
        return
    if norm(path).startswith(norm(pc.CACHE_DIR)):
        return  # already a pseudonymised copy
    size = path.stat().st_size
    if size == 0:
        return
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        if hcfg.get("block_images", False):
            emit("deny", f"PII-filter: afbeeldingen ({path.name}) kunnen niet op persoonsgegevens worden "
                         "gecontroleerd en zijn in deze configuratie geblokkeerd (hook.block_images).")
        return
    is_doc = ext in DOC_EXTS
    if not is_doc and ext not in hcfg["read_extensions"]:
        if size > int(hcfg["max_bytes"]) or not needs_full_filter(path, cfg):
            return

    fail_open = hcfg.get("fail_mode", "closed") == "open" and not pc.enforced()
    if not pc.is_ready():
        if fail_open:
            return
        emit("deny", f"PII-filter wordt nog geïnstalleerd (Presidio + taalmodel, eenmalig enkele minuten), "
                     f"daarom is {path.name} nog niet gelezen. Meld dit aan de gebruiker; voortgang staat in "
                     f"{pc.SETUP_LOG}. Probeer het daarna opnieuw.")

    offset = int(inp.get("offset") or 1)
    limit = int(inp.get("limit") or 2000)
    max_lines = min(max(offset - 1 + limit, 2000), int(hcfg["max_lines"]))
    if size > int(hcfg["max_bytes"]):
        emit("deny", f"Bestand is te groot ({size // 1_000_000} MB) voor automatische PII-filtering. "
                     f"Maak een gefilterde steekproef: {pc.cli_command()} anonymize \"{path}\" "
                     f"--max-lines 2000 --project \"{cwd}\" en lees het uitvoerpad.")

    dst = pc.sanitized_path(path, max_lines, pc.config_fingerprint(cfg), out_suffix=".txt" if is_doc else "")
    meta_path = dst.with_name(dst.name + ".meta.json")
    stats = None
    if meta_path.exists() and (dst.exists() or (not is_doc and
                                                json.loads(meta_path.read_text("utf-8")).get("replacements") == 0)):
        stats = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        pc.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cmd = [str(pc.venv_python()), str(pc.PLUGIN_ROOT / "scripts" / "pii.py"), "anonymize", str(path),
               "-o", str(dst), "--max-lines", str(max_lines), "--project", cwd or os.getcwd()]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=110,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or "onbekend")
            stats = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
            meta_path.write_text(json.dumps(stats), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            if fail_open:
                return
            emit("deny", f"PII-filter kon {path.name} niet verwerken ({type(e).__name__}: {e}). "
                         "Bestand niet gelezen om lekken te voorkomen. Meld dit aan de gebruiker.")

    unreadable = stats.get("unreadable_pages") or []
    if is_doc and unreadable and len(unreadable) >= (stats.get("pages") or 1) and not fail_open:
        emit("deny", f"PII-filter: {path.name} bevat alleen gescande pagina's (afbeeldingen zonder tekstlaag). "
                     "Die kunnen niet op persoonsgegevens worden gecontroleerd, dus het bestand is niet gelezen. "
                     "Vraag de gebruiker om een pdf met tekstlaag (OCR) of om de relevante tekst zelf te geven.")

    if not stats.get("replacements"):
        # clean: read the original, except documents Read cannot show as text and partly scanned pdfs
        if not is_doc:
            try:
                dst.unlink()  # only keep the meta marker ('clean')
            except OSError:
                pass
            return
        if ext == ".pdf" and not unreadable:
            return

    updated = {k: v for k, v in inp.items() if k != "pages"}
    updated["file_path"] = str(dst)
    if offset - 1 >= max_lines:
        updated["offset"] = 1
    summary = ", ".join(f"{k} {n}" for k, n in sorted(stats["by_entity"].items())) or "geen PII gevonden"
    extra = f" Pagina's zonder tekstlaag (niet getoond): {', '.join(map(str, unreadable))}." if unreadable else ""
    kind = "gepseudonimiseerde tekstversie" if is_doc else "gepseudonimiseerde kopie"
    shown = (f"gepseudonimiseerd ({summary})" if stats.get("replacements")
             else "als tekst gelezen (geen PII gevonden)")
    emit("allow",
         reason=f"PII-filter: {kind} van {path.name}",
         updated=updated,
         user_msg=f"🔒 PII-filter: {path.name} {shown}"
                  + (" — afgekapt" if stats.get("truncated") else "")
                  + (" — gescande pagina's overgeslagen" if unreadable else ""),
         context=(f"PII-filter: je ziet een {kind} van {path} ({summary}).{extra} "
                  "Tokens als <PERSON_1> zijn consistente pseudoniemen, geen fouten in de data. "
                  "Het origineel is niet gelezen; Edit op het origineel vraagt eerst toestemming van de gebruiker "
                  "om het bestand uit te zonderen (.pii-filter.json → hook.exclude_globs)."))


# --------------------------------------------------------------------------- shell
VIEWERS = re.compile(
    r"(?<![\w-])(cat|head|tail|less|more|type|gc|get-content|import-csv|import-excel|sed|awk|"
    r"grep|egrep|rg|findstr|select-string|xxd|od|strings|jq|csvlook|column|bat|pdftotext|docx2txt|"
    r"catdoc|antiword|in2csv|xlsx2csv|textutil|pandoc)(?![\w-])",
    re.I,
)


PATH_TOKEN = r"[\w.\\/:~*?\-]+"


def shows_data_file(cmd: str, cfg: dict) -> bool:
    """True when a viewer command gets a data file as a path argument.

    Checked per pipeline segment, so 'cat x.csv | wc -l' still counts but
    'sed -i s#a.log#b.log# file.sh' or 'echo data.csv' does not.
    """
    exts = "|".join(re.escape(e.lstrip(".")) for e in cfg["hook"]["data_extensions_for_shell"])
    data_arg = re.compile(rf"^{PATH_TOKEN}\.({exts})$", re.I)
    for seg in re.split(r"\|\||&&|[|;\n]", cmd):
        m = VIEWERS.search(seg)
        if not m:
            continue
        if m.group(1).lower() in ("sed", "awk") and re.search(r"\s-i\b|--in-place", seg):
            continue  # in-place edit, prints nothing
        tokens = [t.strip("'\"`(),") for t in seg[m.end():].split()]
        if any(data_arg.match(t) and not is_excluded(Path(t), cfg["hook"]["exclude_globs"])
               for t in tokens if t and not t.startswith("-")):
            return True
        # input redirection: < file.csv
        if re.search(rf"<\s*[\"']?{PATH_TOKEN}\.({exts})\b", seg, re.I):
            return True
    return False


def handle_shell(inp: dict, cfg: dict):
    cmd = inp.get("command") or ""
    low = cmd.lower()
    if touches_vault(low):
        emit("deny", "De PII-vault bevat echte persoonsgegevens en is niet toegankelijk voor Claude.")
    if "pii.py" in low or not cfg["hook"].get("block_shell_viewers", True):
        return
    if shows_data_file(cmd, cfg):
        c = pc.cli_command()
        emit("deny",
             "PII-filter: dit commando toont een databestand ongefilterd. Gebruik de Read-tool "
             "(wordt automatisch gefilterd) of maak eerst een gepseudonimiseerde kopie:\n"
             f"  {c} anonymize <bestand>\n  {c} scan <bestand>   (alleen tellingen)\n"
             "en werk op het uitvoerpad. Code die de data verwerkt zonder records te printen mag gewoon draaien.")


# --------------------------------------------------------------------------- Grep
def handle_grep(inp: dict, cfg: dict):
    target = " ".join(str(inp.get(k) or "") for k in ("path", "glob", "type")).lower()
    if touches_vault(target):
        emit("deny", "De PII-vault is niet doorzoekbaar voor Claude.")
    if not cfg["hook"].get("block_grep_content", True):
        return
    if (inp.get("output_mode") or "files_with_matches") != "content":
        return
    exts = [e.lstrip(".") for e in cfg["hook"].get("grep_block_extensions",
                                                 cfg["hook"]["data_extensions_for_shell"])]
    if any(re.search(rf"(\.|\b){re.escape(e)}\b", target) for e in exts):
        emit("deny", "PII-filter: Grep met output_mode=content op databestanden toont ongefilterde PII. "
                     "Gebruik files_with_matches/count, Read (automatisch gefilterd) of "
                     f"{pc.cli_command()} anonymize <bestand>.")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        cwd = payload.get("cwd") or os.getcwd()
        cfg = pc.load_config(cwd)
    except Exception as e:  # noqa: BLE001 - broken payload/config must not brick the session
        print(f"pii-filter hook: {e}", file=sys.stderr)
        return
    if not pc.is_enabled(cfg):
        return
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    if tool == "Read":
        handle_read(inp, cfg, cwd)
    elif tool in ("Bash", "PowerShell"):
        handle_shell(inp, cfg)
    elif tool == "Grep":
        handle_grep(inp, cfg)


if __name__ == "__main__":
    main()
