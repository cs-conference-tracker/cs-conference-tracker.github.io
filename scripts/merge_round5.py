#!/usr/bin/env python3
"""
merge_round5.py — merge round-5 agent outputs into data/conferences.yaml.

Reads YAML files from /tmp/round5/*.yaml (one per agent batch). For each
venue in those files, replaces the matching entry in data/conferences.yaml
by `id`. Also normalizes:
  - acceptance.rate: if value > 1.5, treat as percent → divide by 100
  - acceptance entries with all-null fields: dropped
  - location.lat / location.lng: replace None/~/null with 0.0 so the map
    doesn't crash (a "0,0 island" cluster is the chosen pathology)

Usage: python3 scripts/merge_round5.py
Validates after merge — exits non-zero if validate.py reports errors.
"""
from __future__ import annotations
import glob
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("pip install pyyaml\n")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "conferences.yaml"
UPDATES_DIR = Path("/tmp/round5")


def normalize_rate(v):
    """Percent (e.g. 22.5) or decimal (0.225) both end up as decimal 0..1."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:   # NaN
        return None
    return f / 100.0 if f > 1.5 else f


def normalize_acceptance(entries):
    if not entries:
        return []
    out = []
    for e in entries:
        if not isinstance(e, dict) or not e.get("year"):
            continue
        cleaned = {"year": int(e["year"])}
        if e.get("submitted") not in (None, "~"):
            try:
                cleaned["submitted"] = int(e["submitted"])
            except (TypeError, ValueError):
                pass
        if e.get("accepted") not in (None, "~"):
            try:
                cleaned["accepted"] = int(e["accepted"])
            except (TypeError, ValueError):
                pass
        rate = normalize_rate(e.get("rate"))
        if rate is None and "submitted" in cleaned and "accepted" in cleaned and cleaned["submitted"]:
            rate = cleaned["accepted"] / cleaned["submitted"]
        if rate is not None:
            cleaned["rate"] = round(rate, 4)
        if e.get("track"):
            cleaned["track"] = e["track"]
        # Only keep entries with at least one numeric stat
        if "rate" in cleaned or "submitted" in cleaned or "accepted" in cleaned:
            out.append(cleaned)
    # Sort newest-first for predictable display
    out.sort(key=lambda x: -x["year"])
    return out


def normalize_location(loc):
    if not isinstance(loc, dict):
        return loc
    if loc.get("lat") in (None, "~"):
        loc["lat"] = 0.0
    if loc.get("lng") in (None, "~"):
        loc["lng"] = 0.0
    if loc.get("city") in (None, "~"):
        loc["city"] = "TBD"
    if loc.get("country") in (None, "~"):
        loc["country"] = "TBD"
    return loc


FIELD_RENAMES = {"short": "acronym", "url": "website", "tags": "topics"}


def normalize_venue(v):
    """Normalize fields on a venue dict before merging."""
    for old, new in FIELD_RENAMES.items():
        if old in v and new not in v:
            v[new] = v.pop(old)
        elif old in v:
            del v[old]
    if "acceptance" in v:
        v["acceptance"] = normalize_acceptance(v["acceptance"])
        if not v["acceptance"]:
            del v["acceptance"]
    if "location" in v:
        v["location"] = normalize_location(v["location"])
    return v


def load_updates():
    """Return list of update dicts, parsed from all /tmp/round5/*.yaml files."""
    updates = []
    for path in sorted(glob.glob(str(UPDATES_DIR / "*.yaml"))):
        try:
            data = yaml.safe_load(open(path, encoding="utf-8"))
        except yaml.YAMLError as e:
            sys.stderr.write(f"YAML parse failure in {path}: {e}\n")
            continue
        if not isinstance(data, list):
            sys.stderr.write(f"WARN {path}: top-level is not a list, skipping\n")
            continue
        sys.stderr.write(f"loaded {len(data):3d} entries from {path}\n")
        updates.extend(data)
    return updates


def main():
    existing = yaml.safe_load(open(DATA, encoding="utf-8")) or []
    updates = load_updates()
    if not updates:
        sys.stderr.write("No updates loaded; nothing to do.\n")
        return 1

    by_id = {c["id"]: c for c in existing if isinstance(c, dict) and "id" in c}
    n_replaced, n_added = 0, 0
    for u in updates:
        if not isinstance(u, dict) or "id" not in u:
            sys.stderr.write(f"WARN update missing id: {u}\n")
            continue
        normalize_venue(u)
        if u["id"] in by_id:
            by_id[u["id"]] = u
            n_replaced += 1
        else:
            by_id[u["id"]] = u
            n_added += 1

    # Preserve original ordering: keep existing IDs in their original positions;
    # any new IDs (none expected here) get appended.
    out = []
    seen = set()
    for c in existing:
        if isinstance(c, dict) and c.get("id") in by_id:
            out.append(by_id[c["id"]])
            seen.add(c["id"])
    for vid, v in by_id.items():
        if vid not in seen:
            out.append(v)

    yaml.dump(out, open(DATA, "w", encoding="utf-8"),
              sort_keys=False, allow_unicode=True, width=200)
    sys.stderr.write(f"\n{n_replaced} venues updated, {n_added} added, {len(out)} total.\n")

    # Rebuild data/*.json so the browser keeps loading the fast path
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_json.py")])

    # Validate
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate.py")],
        capture_output=True, text=True,
    )
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
