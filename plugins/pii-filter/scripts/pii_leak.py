"""Second line of defence: detect personal data that still reached Claude, and report it
as an AVG datalek in BRIDGE (ISMS -> datalekkenregister). Standard library only.

Detection is deliberately narrow and verifiable (few false positives):
  EMAIL_ADDRESS  e-mail address (reserved example/test domains and allow-listed domains ignored)
  IBAN_CODE      IBAN with a valid mod-97 checksum
  NL_BSN         9 digits passing the 11-proef, with a BSN keyword nearby
  PHONE_NUMBER   Dutch mobile number (06 / +31 6)

The report NEVER contains the detected values: only counts per type, a local reference,
the file extension and project name. The mapping reference -> file path stays on this machine
in sent.jsonl / the queue, so the privacy officer can ask the reporter for details.

Credentials (per user, never in a repo):
  ~/.config/pii-filter/env        BRIDGE_PAT=bgp_...   (scope isms.datalek.melden)
                                  BRIDGE_API_BASE=https://bridge.bronzgreen.com   (optional)
  or environment variables PII_BRIDGE_PAT / PII_BRIDGE_API_BASE.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pii_config as pc

LEAK_DIR = pc.DATA_DIR / "leaks"
QUEUE_DIR = LEAK_DIR / "queue"
SENT_LOG = LEAK_DIR / "sent.jsonl"
STATE_FILE = LEAK_DIR / "seen.json"
ENV_FILE = Path(os.environ.get("PII_FILTER_ENV") or Path.home() / ".config" / "pii-filter" / "env")
DEFAULT_API = "https://bridge.bronzgreen.com"

TOKEN_RE = re.compile(r"<[A-Z][A-Z0-9_]*_\d+>")
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])")
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?)\b")
BSN_RE = re.compile(r"(?<![\d.])(\d{4}\.?\d{2}\.?\d{3})(?![\d.])")
BSN_CONTEXT = re.compile(r"(?i)\b(bsn|burgerservicenummer|sofi(?:nummer)?|persoonsnummer)\b")
MOBILE_RE = re.compile(r"(?<![\d+])(?:\+31|0031|0)[\s-]?6(?:[\s-]?\d){8}(?!\d)")
RESERVED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "example.nl", "voorbeeld.nl",
                          "test.nl", "test.com", "localhost", "invalid", "users.noreply.github.com",
                          "anthropic.com", "noreply.github.com")
LABELS = {"EMAIL_ADDRESS": "e-mailadres", "IBAN_CODE": "IBAN", "NL_BSN": "BSN",
          "PHONE_NUMBER": "telefoonnummer"}


# --------------------------------------------------------------------------- detection
def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    num = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(num) % 97 == 1


def _bsn_ok(raw: str) -> bool:
    d = re.sub(r"\D", "", raw)
    if len(d) != 9 or d == "000000000":
        return False
    return (sum(int(x) * w for x, w in zip(d[:8], range(9, 1, -1))) - int(d[8])) % 11 == 0


def detect(text: str, cfg: dict) -> dict:
    """Return {entity: set_of_value_hashes}. Values themselves are never kept."""
    lc = cfg.get("leak_check", {})
    ignore_domains = tuple(d.lower() for d in (*RESERVED_EMAIL_DOMAINS, *lc.get("ignore_email_domains", [])))
    allow = {a.lower() for a in cfg.get("allow_list", [])}
    text = TOKEN_RE.sub(" ", text)
    found: dict[str, set] = {}

    def add(kind, value):
        found.setdefault(kind, set()).add(hashlib.sha256(value.lower().encode()).hexdigest()[:12])

    for m in EMAIL_RE.finditer(text):
        dom = m.group(1).lower()
        if dom.endswith(ignore_domains) or m.group(0).lower() in allow:
            continue
        add("EMAIL_ADDRESS", m.group(0))
    for m in IBAN_RE.finditer(text):
        if _iban_ok(m.group(1)):
            add("IBAN_CODE", m.group(1).replace(" ", ""))
    for m in BSN_RE.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 20]
        if _bsn_ok(m.group(1)) and BSN_CONTEXT.search(window):
            add("NL_BSN", m.group(1))
    for m in MOBILE_RE.finditer(text):
        add("PHONE_NUMBER", re.sub(r"\D", "", m.group(0))[-9:])
    return found


# --------------------------------------------------------------------------- credentials
def credentials() -> tuple[str | None, str]:
    pat = os.environ.get("PII_BRIDGE_PAT")
    api = os.environ.get("PII_BRIDGE_API_BASE")
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            v = v.strip().strip('"').strip("'")
            if k == "BRIDGE_PAT" and not pat:
                pat = v
            elif k == "BRIDGE_API_BASE" and not api:
                api = v
    return (pat or None), (api or DEFAULT_API).rstrip("/")


# --------------------------------------------------------------------------- report
def _no_long_digits(s: str) -> str:
    """BRIDGE rejects free text with 8-9 digit runs (possible BSN); break any long digit run."""
    return re.sub(r"\d{6,}", lambda m: "-".join(m.group(0)[i:i + 4] for i in range(0, len(m.group(0)), 4)), s)


def build_report(found: dict, source: dict, note: str = "") -> dict:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    local_ref = secrets.token_hex(4)
    counts = {k: len(v) for k, v in found.items()}
    summary = ", ".join(f"{LABELS.get(k, k)} {n}x" for k, n in sorted(counts.items()))
    tool = source.get("tool", "?")
    ext = source.get("ext") or "onbekend"
    project = source.get("project") or "onbekend"
    automatic = source.get("automatic", True)
    how = ("De PII-filter-plugin heeft automatisch gedetecteerd" if automatic
           else "Een medewerker heeft via de PII-filter-plugin gemeld")
    body = {
        "referentie": f"DL-AI-{now:%Y-%m-%d-%H%M}-{local_ref}",
        "samenvatting": _no_long_digits(
            f"{how} dat persoonsgegevens zijn doorgegeven aan het AI-model in Claude Code "
            f"(Anthropic). Gedetecteerd: {summary or 'zie toelichting'}. "
            f"Bron: {tool} van een {ext}-bestand in project '{project}'."),
        "geconstateerd_op": now.isoformat().replace("+00:00", "Z"),
        "aard": ["vertrouwelijkheid"],
        "rol": "nog_te_bepalen",
        "ontdekt_door": "PII-filter Claude Code (automatisch)" if automatic else "Medewerker (PII-filter Claude Code)",
        "aantal_betrokkenen_schatting": max([0, *counts.values()]),
        "gevolgen": ("Persoonsgegevens zijn verwerkt door een externe AI-dienst (Anthropic, verwerker). "
                     "Er is geen aanwijzing voor verdere verspreiding."),
        "getroffen_maatregelen": ("Gedetecteerd en geregistreerd; gebruiker en AI-sessie zijn geïnformeerd. "
                                  "Te beoordelen: filterconfiguratie (.pii-filter.json) en werkwijze."),
        "toelichting": _no_long_digits(
            f"Lokale referentie {local_ref} op werkplek {socket.gethostname()} "
            f"(pad en details staan alleen lokaal in de PII-filter-meldingenlog). "
            f"Sessie {str(source.get('session_id', ''))[:8]}. "
            f"PII-filter versie {source.get('plugin_version', '?')}."
            + (f" Opmerking melder: {note}" if note else "")),
        "meldbeslissing": "nog_te_bepalen",
        "status": "open",
    }
    return {"local_ref": local_ref, "created": now.isoformat(), "source": source, "body": body}


# --------------------------------------------------------------------------- queue / send
def enqueue(report: dict) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    p = QUEUE_DIR / f"{report['created'][:19].replace(':', '')}-{report['local_ref']}.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _post(api: str, pat: str, body: dict, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{api}/api/v1/isms/datalekken", method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {pat}", "Content-Type": "application/json",
                 "Idempotency-Key": str(uuid.uuid5(uuid.NAMESPACE_URL, body["referentie"]))})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            detail = {}
        return e.code, detail


def flush(timeout: float = 8.0) -> dict:
    """Send every queued report. Returns {'sent': [...], 'pending': n, 'error': str|None}."""
    out = {"sent": [], "pending": 0, "error": None}
    files = sorted(QUEUE_DIR.glob("*.json")) if QUEUE_DIR.exists() else []
    if not files:
        return out
    pat, api = credentials()
    if not pat:
        out["pending"] = len(files)
        out["error"] = f"geen BRIDGE-token ({ENV_FILE})"
        return out
    for f in files:
        rep = json.loads(f.read_text(encoding="utf-8"))
        try:
            code, resp = _post(api, pat, rep["body"], timeout)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            out["error"] = f"BRIDGE onbereikbaar ({type(e).__name__})"
            break
        if code in (200, 201) or (code == 409 and "referentie" in json.dumps(resp).lower()):
            rec = {"local_ref": rep["local_ref"], "referentie": rep["body"]["referentie"],
                   "bridge_id": resp.get("id"), "termijn_uiterlijk": resp.get("termijn_uiterlijk"),
                   "sent": dt.datetime.now(dt.timezone.utc).isoformat(), "source": rep["source"]}
            SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(SENT_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.unlink()
            out["sent"].append(rec)
        else:
            hint = {401: "token verlopen of ingetrokken", 403: "token mist scope isms.datalek.melden"}.get(code, "")
            out["error"] = f"BRIDGE HTTP {code} {hint} {json.dumps(resp)[:200]}".strip()
            if code in (401, 403):
                break  # same for every report; keep them queued
    out["pending"] = len(list(QUEUE_DIR.glob("*.json")))
    return out


# --------------------------------------------------------------------------- dedupe
def seen_before(key: str) -> bool:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if key in state:
        return True
    state[key] = dt.datetime.now(dt.timezone.utc).isoformat()
    if len(state) > 2000:  # keep it small
        state = dict(sorted(state.items(), key=lambda kv: kv[1])[-1000:])
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    return False
