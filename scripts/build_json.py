#!/usr/bin/env python3
"""build_json.py — pre-bake YAML data files into JSON for fast browser parse.

JSON.parse runs ~10x faster than js-yaml on the 445KB conferences file; this
script writes data/conferences.json (+ publications.json, glossary.json)
alongside the YAML sources. The browser tries .json first and falls back to
.yaml so the site keeps working if someone forgets to re-run this script.

Run after editing any data/*.yaml file:
    python3 scripts/build_json.py
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("pip install pyyaml\n")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FILES = ["conferences", "publications", "glossary"]


def encoder(o):
    """yaml.safe_load returns datetime/date for ISO dates — JSON needs strings."""
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"{type(o).__name__} not serializable")


def main() -> int:
    for name in FILES:
        src = DATA / f"{name}.yaml"
        dst = DATA / f"{name}.json"
        if not src.exists():
            sys.stderr.write(f"skip {name}: {src} missing\n")
            continue
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        dst.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=encoder),
            encoding="utf-8",
        )
        sys.stderr.write(f"{name}: {src.stat().st_size:>7} YAML → {dst.stat().st_size:>7} JSON\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
