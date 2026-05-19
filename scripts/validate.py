#!/usr/bin/env python3
"""
validate.py — sanity-check the three YAML data files.

Run before deploying. Exits non-zero if structural errors are found.
Style warnings (unknown topic keys, missing optional fields) are non-fatal
but printed to stderr so maintainers can clean them up.

Usage:
    python scripts/validate.py
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("Install: pip install pyyaml\n")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

REQUIRED_CONF_FIELDS = {"id", "name", "acronym", "year", "website", "topics", "tracks", "location"}
# Optional fields that the validator should silently accept:
OPTIONAL_CONF_FIELDS = {"description", "dates", "rankings", "acceptance"}
REQUIRED_LOC_FIELDS = {"city", "country", "lat", "lng"}
REQUIRED_PUB_FIELDS = {"id", "title", "authors", "year", "location", "type"}
VALID_PUB_TYPES = {"full_paper", "workshop", "demo", "poster", "journal", "short_paper"}
VALID_DEADLINE_KINDS = {
    "abstract", "paper", "rebuttal_start", "rebuttal_end",
    "notification", "camera_ready", "proposal", "commitment",
}

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def parse_iso(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    # Date-only treated as 23:59:59 AoE
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s = s + "T23:59:59-12:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def load(path: Path):
    if not path.exists():
        err(f"missing file: {path}")
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        err(f"YAML parse failure in {path.name}: {e}")
        return None


def validate_glossary(g) -> set[str]:
    if not isinstance(g, dict):
        err("glossary.yaml must be a mapping")
        return set()
    for k in ("topics", "rankings", "deadline_kinds"):
        if k not in g:
            err(f"glossary.yaml missing top-level key: {k}")
    return set((g.get("topics") or {}).keys())


def validate_conferences(confs, known_topics: set[str]) -> None:
    if not isinstance(confs, list):
        err("conferences.yaml must be a list")
        return
    seen_ids: set[str] = set()
    for i, c in enumerate(confs):
        prefix = f"conferences[{i}]"
        if not isinstance(c, dict):
            err(f"{prefix} is not a mapping")
            continue
        missing = REQUIRED_CONF_FIELDS - set(c.keys())
        if missing:
            err(f"{prefix} missing: {sorted(missing)}")
        cid = c.get("id") or prefix
        if cid in seen_ids:
            err(f"{prefix} duplicate id: {cid}")
        seen_ids.add(cid)

        loc = c.get("location") or {}
        missing_loc = REQUIRED_LOC_FIELDS - set(loc.keys())
        if missing_loc:
            err(f"{cid} location missing: {sorted(missing_loc)}")

        for t in (c.get("topics") or []):
            if t not in known_topics:
                warn(f"{cid} unknown topic key: {t!r}")

        for ti, track in enumerate(c.get("tracks") or []):
            tprefix = f"{cid}.tracks[{ti}]"
            if not isinstance(track, dict) or "name" not in track:
                err(f"{tprefix} missing 'name'")
                continue
            for ri, rnd in enumerate(track.get("rounds") or []):
                rprefix = f"{tprefix}.rounds[{ri}]"
                dls = rnd.get("deadlines") or {}
                if not isinstance(dls, dict):
                    err(f"{rprefix} 'deadlines' must be a mapping")
                    continue
                for kind, value in dls.items():
                    if kind not in VALID_DEADLINE_KINDS:
                        warn(f"{rprefix} unknown deadline kind: {kind!r}")
                    parsed = parse_iso(value)
                    if parsed is None:
                        err(f"{rprefix}.{kind} invalid ISO datetime: {value!r}")


def validate_publications(pubs) -> None:
    if not isinstance(pubs, list):
        err("publications.yaml must be a list")
        return
    seen_ids: set[str] = set()
    for i, p in enumerate(pubs):
        prefix = f"publications[{i}]"
        if not isinstance(p, dict):
            err(f"{prefix} not a mapping")
            continue
        missing = REQUIRED_PUB_FIELDS - set(p.keys())
        if missing:
            err(f"{prefix} missing: {sorted(missing)}")
        pid = p.get("id") or prefix
        if pid in seen_ids:
            err(f"{prefix} duplicate id: {pid}")
        seen_ids.add(pid)

        ptype = p.get("type")
        if ptype and ptype not in VALID_PUB_TYPES:
            warn(f"{pid} unknown type: {ptype!r} (valid: {sorted(VALID_PUB_TYPES)})")

        loc = p.get("location") or {}
        missing_loc = REQUIRED_LOC_FIELDS - set(loc.keys())
        if missing_loc:
            err(f"{pid} location missing: {sorted(missing_loc)}")
        if loc.get("city") == "TBD":
            warn(f"{pid} has TBD location — needs human follow-up")


def main() -> int:
    glossary = load(DATA / "glossary.yaml")
    confs = load(DATA / "conferences.yaml")
    pubs = load(DATA / "publications.yaml")

    known_topics: set[str] = set()
    if glossary is not None:
        known_topics = validate_glossary(glossary)
    if confs is not None:
        validate_conferences(confs, known_topics)
    if pubs is not None:
        validate_publications(pubs)

    for w in warnings:
        print(f"warn: {w}", file=sys.stderr)
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
