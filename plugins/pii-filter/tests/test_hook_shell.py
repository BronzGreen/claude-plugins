"""Shell-viewer detection must block raw views of data files but not normal dev commands.

Run: python tests/test_hook_shell.py   (stdlib only)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pii_config as pc  # noqa: E402
import pii_hook as h  # noqa: E402

CASES = {
    # blocked: shows data
    "head -5 data/klanten.csv": True,
    "cat export.CSV | wc -l": True,
    "Import-Csv .\\klanten.csv | Select -First 3": True,
    "Get-Content C:\\data\\export.xlsx": True,
    "tail -f logs/app.log": True,
    "jq '.[0]' < users.jsonl": True,
    "grep -i jansen ./dump.sql": True,
    "sed -n '1,20p' mails/inbox.eml": True,
    "type .\\export\\leden.tsv": True,
    # allowed: normal development
    "sed -i 's#a.log#b.log#' build.sh": False,
    "echo 'data.csv' > list.txt": False,
    "python scripts/import.py --input klanten.csv": False,
    "go test ./... && cat README.md": False,
    "git add data/klanten.csv && git commit -m x": False,
    "wc -l klanten.csv": False,
    "grep -r TODO src --include=*.ts": False,
    "cat package.json": False,
    "npm run build 2>&1 | tail -20": False,
}


def main() -> int:
    cfg = pc.load_config(ROOT)
    bad = 0
    for cmd, want in CASES.items():
        got = h.shows_data_file(cmd, cfg)
        if got != want:
            bad += 1
            print(f"FOUT  verwacht={want}  {cmd}")
    print(f"{len(CASES) - bad}/{len(CASES)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
