#!/usr/bin/env python3
"""sync_ccfddl.py — overlay date / place / paper-deadline ground truth
from the community-maintained ccfddl/ccf-deadlines repo onto our
conferences.yaml.

ccfddl is the de-facto canonical source for CCF-ranked conference dates
and submission deadlines (one file per series, updated by per-conference
maintainers). Our database has more dimensions (multilingual descriptions,
acceptance stats, per-track granularity, coords) so we *overlay* rather
than replace: ccfddl wins on conference dates/location/paper deadline,
we keep everything else (notification / camera-ready / rebuttal /
acceptance / description / topics / coords / extra tracks).

Usage:
    # First clone the repo:  git clone --depth 1 https://github.com/ccfddl/ccf-deadlines.git /tmp/ccf-deadlines
    python3 scripts/sync_ccfddl.py [--dry-run]

Reports per-venue: matched ✓, unmatched —, and the field(s) updated.
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("pip install pyyaml\n")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
CCFDDL_ROOT = Path("/tmp/ccf-deadlines")
DATA = ROOT / "data" / "conferences.yaml"

# ---------------------------------------------------------------------------
# Acronym normalization. ccfddl titles are typically the canonical short
# form (CCS, AAAI, SIGCOMM). We strip non-alphanum + lowercase, plus a
# few hand-mapped aliases for cases where the two databases call the
# same conference different things.
# ---------------------------------------------------------------------------
ALIAS_TO_CCFDDL = {
    # our acronym → ccfddl title
    "thewebconf":    "www",
    "webconf":       "www",
    "ijcai-ecai":    "ijcai",
    "ecml-pkdd":     "ecmlpkdd",
    "ecml pkdd":     "ecmlpkdd",
    "kdd":           "sigkdd",
    "siggraphasia":  "siggraphasia",   # not in ccfddl but kept for completeness
    "imwut/ubicomp": "ubicompiswc",
    "imwut":         "ubicompiswc",
    "ubicomp":       "ubicompiswc",
    "iswc":          "ubicompiswc",   # ccfddl has joint UbiComp/ISWC entry
    "ieeesp":        "sp",
    "ieee s&p":      "sp",
    "ieee-s&p":      "sp",
    "ieee s p":      "sp",
    "ieee sp":       "sp",
    "usenixsec":     "usenixsecurity",
    "usenix security": "usenixsecurity",
    "usenix sec":    "usenixsecurity",
    "atc":           "usenixatc",
    "tronsymposium": None,   # not CCF-ranked; explicit skip
    "vtc":           None,   # ccfddl has vtcspring/vtcfall but we use composite ids
    "ihmmsec":       "ihmmsec",
    "csf":           "csfw",
    "ieeevr":        "vr",
}


def norm(s: str) -> str:
    """Normalize an acronym for index lookup."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# ---------------------------------------------------------------------------
# Date parser. ccfddl date strings come in many shapes — these patterns
# cover the variations seen in the repo.
# ---------------------------------------------------------------------------
MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _month(name: str) -> int | None:
    return MONTH_NAMES.get(name.lower().strip("."))


def parse_date_string(s: str) -> tuple[str, str] | None:
    """Returns (start_iso, end_iso) or None if unparseable.

    Handles: "November 9-13, 2020", "April 06 - April 10, 2025",
    "Mar 12-16, 2021", "29 June - 2 July, 2026", "April 13 - 17, 2026",
    "December 26, 2021 - January 1, 2022", "April 12-13, 2026", etc.
    """
    if not s or s.upper() in ("TBD", "TBA"):
        return None
    s = s.strip()

    # cross-year cross-month: "December 26, 2021 - January 1, 2022"
    m = re.match(
        r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\s*[-–]\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})",
        s,
    )
    if m:
        m1, d1, y1, m2, d2, y2 = m.groups()
        if _month(m1) and _month(m2):
            return (f"{int(y1):04d}-{_month(m1):02d}-{int(d1):02d}",
                    f"{int(y2):04d}-{_month(m2):02d}-{int(d2):02d}")

    # cross-month same year: "April 06 - April 10, 2025"
    m = re.match(
        r"([A-Za-z]+)\s+(\d{1,2})\s*[-–]\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})",
        s,
    )
    if m:
        m1, d1, m2, d2, y = m.groups()
        if _month(m1) and _month(m2):
            return (f"{int(y):04d}-{_month(m1):02d}-{int(d1):02d}",
                    f"{int(y):04d}-{_month(m2):02d}-{int(d2):02d}")

    # Day-first: "29 June - 2 July, 2026"
    m = re.match(
        r"(\d{1,2})\s+([A-Za-z]+)\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})",
        s,
    )
    if m:
        d1, m1, d2, m2, y = m.groups()
        if _month(m1) and _month(m2):
            return (f"{int(y):04d}-{_month(m1):02d}-{int(d1):02d}",
                    f"{int(y):04d}-{_month(m2):02d}-{int(d2):02d}")

    # Day-range same month: "April 13 - 17, 2026"  /  "November 9-13, 2020"  /  "April 12-13, 2026"
    m = re.match(
        r"([A-Za-z]+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s+(\d{4})",
        s,
    )
    if m:
        mo, d1, d2, y = m.groups()
        if _month(mo):
            return (f"{int(y):04d}-{_month(mo):02d}-{int(d1):02d}",
                    f"{int(y):04d}-{_month(mo):02d}-{int(d2):02d}")

    # Single day: "April 6, 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        mo, d, y = m.groups()
        if _month(mo):
            iso = f"{int(y):04d}-{_month(mo):02d}-{int(d):02d}"
            return (iso, iso)

    return None


