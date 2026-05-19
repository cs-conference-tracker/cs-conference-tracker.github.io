# CS Conference Tracker

Static, no-build CS conference deadline tracker. Trilingual UI (EN / 中 / 日),
filtering by topic and ranking (CCF / CORE), three views: List, Timeline, Map.
Data lives in YAML files; the browser fetches and parses them on each page load.

## Quick start

```bash
cd /path/to/conferences
python3 scripts/serve.py 8000     # serves static files + tiny /api/likes counter
# or, if you don't want the like counter, plain Python is enough:
python3 -m http.server 8000
# open http://localhost:8000/
```

No `npm install`, no build.

## Deploy to GitHub Pages

The `public` branch is exactly what you'd push. Enable Pages on it; everything
is plain HTML/CSS/JS that runs out of the box. The 👍 button degrades to a
placeholder when there's no backend.

## Layout

```
conferences/
├── index.html              Main app
├── glossary.html           Glossary reference page
├── styles.css              Design tokens + light/dark themes
├── js/
│   ├── app.js              Alpine.js root: data loading, filters, view switching
│   ├── cards.js            Card helpers (ranking chips, deadline ordering)
│   ├── timeline.js         Horizontal Gantt view
│   ├── map.js              Leaflet + clustered markers
│   ├── glossary.js         Popover content + positioning
│   ├── ics.js              Client-side .ics calendar export
│   ├── likes.js            Floating 👍 widget (bottom-right)
│   ├── i18n.js             EN / ZH / JA translations
│   └── utils.js            Date parsing, URL state, AoE handling
├── data/
│   ├── conferences.yaml    The conference list (edited manually)
│   ├── glossary.yaml       Topic / ranking / jargon definitions
│   └── *.json              Pre-baked JSON (built by scripts/build_json.py)
└── scripts/
    ├── serve.py            Static server + likes counter
    ├── build_json.py       YAML → JSON for faster page loads
    └── validate.py         Pre-deploy YAML sanity check
```

## Editing the conference list

1. Open `data/conferences.yaml` (or the smaller `conferences-additions.yaml`
   for added venues).
2. Update deadlines against each official CFP page (the CFP is authoritative —
   third-party trackers lag).
3. Move past entries to `data/archive/` if you have one; or delete.
4. Run the validator:
   ```bash
   python3 scripts/validate.py
   ```
5. (Optional) Rebuild the pre-baked JSON for faster loads:
   ```bash
   python3 scripts/build_json.py
   ```

## Architecture decisions

- **YAML over CSV**: nested structure (track → round → deadlines) requires it.
- **No backend, no scraping**: manual updates against authoritative CFP pages.
- **Client-side `.ics` export**: works with everyone's calendar app.
- **All datetimes stored with UTC offset**: AoE default is `-12:00`. Avoids the
  off-by-one bugs that plague most deadline trackers.
- **Trilingual UI**: EN / 中 / 日 toggle from any page.

## Browser support

Modern evergreen browsers (Chrome, Firefox, Safari, Edge — latest two versions).

## Dependencies (CDN, no install)

- Alpine.js 3.x — reactive UI
- js-yaml 4.x — YAML parsing
- dayjs 1.11.x (+ utc, timezone, relativeTime, duration, advancedFormat)
- Leaflet 1.9.x + Leaflet.markercluster 1.5.x
- OpenStreetMap tiles (no API key required)

All loaded over HTTPS from unpkg / jsdelivr. To go fully offline, mirror these
into `vendor/` and update the `<script>` / `<link>` URLs in `index.html` and
`glossary.html`.
