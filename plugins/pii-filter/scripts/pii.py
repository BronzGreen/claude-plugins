"""PII-filter CLI (Microsoft Presidio, volledig lokaal).

  pii.py scan <bestand>                    telt PII per type + regelnummers (toont GEEN waarden);
                                           ook pdf/docx/pptx/xlsx/odf
  pii.py anonymize <bestand> [-o uit]      schrijft gepseudonimiseerde kopie, print pad + tellingen
  pii.py anonymize -                       stdin -> gepseudonimiseerde stdout
  pii.py text "Jan woont in Utrecht"       losse tekst pseudonimiseren
  pii.py deanonymize <bestand> -o <uit>    tokens terug naar echte waarden (alleen naar bestand)
  pii.py vault stats | vault clear --yes
  pii.py status                            installatie/config-status

Opties per subcommando: --lang nl|en, --max-lines N, --project <map> (voor .pii-filter.json)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pii_config as pc  # noqa: E402


def _filter(a):
    import pii_core as core

    cfg = pc.load_config(a.project or os.getcwd())
    return core, core.Filter(config=cfg, language=a.lang)


def cmd_anonymize(a):
    core, flt = _filter(a)
    if a.src == "-":
        text = sys.stdin.read()
        with core.Vault() as v:
            sys.stdout.write(flt.filter_text(text, v))
        print(json.dumps({"replacements": flt.counts}), file=sys.stderr)
        return
    src = Path(a.src)
    if a.output:
        dst = Path(a.output)
    else:
        pc.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dst = pc.sanitized_path(src, a.max_lines, pc.config_fingerprint(flt.cfg))
    if dst.resolve() == src.resolve():
        sys.exit("uitvoer mag niet het bronbestand zijn")
    with core.Vault() as v:
        stats = core.filter_file(flt, src, dst, v, max_lines=a.max_lines)
    print(json.dumps({"output": str(dst), **stats}, ensure_ascii=False))


def cmd_text(a):
    core, flt = _filter(a)
    with core.Vault() as v:
        print(flt.filter_text(a.text, v))


def cmd_scan(a):
    core, flt = _filter(a)
    src = Path(a.src)
    import pii_extract

    if src.suffix.lower() in pii_extract.DOC_EXTENSIONS:
        pc.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = pc.CACHE_DIR / "scan-tmp.txt"
        with core.Vault() as v:
            stats = core.filter_document(flt, src, tmp, v, max_lines=a.max_lines)
        tmp.unlink(missing_ok=True)
        print(json.dumps({"file": str(src), "by_entity": flt.counts,
                          "unreadable_pages": stats.get("unreadable_pages"),
                          "note": "waarden worden bewust niet getoond"}, ensure_ascii=False))
        return
    lines = core.read_text(src).splitlines()
    if a.max_lines:
        lines = lines[: a.max_lines]
    found, where = {}, {}
    for i, res in enumerate(flt.analyze_many(lines), start=1):
        for r in core._resolve_overlaps(res):
            found[r.entity_type] = found.get(r.entity_type, 0) + 1
            where.setdefault(r.entity_type, []).append(i)
    print(json.dumps({"file": str(src), "by_entity": found,
                      "first_lines": {k: v[:10] for k, v in where.items()},
                      "note": "waarden worden bewust niet getoond"}, ensure_ascii=False))


def cmd_deanonymize(a):
    import pii_core as core

    if not a.output:
        sys.exit("deanonymize schrijft alleen naar een bestand (-o); echte waarden horen niet in de chat")
    src, dst = Path(a.src), Path(a.output)
    if dst.resolve() == src.resolve():
        sys.exit("kies een ander uitvoerbestand dan de bron")
    with core.Vault() as v:
        out, n = v.reveal(core.read_text(src))
    dst.write_text(out, encoding="utf-8")
    print(json.dumps({"output": str(dst), "tokens_restored": n}))


def cmd_vault(a):
    import pii_core as core

    if a.action == "stats":
        with core.Vault() as v:
            print(json.dumps({"vault": str(pc.VAULT_PATH), "tokens_per_type": v.stats()}))
    elif a.action == "clear":
        if not a.yes:
            sys.exit("gebruik 'vault clear --yes'; bestaande tokens worden dan onomkeerbaar")
        pc.VAULT_PATH.unlink(missing_ok=True)
        if pc.CACHE_DIR.exists():
            for f in pc.CACHE_DIR.glob("*"):
                f.unlink()
        print("vault en cache gewist")


def cmd_status(a):
    cfg = pc.load_config(a.project or os.getcwd())
    print(json.dumps({
        "ready": pc.is_ready(),
        "enabled": pc.is_enabled(cfg),
        "enforced": pc.enforced(),
        "venv": str(pc.VENV_DIR),
        "vault": str(pc.VAULT_PATH),
        "project_config": str(pc.find_project_config(a.project or os.getcwd()) or ""),
        "user_config": str(pc.USER_CONFIG) if pc.USER_CONFIG.exists() else "",
        "setup_log": str(pc.SETUP_LOG),
    }, indent=1))


def cmd_report_leak(a):
    """Manual datalek report (skill datalek-melden). Never pass the leaked values themselves.

    The report states WHICH kinds of data (types, counts, where) and HOW they came in, and always
    carries an assessment of the meldplicht: the automatic one, or Claude's own via --advies/--motivering.
    """
    import pii_leak as leak

    cfg = pc.load_config(a.project or os.getcwd())
    counts, details = {}, []
    for part in filter(None, (a.types or "").split(",")):
        k, _, n = part.partition("=")
        k = k.strip().upper()
        counts[k] = set(range(int(n or 1)))
    for w in a.waar or []:  # "PERSON=kolom 'Naam'"
        k, _, basis = w.partition("=")
        details.append({"type": k.strip().upper(), "basis": basis.strip()})
    note = (a.note or "").strip()
    texts = [note, a.motivering or "", *(d["basis"] for d in details)]
    if any(leak.detect(t, cfg) for t in texts):
        sys.exit("de toelichting/motivering bevat zelf persoonsgegevens; beschrijf alleen wat voor "
                 "gegevens het waren, niet de gegevens zelf")
    source = {"tool": a.source or "handmatig", "ext": (a.ext or "").lstrip(".") or None,
              "project": Path(a.project or os.getcwd()).name, "session_id": a.session or "",
              "plugin_version": pc.plugin_version(), "automatic": False,
              "file_name": a.file_name or "", "eigen": bool(a.eigen_gegevens),
              "betrokkenen": a.betrokkenen, "hoe_kort": a.source, "melder": a.melder}
    n = a.betrokkenen if a.betrokkenen is not None else max([0, *(len(v) for v in counts.values())])
    assessment = leak.assess({k: len(v) for k, v in counts.items()}, cfg, eigen=bool(a.eigen_gegevens),
                             betrokkenen=n)
    if a.advies:
        motivering = (a.motivering or "").strip()
        if not motivering:
            sys.exit("--advies vraagt ook --motivering (waarom wel/niet melden)")
        assessment = {**assessment, "advies": a.advies, "label": leak.ADVIES_LABEL[a.advies],
                      "redenen": [motivering],
                      "tekst": (f"Inschatting meldplicht (advies melder/AI-sessie, geen besluit): "
                                f"{leak.ADVIES_LABEL[a.advies]}. Motivering: {motivering} "
                                f"Automatische inschatting PII-filter: {assessment['label']}. "
                                "Altijd registreren in het datalekkenregister (art. 33 lid 5). "
                                "De meldbeslissing neemt de privacy officer.")}
    report = leak.build_report(counts, source, note=note, details=details, cfg=cfg, assessment=assessment)
    leak.enqueue(report)
    res = leak.flush()
    sent = next((r for r in res["sent"] if r["local_ref"] == report["local_ref"]), None)
    print(json.dumps({"referentie": report["body"]["referentie"],
                      "status": "geregistreerd in BRIDGE" if sent else "in lokale wachtrij",
                      "bridge_api": leak.credentials()[1],
                      "fout": None if sent else res["error"],
                      "termijn_uiterlijk": sent.get("termijn_uiterlijk") if sent else None,
                      "wat": leak.describe(counts, details),
                      "hoe": leak.route_text(source),
                      "advies": assessment["label"],
                      "motivering": assessment["redenen"]},
                     ensure_ascii=False, indent=1))


def cmd_leaks(a):
    import pii_leak as leak

    if a.flush:
        print(json.dumps(leak.flush(), ensure_ascii=False, default=str))
        return
    pat, api = leak.credentials()
    sent = []
    if leak.SENT_LOG.exists():
        for line in leak.SENT_LOG.read_text(encoding="utf-8").splitlines()[-20:]:
            r = json.loads(line)
            sent.append({k: r.get(k) for k in ("referentie", "sent", "termijn_uiterlijk")})
    queue = sorted(p.name for p in leak.QUEUE_DIR.glob("*.json")) if leak.QUEUE_DIR.exists() else []
    print(json.dumps({"bridge_api": api, "token_ingesteld": bool(pat), "token_bestand": str(leak.ENV_FILE),
                      "wachtrij": queue, "laatst_verzonden": sent}, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lang", choices=["nl", "en"], default=None)
    common.add_argument("--max-lines", type=int, default=None)
    common.add_argument("--project", default=None, help="projectmap (voor .pii-filter.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("anonymize", parents=[common]); s.add_argument("src")
    s.add_argument("-o", "--output"); s.set_defaults(fn=cmd_anonymize)
    s = sub.add_parser("text", parents=[common]); s.add_argument("text"); s.set_defaults(fn=cmd_text)
    s = sub.add_parser("scan", parents=[common]); s.add_argument("src"); s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("deanonymize", parents=[common]); s.add_argument("src")
    s.add_argument("-o", "--output"); s.set_defaults(fn=cmd_deanonymize)
    s = sub.add_parser("vault", parents=[common]); s.add_argument("action", choices=["stats", "clear"])
    s.add_argument("--yes", action="store_true"); s.set_defaults(fn=cmd_vault)
    s = sub.add_parser("status", parents=[common]); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("report-leak", parents=[common],
                       help="datalek handmatig melden in BRIDGE (zonder de gegevens zelf)")
    s.add_argument("--types", help="bv. PERSON=2,EMAIL_ADDRESS=1")
    s.add_argument("--source", help="hoe het binnenkwam, bv. 'Read', 'Bash-output', 'plak in chat'")
    s.add_argument("--ext", help="bestandstype, bv. csv")
    s.add_argument("--note", help="korte toelichting ZONDER persoonsgegevens")
    s.add_argument("--waar", action="append", metavar="TYPE=PLEK",
                   help="waar het stond, zonder waarde, bv. \"PERSON=kolom 'Naam'\" (herhaalbaar)")
    s.add_argument("--file-name", help="bestandsnaam (wordt weggelaten als die zelf PII lijkt te bevatten)")
    s.add_argument("--betrokkenen", type=int, help="geschat aantal betrokkenen")
    s.add_argument("--eigen-gegevens", action="store_true",
                   help="het gaat om eigen gegevens van de melder (bv. een bewuste test)")
    s.add_argument("--advies", choices=["niet_melden", "beoordelen", "wel_melden"],
                   help="eigen inschatting van de meldplicht (anders: automatische inschatting)")
    s.add_argument("--motivering", help="motivering bij --advies, zonder persoonsgegevens")
    s.add_argument("--melder", help="bij wie het lek optrad (medewerker); standaard MELDER in het env-bestand of git user.name")
    s.add_argument("--session", help="sessie-id (optioneel)")
    s.set_defaults(fn=cmd_report_leak)
    s = sub.add_parser("leaks", parents=[common], help="meldingen: wachtrij, verzonden, token-status")
    s.add_argument("--flush", action="store_true", help="wachtrij nu versturen")
    s.set_defaults(fn=cmd_leaks)

    a = p.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    a.fn(a)


if __name__ == "__main__":
    main()