# ---------------------------------------------------------------------------
# Place parser. ccfddl format: "<venue/city>, [<state/region>,] <country>".
# We collapse to {city, country} keeping the city as the first token before
# the country and normalizing common variants.
# ---------------------------------------------------------------------------
COUNTRY_ALIAS = {
    "u.s.a": "USA", "u.s.a.": "USA", "us": "USA", "u.s.": "USA", "usa": "USA",
    "uk": "UK", "u.k.": "UK", "u.k": "UK", "united kingdom": "UK",
    "p.r. china": "China", "p.r.china": "China", "prc": "China",
}


def parse_place(s: str) -> tuple[str | None, str | None]:
    if not s or s.upper() in ("TBD", "TBA"):
        return None, None
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        return None, None
    country_raw = parts[-1]
    country = COUNTRY_ALIAS.get(country_raw.lower().strip("."), country_raw)
    if len(parts) == 1:
        return parts[0], country
    # City is the part before the country; if there are >=3 segments, the
    # second-to-last is usually a state ("Los Angeles, California, USA"),
    # so we drop it and keep the first segment as the venue city.
    return parts[0], country


# ---------------------------------------------------------------------------
# Timezone mapper.
# ---------------------------------------------------------------------------
def tz_to_offset(tz: str) -> str:
    if not tz:
        return "-12:00"
    if tz.upper() == "AOE":
        return "-12:00"
    m = re.match(r"UTC([+-])(\d{1,2})", tz.upper())
    if m:
        sign, hours = m.groups()
        return f"{sign}{int(hours):02d}:00"
    if tz.upper() in ("UTC", "UTC+0"):
        return "+00:00"
    return "-12:00"


def fmt_deadline(deadline_str: str, tz: str) -> str | None:
    """ccfddl deadline = 'YYYY-MM-DD HH:MM:SS' (or TBD). Returns ISO with offset."""
    if not deadline_str or deadline_str.upper() == "TBD":
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", deadline_str)
    if not m:
        return None
    date, time = m.groups()
    return f"{date}T{time}{tz_to_offset(tz)}"


