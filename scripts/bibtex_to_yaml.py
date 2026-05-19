#!/usr/bin/env python3
"""
bibtex_to_yaml.py — convert BibTeX entries to publications.yaml entries.

Usage:
    python scripts/bibtex_to_yaml.py < new.bib >> data/publications.yaml
    python scripts/bibtex_to_yaml.py new.bib >> data/publications.yaml

The script:
  - Parses BibTeX from stdin or first arg
  - Maps verbose booktitle/journal strings to short venue acronyms via VENUE_MAP
  - Looks up the (venue, year) tuple in data/conferences.yaml to auto-fill
    location lat/lng — useful when the paper was presented at a conference
    already in the tracker. Otherwise emits `city: TBD` for human follow-up.
  - Emits YAML to stdout. Review before appending to publications.yaml.

Dependencies: bibtexparser, pyyaml
    pip install bibtexparser pyyaml
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

try:
    import bibtexparser
    import yaml
except ImportError:
    sys.stderr.write("Install dependencies: pip install bibtexparser pyyaml\n")
    sys.exit(1)


# Lab can extend this table as new venues appear. The script falls back to
# using the raw booktitle when there's no match.
VENUE_MAP: dict[str, str] = {
    "Proceedings of the SIGCHI Conference on Human Factors in Computing Systems": "CHI",
    "Proceedings of the ACM SIGCHI Conference on Human Factors in Computing Systems": "CHI",
    "CHI Conference on Human Factors in Computing Systems": "CHI",
    "Proceedings of the ACM Symposium on User Interface Software and Technology": "UIST",
    "Proceedings of the 36th Annual ACM Symposium on User Interface Software and Technology": "UIST",
    "Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous Technologies": "UbiComp/IMWUT",
    "PACM IMWUT": "UbiComp/IMWUT",
    "Proceedings of the ACM SIGSPATIAL International Conference on Advances in Geographic Information Systems": "SIGSPATIAL",
    "Proceedings of the 31st ACM SIGSPATIAL International Conference on Advances in Geographic Information Systems": "SIGSPATIAL",
    "IEEE INFOCOM": "INFOCOM",
    "Proceedings of IEEE INFOCOM": "INFOCOM",
    "ACM International Conference on Mobile Computing and Networking": "MobiCom",
    "Proceedings of the ACM International Conference on Mobile Computing and Networking": "MobiCom",
    "ACM Conference on Embedded Networked Sensor Systems": "SenSys",
    "Proceedings of the ACM Conference on Embedded Networked Sensor Systems": "SenSys",
    "IEEE International Conference on Pervasive Computing and Communications": "PerCom",
    "ACM/IEEE International Conference on Internet of Things Design and Implementation": "IoTDI",
    "IEEE Conference on Virtual Reality and 3D User Interfaces": "IEEE VR",
    "IEEE Virtual Reality": "IEEE VR",
}

# `type` defaults; can be inferred from BibTeX entry type or content keywords.
ENTRY_TYPE_MAP = {
    "inproceedings": "full_paper",
    "article": "journal",
    "incollection": "full_paper",
    "misc": "short_paper",
    "techreport": "short_paper",
}


def slugify(s: str, max_words: int | None = None, max_len: int = 60) -> str:
    words = re.findall(r"[A-Za-z0-9]+", (s or "").lower())
    if max_words is not None:
        words = words[:max_words]
    out = "-".join(words)
    return out[:max_len].rstrip("-")


def clean_braces(s: str) -> str:
    return re.sub(r"[{}]", "", (s or "")).strip()


def parse_authors(author_str: str) -> list[str]:
    """Convert BibTeX `Last, First and Last, First` to display strings."""
    if not author_str:
        return []
    parts = [a.strip() for a in author_str.split(" and ")]
    out = []
    for p in parts:
        p = clean_braces(p)
        if "," in p:
            last, first = (s.strip() for s in p.split(",", 1))
            initials = "".join(w[0] + "." for w in first.split() if w)
            out.append(f"{initials} {last}".strip())
        else:
            # Already "First Last" → keep but reduce given names to initials
            tokens = p.split()
            if len(tokens) >= 2:
                last = tokens[-1]
                initials = "".join(w[0] + "." for w in tokens[:-1] if w)
                out.append(f"{initials} {last}")
            else:
                out.append(p)
    return out


def load_conferences(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for c in raw:
        acronym = c.get("acronym")
        year = c.get("year")
        if acronym is not None and year is not None:
            out[(acronym, int(year))] = c.get("location", {}) or {}
    return out


def infer_venue(entry: dict[str, str]) -> str:
    raw = clean_braces(entry.get("booktitle") or entry.get("journal") or "")
    return VENUE_MAP.get(raw, raw)


def infer_type(entry: dict[str, str]) -> str:
    etype = entry.get("ENTRYTYPE", "").lower()
    base = ENTRY_TYPE_MAP.get(etype, "full_paper")
    # Heuristics for posters/demos/workshops based on title keywords
    title = (entry.get("title") or "").lower()
    if "poster" in title:
        return "poster"
    if "demo" in title or "demonstration" in title:
        return "demo"
    if "workshop" in title:
        return "workshop"
    return base


def convert(bib_text: str, confs: dict[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    db = bibtexparser.loads(bib_text)
    results: list[dict[str, Any]] = []
    for e in db.entries:
        title = clean_braces(e.get("title", "")).strip()
        year_str = e.get("year", "").strip()
        try:
            year = int(year_str)
        except (TypeError, ValueError):
            sys.stderr.write(f"[skip] no/invalid year for: {title!r}\n")
            continue

        venue = infer_venue(e)
        location = confs.get((venue, year), {
            "city": "TBD", "country": "TBD", "lat": 0.0, "lng": 0.0,
        })

        item: dict[str, Any] = {
            "id": f"pub-{year}-{slugify(venue, max_len=20)}-{slugify(title, max_words=4)}",
            "title": title,
            "authors": parse_authors(e.get("author", "")),
            "venue": venue,
            "year": year,
            "location": location,
            "type": infer_type(e),
        }
        if e.get("journal") and not e.get("booktitle"):
            item["venue_full"] = clean_braces(e["journal"])
        elif e.get("booktitle"):
            item["venue_full"] = clean_braces(e["booktitle"])
        if e.get("doi"):
            doi = clean_braces(e["doi"]).strip()
            item["doi"] = doi
            item["url"] = e.get("url") or f"https://doi.org/{doi}"
        elif e.get("url"):
            item["url"] = clean_braces(e["url"])
        results.append(item)
    return results


def main() -> int:
    if len(sys.argv) > 1:
        bib_text = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        bib_text = sys.stdin.read()

    project_root = Path(__file__).resolve().parent.parent
    confs = load_conferences(project_root / "data" / "conferences.yaml")
    if not confs:
        sys.stderr.write("Warning: data/conferences.yaml not found or empty — locations will be TBD\n")

    entries = convert(bib_text, confs)
    if not entries:
        sys.stderr.write("No entries produced.\n")
        return 1

    yaml.dump(entries, sys.stdout, sort_keys=False, allow_unicode=True, width=120)
    sys.stderr.write(f"\n[done] {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} emitted. Review TBD locations before committing.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
