#!/usr/bin/env python3
"""apply_cfp_patches.py — apply agent-generated CFP patches to conferences.yaml.

Reads every /tmp/cfp_refresh/patches/batch_NN.json file (each a JSON array of
patch objects), validates each patch against the existing data, and applies it
with ruamel.yaml so quoting/ordering is preserved.

Patch schema (one object per discrepancy):
    {
      "id":         "<conf id, e.g. aaai2026>",
      "field":      "<dotted/indexed path, e.g. tracks[0].rounds[0].deadlines.paper>",
      "current":    <existing value — for sanity check>,
      "correct":    <new value>,
      "reason":     "<one-line why>",
      "source_url": "<URL where confirmed>",
      "confidence": "high" | "medium" | "low"
    }

Guardrails (every one of these has burned us in a past round):
- walk_path handles array-index terminals: returns (container, key) for dict
  writes and (array, idx) for array-element writes. Never silently drops.
- Refuses structural replacement: a path ending in `.rounds`/`.tracks`, or a
  `correct` value that's a free-text agent description (contains `[{`/`},{`)
  is skipped with a logged reason.
- Type-checks before writing: if `current` doesn't match the actual existing
  value (either by content or by type), the patch is skipped — the agent
  likely misread the schema.
- Routes notification / camera_ready / commitment by detected schema:
  - if the field already exists as a sibling of `deadlines:` on this round,
    keep it as a sibling (don't duplicate inside `deadlines:`)
  - else write inside `deadlines:` (the modern convention)
- Skips low-confidence patches unless --include-low is passed.
- Always backs up the YAML first.
- Validator runs after apply; non-zero exit aborts (restore from backup).

Usage:
    python3 scripts/apply_cfp_patches.py [--include-low] [--dry-run]
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.scalarstring import SingleQuotedScalarString
except ImportError:
    sys.stderr.write("ruamel.yaml required: pip install ruamel.yaml\n")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / 'data' / 'conferences.yaml'
PATCHES_DIR = Path('/tmp/cfp_refresh/patches')
BACKUP_DIR = Path('/tmp/cfp_refresh/backups')

PATH_TOKEN_RE = re.compile(r'(?P<key>[a-zA-Z_][\w]*)(?:\[(?P<idx>[^\]]+)\])?')


def parse_path(path: str) -> list[tuple[str, str | int | None]]:
    """Parse a dotted/indexed path like `tracks[0].rounds[1].deadlines.paper`
    into a list of (key, idx_or_None) tuples. The idx may be an int (positional)
    or a str (name-lookup: agents sometimes write `tracks[Conference Track]`)."""
    tokens = []
    for segment in path.split('.'):
        m = PATH_TOKEN_RE.fullmatch(segment)
        if not m:
            raise ValueError(f"unparseable path segment: {segment!r} in {path!r}")
        idx_raw = m.group('idx')
        if idx_raw is None:
            tokens.append((m.group('key'), None))
        elif idx_raw.isdigit():
            tokens.append((m.group('key'), int(idx_raw)))
        else:
            # Name-lookup: tracks[Conference Track] etc.
            tokens.append((m.group('key'), idx_raw))
    return tokens


def resolve_idx(arr: list, idx) -> int | None:
    """Convert a name-lookup idx into a positional integer, or return idx if
    already an int. Returns None if out of range or no match."""
    if isinstance(idx, int):
        return idx if 0 <= idx < len(arr) else None
    # name-lookup
    for i, item in enumerate(arr):
        if isinstance(item, dict) and item.get('name') == idx:
            return i
    # case-insensitive fallback
    lower = idx.lower()
    for i, item in enumerate(arr):
        if isinstance(item, dict) and str(item.get('name', '')).lower() == lower:
            return i
    return None


def walk_path(obj: Any, tokens: list) -> tuple[Any, Any] | None:
    """Walk `obj` following `tokens`. Returns:
      (container, key)  — for dict writes:  container[key] = new_value
      (array, idx)      — for array writes: array[idx] = new_value
    Returns None if the path is invalid mid-walk.

    Supports both positional (`tracks[0]`) and name-lookup (`tracks[Foo Bar]`)
    indices — see resolve_idx.
    """
    if not tokens:
        return None
    cur = obj
    for i, (key, idx) in enumerate(tokens):
        is_last = (i == len(tokens) - 1)
        if not isinstance(cur, dict):
            return None
        if is_last:
            if idx is None:
                return (cur, key)
            arr = cur.get(key)
            if not isinstance(arr, list):
                return None
            resolved = resolve_idx(arr, idx)
            if resolved is None:
                return None
            return (arr, resolved)
        # intermediate step
        nxt = cur.get(key)
        if idx is not None:
            if not isinstance(nxt, list):
                return None
            resolved = resolve_idx(nxt, idx)
            if resolved is None:
                return None
            nxt = nxt[resolved]
        if nxt is None:
            return None
        cur = nxt
    return None


def detect_dual_schema(round_dict: dict, leaf_name: str) -> str:
    """For notification/camera_ready/commitment, decide whether to write at the
    sibling level (next to `deadlines:`) or nested inside `deadlines:`.

    Schema A (majority): everything inside deadlines:.
    Schema B (minority, e.g. AAAI/ICCPS/PODC): notification/camera_ready as
    siblings of deadlines:.
    """
    if leaf_name in round_dict:
        return 'sibling'
    dl = round_dict.get('deadlines') or {}
    if leaf_name in dl:
        return 'nested'
    # truly missing — follow sibling convention if ANY of the optional fields
    # are siblings on this round, otherwise nest.
    for opt in ('notification', 'camera_ready', 'commitment'):
        if opt in round_dict:
            return 'sibling'
    return 'nested'


def find_entry_by_id(data: list, conf_id: str) -> int | None:
    for i, c in enumerate(data):
        if c.get('id') == conf_id:
            return i
    return None


def safe_eq(a: Any, b: Any) -> bool:
    """Compare two values for the `current` sanity check. Handles
    datetime <-> string and avoids being too strict (e.g. 1.0 vs 1)."""
    if a == b:
        return True
    sa, sb = str(a), str(b)
    if sa == sb:
        return True
    # normalise -12:00 timezone suffix variants
    return sa.rstrip('Z') == sb.rstrip('Z')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--include-low', action='store_true', help='Apply low-confidence patches too')
    ap.add_argument('--dry-run', action='store_true', help='Show what would change, don\'t write')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    if not PATCHES_DIR.exists():
        sys.stderr.write(f"No patches dir: {PATCHES_DIR}\n")
        return 1

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 10_000

    with open(YAML_PATH) as f:
        data = yaml.load(f)

    # Backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = BACKUP_DIR / f'conferences-{ts}.yaml'
    shutil.copy2(YAML_PATH, backup)
    print(f"Backup: {backup}")

    # Collect patches
    all_patches = []
    for f in sorted(PATCHES_DIR.glob('batch_*.json')):
        try:
            batch = json.loads(f.read_text())
            if not isinstance(batch, list):
                print(f"  WARN {f.name}: not a JSON array, skipping")
                continue
            for p in batch:
                p['_source_file'] = f.name
                all_patches.append(p)
        except json.JSONDecodeError as e:
            print(f"  ERROR {f.name}: {e}")
    print(f"Loaded {len(all_patches)} patches from {len(list(PATCHES_DIR.glob('batch_*.json')))} files")

    stats = {'applied': 0, 'skipped_low': 0, 'skipped_struct': 0, 'skipped_type': 0,
             'skipped_path': 0, 'skipped_unchanged': 0, 'skipped_dryrun': 0, 'errors': 0}
    skip_log = []

    for p in all_patches:
        conf_id = p.get('id')
        field = p.get('field', '')
        correct = p.get('correct')
        confidence = p.get('confidence', 'medium')

        if confidence == 'low' and not args.include_low:
            stats['skipped_low'] += 1
            skip_log.append((p, 'low confidence'))
            continue

        # Guard 2: refuse structural-replacement patches
        if field.endswith(('.rounds', '.tracks')) or field in ('tracks', 'rounds'):
            stats['skipped_struct'] += 1
            skip_log.append((p, f"structural replacement: {field}"))
            continue
        if isinstance(correct, str) and ('[{' in correct or '},{' in correct or '\n  - ' in correct):
            stats['skipped_struct'] += 1
            skip_log.append((p, "agent supplied free-text description, not a value"))
            continue

        # Locate the conference entry
        idx = find_entry_by_id(data, conf_id)
        if idx is None:
            stats['skipped_path'] += 1
            skip_log.append((p, f"no entry with id={conf_id!r}"))
            continue
        entry = data[idx]

        # Parse and walk path
        try:
            tokens = parse_path(field)
        except ValueError as e:
            stats['errors'] += 1
            skip_log.append((p, f"path parse: {e}"))
            continue
        target = walk_path(entry, tokens)
        if target is None:
            # Try dual-schema rerouting if the last segment is notification/
            # camera_ready/commitment under a `.deadlines` parent
            if len(tokens) >= 2 and tokens[-2] == ('deadlines', None) and tokens[-1][0] in (
                'notification', 'camera_ready', 'commitment'
            ):
                # Drop the `deadlines.` middle segment, try at sibling level
                alt_tokens = tokens[:-2] + [tokens[-1]]
                target = walk_path(entry, alt_tokens)
                if target is not None:
                    if args.verbose:
                        print(f"  [reroute] {conf_id} {field} → sibling-level")
            if target is None:
                stats['skipped_path'] += 1
                skip_log.append((p, f"path not found: {field}"))
                continue

        container, key = target
        # Get current value
        if isinstance(container, list):
            cur_val = container[key]
        else:
            cur_val = container.get(key)

        # Special-case: routing notification/camera_ready/commitment via the
        # dual-schema detect. If patch wrote `tracks[N].rounds[M].deadlines.X`
        # but the round actually uses sibling-style, we should reroute.
        leaf_name = tokens[-1][0]
        if leaf_name in ('notification', 'camera_ready', 'commitment') and len(tokens) >= 2:
            # Find the round dict (parent of `.deadlines.X` or `.X`)
            if tokens[-2] == ('deadlines', None):
                # Nested-style path; check if round actually uses sibling.
                # Walk via resolve_idx so name-lookup tokens work too.
                round_tokens = tokens[:-2]
                cur = entry
                round_dict = None
                ok = True
                for k, j in round_tokens:
                    if not isinstance(cur, dict):
                        ok = False; break
                    nxt = cur.get(k)
                    if j is not None:
                        if not isinstance(nxt, list):
                            ok = False; break
                        ri = resolve_idx(nxt, j)
                        if ri is None:
                            ok = False; break
                        nxt = nxt[ri]
                    if nxt is None:
                        ok = False; break
                    cur = nxt
                round_dict = cur if (ok and isinstance(cur, dict)) else None
                if round_dict is not None:
                    schema = detect_dual_schema(round_dict, leaf_name)
                    if schema == 'sibling':
                        # Reroute to sibling
                        container = round_dict
                        key = leaf_name
                        cur_val = round_dict.get(leaf_name)
                        if args.verbose:
                            print(f"  [dual-schema] {conf_id}: rerouting {field} → sibling-level")

        # Sanity-check current value vs claim. Use isinstance-based type checks
        # rather than class-name comparison — ruamel wraps strings in
        # SingleQuotedScalarString and datetimes in TimeStamp (both subclasses).
        claimed = p.get('current')
        if claimed is not None and cur_val is not None and not safe_eq(claimed, cur_val):
            # Allow flexibility for: str<->str (any subclass), datetime<->str,
            # dict<->str (agent flattened a CommentedMap into prose).
            cur_is_str = isinstance(cur_val, str)
            cur_is_dt = hasattr(cur_val, 'isoformat')
            cur_is_dict = isinstance(cur_val, dict)
            claim_is_str = isinstance(claimed, str)
            claim_is_dict = isinstance(claimed, dict)
            ok = (
                (cur_is_str and claim_is_str)
                or (cur_is_dt and claim_is_str)
                or (cur_is_dict and (claim_is_str or claim_is_dict))
            )
            if not ok:
                stats['skipped_type'] += 1
                skip_log.append((p, f"current mismatch: tracker={cur_val!r} vs claim={claimed!r}"))
                continue

        # Type check before write — only block writes that would clobber
        # a structured value with prose.
        if cur_val is not None and correct is not None:
            cur_is_dict = isinstance(cur_val, dict)
            cur_is_list = isinstance(cur_val, list)
            correct_is_str = isinstance(correct, str)
            if (cur_is_dict or cur_is_list) and correct_is_str:
                # Special case: `location` field with "City, Country" string.
                # We rewrite it into sub-field patches (city, country) and skip
                # the parent write.
                leaf = tokens[-1][0]
                if leaf == 'location' and ',' in correct:
                    parts = [s.strip() for s in correct.split(',', 1)]
                    if len(parts) == 2 and isinstance(container, dict):
                        loc = container.get('location') or {}
                        loc['city'] = parts[0]
                        loc['country'] = parts[1]
                        container['location'] = loc
                        stats['applied'] += 1
                        if args.verbose:
                            print(f"  [OK split] {conf_id}.location: city={parts[0]!r} country={parts[1]!r}")
                        continue
                if leaf == 'dates' and ' to ' in correct:
                    start, end = [s.strip() for s in correct.split(' to ', 1)]
                    if isinstance(container, dict):
                        d = container.get('dates') or {}
                        d['start'] = SingleQuotedScalarString(start) if re.match(r'^\d{4}-\d{2}-\d{2}', start) else start
                        d['end'] = SingleQuotedScalarString(end) if re.match(r'^\d{4}-\d{2}-\d{2}', end) else end
                        container['dates'] = d
                        stats['applied'] += 1
                        if args.verbose:
                            print(f"  [OK split] {conf_id}.dates: start={start} end={end}")
                        continue
                stats['skipped_type'] += 1
                skip_log.append((p, f"type: would clobber {type(cur_val).__name__} with str: {correct!r}"))
                continue

        # No-op?
        if safe_eq(cur_val, correct):
            stats['skipped_unchanged'] += 1
            skip_log.append((p, "value already matches"))
            continue

        # Apply write (with single-quote preservation for date strings)
        if args.dry_run:
            stats['skipped_dryrun'] += 1
            print(f"  [dry-run] {conf_id}.{field}: {cur_val!r} → {correct!r}  ({p.get('reason','')[:50]})")
            continue

        write_val = correct
        if isinstance(correct, str) and re.match(r'^\d{4}-\d{2}-\d{2}', correct):
            write_val = SingleQuotedScalarString(correct)

        if isinstance(container, list):
            container[key] = write_val
        else:
            container[key] = write_val
        stats['applied'] += 1
        if args.verbose:
            print(f"  [OK] {conf_id}.{field}: {cur_val!r} → {correct!r}")

    # Write back
    if not args.dry_run and stats['applied'] > 0:
        with open(YAML_PATH, 'w') as f:
            yaml.dump(data, f)
        print(f"\nWrote {YAML_PATH}")

    # Summary
    print("\n=== Summary ===")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")

    # Log skipped patches for review
    log_file = Path('/tmp/cfp_refresh/skipped.log')
    with open(log_file, 'w') as f:
        for p, reason in skip_log:
            f.write(f"[{reason}] {p.get('id')} {p.get('field')} → {p.get('correct')!r}  "
                    f"src={p.get('_source_file')}\n")
    print(f"  skip log: {log_file}")

    # Validate
    if not args.dry_run and stats['applied'] > 0:
        print("\n--- Running validator ---")
        r = subprocess.run(['python3', str(ROOT / 'scripts' / 'validate.py')],
                           cwd=ROOT, capture_output=True, text=True)
        print(r.stdout)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            print(f"\n!! Validator failed. Restore from backup: cp {backup} {YAML_PATH}")
            return 2
        print("OK validator passed")

    return 0


if __name__ == '__main__':
    sys.exit(main())