# ---------------------------------------------------------------------------
# Build the ccfddl index.
# ---------------------------------------------------------------------------
def load_ccfddl_index() -> dict[str, dict]:
    """Returns {normalized_acronym: ccfddl_series_dict}."""
    idx: dict[str, dict] = {}
    if not CCFDDL_ROOT.exists():
        sys.stderr.write(
            f"[sync] {CCFDDL_ROOT} not found. Clone first:\n"
            f"    git clone --depth 1 https://github.com/ccfddl/ccf-deadlines.git {CCFDDL_ROOT}\n"
        )
        sys.exit(1)
    for p in sorted(CCFDDL_ROOT.glob("conference/*/*.yml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            sys.stderr.write(f"[sync] skipping {p}: {e}\n")
            continue
        if not isinstance(data, list):
            continue
        for series in data:
            if not isinstance(series, dict):
                continue
            for key in (series.get("title", ""), series.get("dblp", "")):
                if key:
                    idx[norm(key)] = series
    return idx


def lookup(idx: dict[str, dict], acronym: str) -> dict | None:
    """Find a ccfddl series by our acronym, applying aliases."""
    key = norm(acronym)
    if key in ALIAS_TO_CCFDDL:
        mapped = ALIAS_TO_CCFDDL[key]
        if mapped is None:
            return None
        key = norm(mapped)
    return idx.get(key)


# ---------------------------------------------------------------------------
# Overlay logic.
# ---------------------------------------------------------------------------
def overlay(our_conf: dict, ccfddl_series: dict) -> list[str]:
    """Mutates our_conf in place. Returns a list of field-change strings
    for the report ('dates', 'location.city', 'tracks[0].rounds[0].paper',
    etc.)."""
    changes: list[str] = []
    year = our_conf.get("year")
    edition = next(
        (c for c in (ccfddl_series.get("confs") or []) if c.get("year") == year),
        None,
    )
    if not edition:
        return changes

    # Website
    new_url = edition.get("link")
    if new_url and our_conf.get("website") != new_url:
        our_conf["website"] = new_url
        changes.append("website")

    # Dates
    date_text = edition.get("date") or ""
    parsed = parse_date_string(date_text)
    if parsed:
        s, e = parsed
        cur = our_conf.get("dates") or {}
        if cur.get("start") != s or cur.get("end") != e:
            our_conf["dates"] = {"start": s, "end": e}
            changes.append("dates")

    # Location — overlay city/country, preserve coords if we have them.
    city, country = parse_place(edition.get("place") or "")
    if city or country:
        loc = our_conf.setdefault("location", {})
        if city and loc.get("city") != city:
            loc["city"] = city
            changes.append("location.city")
        if country and loc.get("country") != country:
            loc["country"] = country
            changes.append("location.country")
        loc.setdefault("lat", 0.0)
        loc.setdefault("lng", 0.0)

    # Timeline → tracks[0].rounds. Only the FIRST track is touched;
    # ccfddl's data is series-level so it really only describes the main
    # research track. Multi-cycle venues map one ccfddl timeline entry
    # per round in order.
    timeline = edition.get("timeline") or []
    tz = edition.get("timezone") or "AoE"
    tracks = our_conf.get("tracks") or []
    if timeline and tracks:
        main = tracks[0]
        rounds = main.setdefault("rounds", [])
        # Ensure there's a round per timeline entry (preserve existing
        # rounds, append empty ones for cycles we don't have yet).
        while len(rounds) < len(timeline):
            label = timeline[len(rounds)].get("comment") or f"Cycle {len(rounds)+1}"
            rounds.append({"round": label, "deadlines": {}})
        for i, tline in enumerate(timeline):
            r = rounds[i]
            dls = r.setdefault("deadlines", {})
            new_paper = fmt_deadline(tline.get("deadline", ""), tz)
            if new_paper and dls.get("paper") != new_paper:
                dls["paper"] = new_paper
                changes.append(f"tracks[0].rounds[{i}].paper")
            new_abs = fmt_deadline(tline.get("abstract_deadline", ""), tz)
            if new_abs and dls.get("abstract") != new_abs:
                dls["abstract"] = new_abs
                changes.append(f"tracks[0].rounds[{i}].abstract")
            # Comment as the round label if we have nothing useful.
            comment = tline.get("comment")
            if comment and not r.get("round"):
                r["round"] = comment

    return changes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    idx = load_ccfddl_index()
    sys.stderr.write(f"[sync] loaded {len(idx)} ccfddl series\n")

    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    matched = 0
    unmatched: list[str] = []
    changes_per_id: dict[str, list[str]] = {}

    for c in data:
        if not isinstance(c, dict) or "acronym" not in c:
            continue
        ser = lookup(idx, c["acronym"])
        if not ser:
            unmatched.append(c["id"])
            continue
        matched += 1
        ch = overlay(c, ser)
        if ch:
            changes_per_id[c["id"]] = ch

    sys.stderr.write(
        f"[sync] matched {matched}/{len(data)} venues; "
        f"{len(changes_per_id)} had at least one field updated; "
        f"{len(unmatched)} unmatched\n"
    )

    if not args.dry_run:
        DATA.write_text(
            yaml.dump(data, sort_keys=False, allow_unicode=True, width=200),
            encoding="utf-8",
        )
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_json.py")])
        subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py")])

    # Print a concise per-venue change report.
    print("\n=== changes ===")
    for vid, fields in sorted(changes_per_id.items()):
        print(f"  {vid}: {', '.join(sorted(set(f.split('.', 1)[0] for f in fields)))}")
    print(f"\n=== unmatched ({len(unmatched)}) ===")
    print("  " + ", ".join(unmatched[:40]) + (" …" if len(unmatched) > 40 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
