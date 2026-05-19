# CS Conference Tracker — Koshizuka Lab

CS conference deadline tracker. Static site, no backend, no build step.
Data lives in YAML files; the browser fetches and parses them on each page load.

**Affiliation**: Koshizuka Lab, Graduate School of Interdisciplinary Information
Studies (情報学環), The University of Tokyo.

---

## Quick start (local preview)

```bash
cd /path/to/conferences
python3 -m http.server 8000
# open http://localhost:8000/
```

That's it. No `npm install`, no build.

---

## Layout

```
conferences/
├── index.html              Main app
├── glossary.html           Standalone glossary reference page
├── styles.css              All styling (design tokens, light + dark)
├── js/
│   ├── app.js              Alpine.js root; data loading, filters, view switching
│   ├── cards.js            Per-card helpers (ranking chips, deadline ordering)
│   ├── timeline.js         Horizontal Gantt view
│   ├── map.js              Leaflet + pulse markers
│   ├── glossary.js         Popover content + positioning
│   ├── ics.js              .ics calendar export
│   └── utils.js            Date parsing, URL state, AoE handling
├── data/
│   ├── conferences.yaml    ← Edited monthly by lab maintainer
│   ├── publications.yaml   ← Updated when lab publishes a new paper
│   ├── glossary.yaml       ← Rarely edited (new topic key or ranking system)
│   └── archive/            Optional: park past conferences here
├── scripts/
│   ├── bibtex_to_yaml.py   .bib → publications.yaml converter
│   └── validate.py         Pre-deploy YAML sanity check
└── README.md               This file
```

---

## Monthly maintenance workflow

On the **first of each month**, the assigned lab maintainer:

1. Open `data/conferences.yaml`.
2. For every entry, open the conference's `website` field in a browser and
   compare each deadline against the live CFP page. **The CFP page is
   authoritative** — third-party trackers (and this tracker) lag.
3. Move entries whose deadlines have entirely passed and that won't recur this
   year into `data/archive/` (or delete; the maintainer's call).
4. Add any new conferences the lab plans to target. Copy an existing entry and
   edit fields rather than starting from scratch.
5. Run the validator:
   ```bash
   python3 scripts/validate.py
   ```
   Fix any errors. Warnings are advisory.
6. Bump the date shown in the footer (it's auto-derived from page load, but if
   you want a hard timestamp, edit the `deriveLastUpdate()` function in `app.js`).
7. Commit and push (or scp to the nginx directory).

**Time budget per month**: 30–60 minutes if a handful of entries changed.

---

## Adding a new publication

When the lab gets a paper accepted:

1. Save the BibTeX entry to a local file, e.g. `new.bib`.
2. Run:
   ```bash
   python3 scripts/bibtex_to_yaml.py new.bib >> data/publications.yaml
   ```
   The script auto-fills `location` if the `(venue, year)` tuple appears in
   `conferences.yaml`. Otherwise it writes `city: TBD`.
3. Open `data/publications.yaml` and:
   - Fix any `TBD` location (city + country + lat/lng of where the paper
     was presented — for IMWUT-type journals, use the UbiComp co-location city
     for that year).
   - Verify `type` (`full_paper`, `workshop`, `demo`, `poster`, `journal`,
     `short_paper`).
4. Run `python3 scripts/validate.py`.
5. Commit and deploy.

---

## Adding a new topic tag or ranking

Edit `data/glossary.yaml`:

- **New topic**: add an entry under `topics:` with at least `full_name`,
  `category`, and `description`. Then reference its key in any conference's
  `topics:` list. The tracker logs a `warn:` if a conference references a topic
  key that's not in glossary, so the validator will catch typos.
- **New ranking system**: add under `rankings:` with `short`, `full`, `source`,
  `description`, and optional `url`. Then map the conference-entry value to the
  glossary key inside `js/glossary.js → rankingKey()`.

---

## Deployment

### Option A — nginx on the lab LAN

Copy the directory to the server and serve it at any path:

```nginx
location /conf-tracker/ {
    alias /var/www/conf-tracker/;
    try_files $uri $uri/ =404;
}
```

No special MIME setup needed — browsers handle `.yaml` as text.

### Option B — GitHub Pages (private repo)

Push to a private GitHub repo and enable Pages on the `main` branch. Lab members
need GitHub accounts with read access to the repo.

---

## Architecture decisions

- **YAML over CSV**: nested structure (track → round → deadlines) requires it.
- **No backend, no scraping**: monthly manual updates are more reliable than
  agent-based collection and have zero operational cost.
- **`.ics` export per conference**: works with everyone's calendar app; no
  email subscription service needed.
- **All datetimes stored UTC offset**: AoE default is `-12:00`. Avoids the
  off-by-one bugs that plague most deadline trackers.
- **English-only UI**: international audience; acronyms are universal.
- **Three views (Cards / Timeline / Map)**: each serves a distinct need
  — browsing, planning, geographic lens.

See the design document for full context.

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Conference doesn't appear | Topic key typo not in glossary | Check console — validator catches this |
| Countdown shows "Past" but CFP is still open | YAML date in wrong timezone offset | Confirm you used `-12:00` (AoE) not `+09:00` (JST) |
| Pulse animation not visible | Browser has `prefers-reduced-motion: reduce` | Working as designed; animation is suppressed |
| Map markers all at (0, 0) | Location fields missing/wrong | Run validator; check lat/lng signs |
| `.ics` import skips events | UID collision with prior version | Bump conference `id` (UID is derived from it) |
| Dark mode tiles wash out | OSM tiles have no native dark mode | Inversion filter in CSS handles it cheaply |

---

## Browser support

Modern evergreen browsers (Chrome, Firefox, Safari, Edge — latest two versions).
No IE11. Tested on macOS Safari, Firefox, Chrome.

---

## Dependencies (CDN, no install)

- Alpine.js 3.x — reactive UI
- js-yaml 4.x — YAML parsing
- dayjs 1.11.x (+ utc, timezone, relativeTime, duration, advancedFormat) — dates
- Leaflet 1.9.x — map
- Leaflet.markercluster 1.5.x — map clustering
- OpenStreetMap — tile server (no API key required)

All loaded over HTTPS from unpkg / jsdelivr. To go fully offline, mirror these
into `vendor/` and update the `<script>` / `<link>` URLs in `index.html` and
`glossary.html`.

---

## Maintainer Python deps

For the optional scripts only:

```bash
pip install bibtexparser pyyaml
```
