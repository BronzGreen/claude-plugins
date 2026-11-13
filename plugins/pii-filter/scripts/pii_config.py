"""Paths and layered config for pii-filter. Standard library only (runs under any Python 3.8+).

Config layers (later wins / extends):
  1. <plugin>/config.default.json          shipped with the plugin
  2. ~/.claude/pii-filter.json              personal additions
  3. <project>/.pii-filter.json             per-repo additions (commit it)

List keys (allow_list, hook.exclude_globs, hook.read_extensions, ...) are EXTENDED,
dict keys (column_hints) are MERGED, scalars are REPLACED.
When PII_FILTER_ENFORCED=1 (set by the organisation via managed settings), 'enabled: false'
and PII_FILTER=off are ignored.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
HOME_CLAUDE = Path.home() / ".claude"
DATA_DIR = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or HOME_CLAUDE / "pii-filter")
VENV_DIR = DATA_DIR / "venv"
READY_MARKER = DATA_DIR / "ready.json"
SETUP_LOG = DATA_DIR / "setup-log.txt"
VAULT_DIR = Path(os.environ.get("PII_VAULT_DIR") or HOME_CLAUDE / "pii-vault")
VAULT_PATH = VAULT_DIR / "vault.json"
CACHE_DIR = VAULT_DIR / "cache"
USER_CONFIG = HOME_CLAUDE / "pii-filter.json"
PROJECT_CONFIG_NAME = ".pii-filter.json"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def is_ready() -> bool:
    return READY_MARKER.exists() and venv_python().exists()


def cli_command() -> str:
    """The exact command line Claude should use for the CLI."""
    return f'"{venv_python()}" "{PLUGIN_ROOT / "scripts" / "pii.py"}"'


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif isinstance(v, list) and isinstance(out.get(k), list) and k != "entities":
            out[k] = out[k] + [x for x in v if x not in out[k]]
        else:
            out[k] = v
    return out


def find_project_config(start: str | os.PathLike | None) -> Path | None:
    if not start:
        return None
    p = Path(start).resolve()
    for d in [p, *p.parents]:
        cand = d / PROJECT_CONFIG_NAME
        if cand.is_file():
            return cand
        if (d / ".git").exists():
            break
    return None


def load_config(project_dir: str | os.PathLike | None = None) -> dict:
    with open(PLUGIN_ROOT / "config.default.json", encoding="utf-8") as f:
        cfg = json.load(f)
    for extra in (USER_CONFIG, find_project_config(project_dir)):
        if extra and extra.is_file():
            try:
                with open(extra, encoding="utf-8") as f:
                    cfg = _merge(cfg, json.load(f))
            except (OSError, ValueError) as e:
                print(f"pii-filter: config {extra} ongeldig ({e}), genegeerd", file=sys.stderr)
    return cfg


def enforced() -> bool:
    return os.environ.get("PII_FILTER_ENFORCED", "").lower() in ("1", "true", "yes")


def is_enabled(cfg: dict) -> bool:
    if enforced():
        return True
    if os.environ.get("PII_FILTER", "").lower() in ("off", "0", "false"):
        return False
    return bool(cfg.get("enabled", True))


def sanitized_path(src: Path, max_lines: int | None, cfg_fingerprint: str = "") -> Path:
    st = src.stat()
    key = f"{src.resolve()}|{st.st_mtime_ns}|{st.st_size}|{max_lines}|{cfg_fingerprint}"
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    return CACHE_DIR / f"{src.stem}.pii-sanitized.{h}{src.suffix}"


def config_fingerprint(cfg: dict) -> str:
    relevant = {k: cfg.get(k) for k in ("entities", "allow_list", "column_hints", "score_threshold",
                                        "default_language")}
    return hashlib.sha1(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:8]
