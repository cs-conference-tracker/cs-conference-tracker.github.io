/* =========================================================================
   app.js — Alpine.js root component. Data loading, filters, view switching.
   Exposes trackerApp() factory referenced by <body x-data="trackerApp()">.
   ========================================================================= */

// Lab-internal vs public deployment. Hostname-based — if the visitor can
// reach an IP/host on this allowlist, they're already on the lab network,
// so internal-only features (Slack post template, Feedback submission, Lab
// paper history) are unlocked. Hosted on github.io or any other public
// host → public mode, those features hide.
// Override via URL hash for testing: #mode=internal or #mode=public.
const INTERNAL_HOSTNAME_PATTERNS = [
  /^localhost$/i,
  /^127\.0\.0\.1$/,
  /^10\./,                                // 10.0.0.0/8
  /^192\.168\./,                          // 192.168.0.0/16
  /^172\.(1[6-9]|2[0-9]|3[01])\./,        // 172.16.0.0/12
  /\.u-tokyo\.ac\.jp$/i,                  // university DNS
  /^koshizuka-lab\./i,                    // any custom lab subdomain
];

function detectMode() {
  const m = (window.location.hash || '').match(/(?:^|&|#)mode=(internal|public)\b/i);
  if (m) return m[1].toLowerCase();
  const host = (window.location.hostname || '').toLowerCase();
  return INTERNAL_HOSTNAME_PATTERNS.some(re => re.test(host)) ? 'internal' : 'public';
}

window.trackerApp = function () {

  return {
    // -------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------
    loading: true,
    error: null,
    conferences: [],
    publications: [],
    glossary: null,

    // 'internal' (lab network) → Slack template, Feedback, Lab paper history all visible.
    // 'public'   (github.io etc.) → those three hidden.
    // Decided once at init by detectMode(); not persisted.
    mode: 'public',

    view: 'cards',          // cards | timeline | map
    mapMode: 'upcoming',    // upcoming | history

    filters: {
      q: '',
      topics: [],
      ranks: [],           // checkbox group; e.g. ['ccf-A','core-A*']. Empty = no rank filter.
      sort: 'next-ddl',
    },

    expanded: {},           // { [confId]: bool }
    popover: { open: false, style: {}, content: null, anchor: null },
    // Map side panel — opens when user clicks a marker (single conf) or a
    // cluster (multiple confs at the same location). Paginated when there
    // are more than `perPage` to avoid overflowing the panel and forcing the
    // user to scroll past the map.
    sidePanel: { open: false, confs: [], page: 0, perPage: 3, title: '' },

    // Anonymous feedback modal. Name is optional. Category radio is required
    // (defaults to bug). Messages are POSTed to /api/submit-feedback which
    // appends them to ~/.ct_comments.jsonl on the server; a weekly cron
    // ships the digest to the maintainer mailbox.
    feedback: {
      open: false, name: '', category: 'bug', message: '',
      sending: false, sent: false, error: '',
    },

    // Slack post template — generates the fixed 【締切】/【研究ネタ】/...
    // format lab members post to the #paper channel before each submission.
    // Opens either from a conf card (auto-fills 学会 / URL / 締切) or from
    // the header button (empty). Authors line is persisted in localStorage
    // so the user doesn't retype their collaborators every time.
    slackModal: {
      open: false, conf: null,
      deadlines: [],              // [{key, kind, ...}] — picker for conf mode
      deadlineKey: '',            // selected key, drives deadlineText
      deadlineText: '',           // editable string ("Sep 15th, 2024")
      topic: '',                  // 研究ネタ
      venue: '',                  // 学会
      url: '',                    // URL
      paperType: 'Conference Papers',  // 論文タイプ
      authors: '',                // Authors (persisted)
      abstract: '',               // Abst
      copied: false, error: '',
    },
    showHint: false,
    // Onboarding banner shown on first visit and any time the user
    // re-opens it. Persisted in localStorage so dismissals stick across
    // sessions — checked once in init() and updated by toggleHowto().
    showHowto: true,
    isMobile: false,

    // Pagination — Cards view only. 24 cards = 3 cols × 8 rows on a wide
    // monitor, 2 cols × 12 on a laptop. Map / Timeline still render the
    // full filtered list since they need the whole spatial/temporal view.
    currentPage: 1,
    pageSize: 24,

    countdownTick: 0,       // bumped every 1s for visible countdown spans only
    resortTick: 0,          // bumped every 60s — invalidates the filter/sort memo so next-ddl re-orders
    lang: 'en',             // current UI language; mutating it re-runs every template using t()
    lastUpdateDate: '',
    // Calendar modal — pure client-side. Lists every (track, round, kind)
    // deadline for the conf with a checkbox per row. Bulk actions at the
    // bottom act on the ticked set: add to Google Calendar, add to Outlook,
    // or download a single bundled .ics. Default selection = primary
    // submission deadline.
    calModal: {
      open: false, conf: null,
      deadlines: [],           // [{key, kind, kindLabel, trackName, roundLabel, value}]
      selected: {},            // {key: true} — which rows the user has ticked
      bulkHint: '',            // '' | 'gcal' | 'outlook' — drives the post-action hint banner
    },

    // Memo for filteredConferences. Recomputing the full filter+sort+next-ddl
    // for 318 venues on every Alpine getter access is expensive, and the
    // result is the same across 5+ template references per render. Keyed by
    // filters + resortTick (not countdownTick — second-by-second resorts are
    // pointless when the visible countdown text already updates on its own).
    _filterMemo: null,

    // Checkbox-group ranking filter. Each item is one CCF or one CORE grade;
    // a conf passes if EITHER its CCF or its CORE grade matches any checked
    // box. Label is a literal short tag — never translated, since CCF/CORE
    // grade names are not localized.
    rankingOptions: [
      { value: 'ccf-A',    label: 'CCF A',    family: 'ccf',  grade: 'A'  },
      { value: 'ccf-B',    label: 'CCF B',    family: 'ccf',  grade: 'B'  },
      { value: 'ccf-C',    label: 'CCF C',    family: 'ccf',  grade: 'C'  },
      { value: 'core-A*',  label: 'CORE A*',  family: 'core', grade: 'A*' },
      { value: 'core-A',   label: 'CORE A',   family: 'core', grade: 'A'  },
      { value: 'core-B',   label: 'CORE B',   family: 'core', grade: 'B'  },
      { value: 'core-C',   label: 'CORE C',   family: 'core', grade: 'C'  },
    ],

    // Sort option labels come from the i18n table; resolved lazily so they
    // re-translate when `lang` changes.
    sortOptions: [
      { value: 'next-ddl',  i18nKey: 'sort.nextDdl'  },
      { value: 'conf-date', i18nKey: 'sort.confDate' },
      { value: 'acronym',   i18nKey: 'sort.acronym'  },
    ],

    // -------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------
    async init() {
      this.isMobile = window.matchMedia('(max-width: 600px)').matches;
      window.matchMedia('(max-width: 600px)')
        .addEventListener('change', e => { this.isMobile = e.matches; });

      // Decide internal vs public mode once, before anything renders. Tells
      // the template whether to show Slack post, Feedback, Lab paper history.
      this.mode = detectMode();

      this.lang = CT.i18n.getLang();
      this.restoreFromUrl();
      this.restoreMapMode();
      // Public mode never shows lab paper history; reset if a stale
      // localStorage/URL value would land them there.
      if (this.mode === 'public' && this.mapMode === 'history') {
        this.mapMode = 'upcoming';
      }
      this.maybeShowHint();
      // Onboarding: persisted across sessions, default open on first visit.
      this.showHowto = localStorage.getItem('ct-howto-dismissed') !== '1';

      await this.loadData();
      this.lastUpdateDate = this.deriveLastUpdate();

      // Two ticks: a fast 1s tick for visible countdown text only, and a slow
      // 60s tick that invalidates the filtered/sorted list memo so the
      // next-ddl order eventually catches up as deadlines pass.
      setInterval(() => { this.countdownTick++; }, 1000);
      setInterval(() => { this.resortTick++; }, 60000);

      // React to hash changes (back/forward navigation)
      window.addEventListener('hashchange', () => this.restoreFromUrl());

      // Watch view → mount map / timeline on demand
      this.$watch('view', v => this.handleViewChange(v));
      this.$watch('mapMode', () => this.renderMap());
      // Re-render map/timeline when filters change. Reset pagination back
      // to page 1 — otherwise a filter that shrinks the result set leaves
      // the user staring at an empty page beyond the new last page.
      ['q', 'topics', 'ranks', 'sort'].forEach(k => {
        this.$watch(`filters.${k}`, () => {
          this.currentPage = 1;
          this.syncUrl();
          if (this.view === 'map') this.renderMap();
          if (this.view === 'timeline') this.renderTimeline();
        });
      });
    },

    async loadData() {
      try {
        // Prefer pre-baked JSON (JSON.parse is ~10x faster than js-yaml on
        // the 400KB conferences file). Fall back to YAML if the JSON file
        // was not generated — keeps the site working when someone forgets
        // to run scripts/build_json.py after editing data/*.yaml.
        const opts = { cache: 'no-cache' };
        const loadOne = async (name) => {
          const j = await fetch(`data/${name}.json`, opts);
          if (j.ok) return j.json();
          const y = await fetch(`data/${name}.yaml`, opts).then(this.failIfBad);
          return jsyaml.load(await y.text());
        };
        // Publications (lab paper history) is internal-only data, excluded
        // from public builds via .gitignore. Load fail-soft so public
        // deployments where the file isn't shipped still work — the file
        // is only consumed by the Map view's history mode, which is itself
        // hidden in public mode.
        const loadOptional = async (name) => {
          try { return await loadOne(name); }
          catch (e) {
            console.info(`[data] optional file '${name}' not available — skipping`);
            return [];
          }
        };
        const [conf, pub, gloss] = await Promise.all([
          loadOne('conferences'),
          this.mode === 'internal' ? loadOptional('publications') : Promise.resolve([]),
          loadOne('glossary'),
        ]);
        this.conferences = conf || [];
        this.publications = pub || [];
        this.glossary = gloss || {};

        this.validateData();
        this.loading = false;

        // Map mounting deferred until view becomes 'map' (Leaflet needs visible container)
        if (this.view === 'timeline') this.$nextTick(() => this.renderTimeline());
        if (this.view === 'map') this.$nextTick(() => this.mountAndRenderMap());
      } catch (e) {
        console.error(e);
        this.error = `Failed to load data: ${e.message}`;
        this.loading = false;
      }
    },

    failIfBad(r) {
      if (!r.ok) throw new Error(`${r.url} → HTTP ${r.status}`);
      return r;
    },

    // -------------------------------------------------------------------
    // Validation (warn-only)
    // -------------------------------------------------------------------
    validateData() {
      const topicKeys = new Set(Object.keys(this.glossary?.topics || {}));
      this.conferences.forEach((c, i) => {
        if (!c.id || !c.acronym || !c.year) {
          console.warn(`[conferences[${i}]] missing required id/acronym/year`, c);
        }
        (c.topics || []).forEach(t => {
          if (!topicKeys.has(t)) {
            console.warn(`[${c.id || i}] unknown topic key "${t}"`);
          }
        });
        if (!c.tracks || c.tracks.length === 0) {
          console.warn(`[${c.id}] has no tracks`);
        }
      });
      this.publications.forEach((p, i) => {
        if (!p.id || !p.title || !p.year) {
          console.warn(`[publications[${i}]] missing required fields`, p);
        }
      });
    },

    deriveLastUpdate() {
      // Fallback to today's date if no manifest is provided
      return dayjs().format('YYYY-MM-DD');
    },

    // -------------------------------------------------------------------
    // View switching
    // -------------------------------------------------------------------
    setView(v) {
      this.view = v;
      this.syncUrl();
    },

    handleViewChange(v) {
      this.closePopover();
      if (v === 'map') {
        this.$nextTick(() => this.mountAndRenderMap());
      } else if (v === 'timeline') {
        this.$nextTick(() => this.renderTimeline());
      }
    },

    mountAndRenderMap() {
      CT.map.init('map');
      CT.map.setSelectCallback(conf => this.openSidePanel(conf));
      CT.map.setClusterSelectCallback((confs, label) => this.openSidePanelMulti(confs, label));
      this.renderMap();
      CT.map.invalidate();
    },

    renderMap() {
      if (this.view !== 'map') return;
      if (this.mapMode === 'upcoming') {
        CT.map.renderUpcoming(this.filteredConferences());
      } else {
        CT.map.renderHistory(this.publications);
      }
    },

    setMapMode(m) {
      this.mapMode = m;
      localStorage.setItem('mapDefaultMode', m);
      this.closeSidePanel();
      this.syncUrl();
    },

    restoreMapMode() {
      const saved = localStorage.getItem('mapDefaultMode');
      if (saved === 'upcoming' || saved === 'history') this.mapMode = saved;
    },

    renderTimeline() {
      if (this.view !== 'timeline') return;
      CT.timeline.render('timeline-mount', this.filteredConferences());
    },

    // -------------------------------------------------------------------
    // Filtering / sorting
    // -------------------------------------------------------------------
    filteredConferences() {
      // Memo invalidated by filters (q/topics/rank/sort), the slow 60s
      // resortTick (so next-ddl order eventually catches up), and the
      // conferences-length proxy (cheap way to detect a fresh data load).
      // Crucially NOT invalidated by countdownTick — the visible per-row
      // countdown spans read that themselves; refiltering 318 venues
      // every second was the main source of the laggy feel.
      const sig = [
        this.filters.q, this.filters.topics.join(','),
        this.filters.ranks.join(','), this.filters.sort,
        this.conferences.length, this.resortTick,
      ].join('|');
      if (this._filterMemo && this._filterMemo.sig === sig) {
        return this._filterMemo.list;
      }

      const q = this.filters.q.trim().toLowerCase();
      const selectedTopics = this.filters.topics;
      const ranks = this.filters.ranks;

      let list = this.conferences.filter(c => {
        if (q) {
          // c.description is now {en, zh, ja} — flatten all three so
          // search matches keywords in any language.
          const d = c.description;
          const descParts = d && typeof d === 'object'
            ? [d.en, d.zh, d.ja]
            : [d];
          const hay = [
            c.acronym, c.name, ...descParts,
            c.location?.city, c.location?.country,
          ].filter(Boolean).join(' ').toLowerCase();
          if (!hay.includes(q)) return false;
        }
        if (selectedTopics.length) {
          const ts = new Set(c.topics || []);
          if (!selectedTopics.every(t => ts.has(t))) return false;
        }
        if (!this.matchesRanks(c, ranks)) return false;
        return true;
      });

      list.sort((a, b) => {
        if (this.filters.sort === 'acronym') {
          return a.acronym.localeCompare(b.acronym);
        }
        if (this.filters.sort === 'conf-date') {
          const ad = a.dates?.start ? dayjs(a.dates.start).valueOf() : Infinity;
          const bd = b.dates?.start ? dayjs(b.dates.start).valueOf() : Infinity;
          return ad - bd;
        }
        // next-ddl — by submission deadline (the gating one)
        const an = CT.utils.nextSubmissionFor(a);
        const bn = CT.utils.nextSubmissionFor(b);
        const av = an.past ? Infinity : an.value.valueOf();
        const bv = bn.past ? Infinity : bn.value.valueOf();
        if (av === bv) return a.acronym.localeCompare(b.acronym);
        return av - bv;
      });

      this._filterMemo = { sig, list };
      return list;
    },

    // ---- Pagination (Cards view only) ----
    paginatedConferences() {
      const all = this.filteredConferences();
      const start = (this.currentPage - 1) * this.pageSize;
      return all.slice(start, start + this.pageSize);
    },

    totalPages() {
      const n = this.filteredConferences().length;
      return Math.max(1, Math.ceil(n / this.pageSize));
    },

    // Compact pager: always show first, current-1, current, current+1, last.
    // Gaps replaced by an ellipsis sentinel. Deduplicated and ordered.
    pagerItems() {
      const total = this.totalPages();
      const cur = this.currentPage;
      const out = new Set([1, cur - 1, cur, cur + 1, total]);
      const sorted = [...out].filter(n => n >= 1 && n <= total).sort((a, b) => a - b);
      const items = [];
      let prev = 0;
      for (const n of sorted) {
        if (n - prev > 1) items.push('…');
        items.push(n);
        prev = n;
      }
      return items;
    },

    goToPage(p) {
      const total = this.totalPages();
      this.currentPage = Math.max(1, Math.min(total, p));
      // Scroll to top of card list for a clean transition
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    pageRangeLabel() {
      const total = this.filteredConferences().length;
      if (total === 0) return '0 of 0';
      const start = (this.currentPage - 1) * this.pageSize + 1;
      const end = Math.min(this.currentPage * this.pageSize, total);
      return `${start}–${end} of ${total}`;
    },

    matchesRanks(c, ranks) {
      if (!ranks || !ranks.length) return true;
      const r = c.rankings || {};
      // AND across families (a conf must pass every family that has at
      // least one ticked box), OR within a family (any of that family's
      // ticked grades qualifies). Example:
      //   ticked = [CCF-A, CCF-B, CORE-A*]
      //   → must have ccf ∈ {A,B} AND core = A*
      // No ticks in a family = no restriction from that family.
      const byFamily = {};
      for (const v of ranks) {
        const opt = this.rankingOptions.find(o => o.value === v);
        if (!opt) continue;
        (byFamily[opt.family] ||= []).push(opt.grade);
      }
      for (const family of Object.keys(byFamily)) {
        const grades = byFamily[family];
        if (!grades.includes(r[family])) return false;
      }
      return true;
    },

    toggleTopic(key) {
      const i = this.filters.topics.indexOf(key);
      if (i === -1) this.filters.topics.push(key);
      else this.filters.topics.splice(i, 1);
      this.syncUrl();
    },

    // "All" is a virtual checkbox at the top of the dropdown. It is
    // visually checked when no individual rank is selected (filters.ranks
    // is empty == no filter == everything shown).
    isAllRanksChecked() {
      return !this.filters.ranks.length;
    },
    // An individual rank box is visually checked when:
    //  - "All" is on (default state — everything is implicitly included), OR
    //  - this specific rank is in the active filter set
    isRankChecked(v) {
      return this.isAllRanksChecked() || this.filters.ranks.includes(v);
    },
    toggleRank(v) {
      if (this.isAllRanksChecked()) {
        // First click out of "All" mode — start filtering with just this one.
        // (Don't carry over the implicit "everything", that would defeat
        // the user's intent to narrow down.)
        this.filters.ranks = [v];
      } else {
        const i = this.filters.ranks.indexOf(v);
        if (i === -1) this.filters.ranks.push(v);
        else this.filters.ranks.splice(i, 1);
      }
      this.syncUrl();
    },
    toggleAllRanks() {
      // Clicking "All" always resets to no-filter, regardless of prior state.
      this.filters.ranks = [];
      this.syncUrl();
    },
    clearRanks() { this.filters.ranks = []; this.syncUrl(); },
    setSort(v) { this.filters.sort = v; this.syncUrl(); },

    rankingLabel() {
      void this.lang;
      const n = this.filters.ranks.length;
      if (!n) return this.t('filter.anyRanking');
      if (n === 1) {
        const o = this.rankingOptions.find(x => x.value === this.filters.ranks[0]);
        return o ? o.label : `${this.t('filter.rankings')}: 1`;
      }
      return `${this.t('filter.rankings')}: ${n}`;
    },
    sortLabel(v) {
      void this.lang;
      const o = this.sortOptions.find(x => x.value === v);
      return o ? this.t(o.i18nKey) : this.t('sort.nextDdl');
    },

    // ---- i18n ----
    t(key) {
      void this.lang;          // reactive dep so templates re-render on lang switch
      return CT.i18n.t(key);
    },
    // Localized text for data fields that may be a flat string or a
    // {en, zh, ja} object. Used for conference.description, topic.full_name,
    // glossary descriptions, etc. — anything that gradually grows i18n
    // entries without changing the schema upfront.
    iText(value) {
      void this.lang;
      return CT.utils.i18nText(value);
    },
    setLang(lang) {
      CT.i18n.setLang(lang);
      this.lang = lang;
      this.syncUrl();
    },

    filterDirty() {
      return this.filters.q || this.filters.topics.length ||
             this.filters.ranks.length || this.filters.sort !== 'next-ddl';
    },

    resetFilters() {
      this.filters.q = '';
      this.filters.topics = [];
      this.filters.ranks = [];
      this.filters.sort = 'next-ddl';
      this.syncUrl();
    },

    // -------------------------------------------------------------------
    // URL state
    // -------------------------------------------------------------------
    syncUrl() {
      CT.utils.writeUrlState({
        view: this.view,
        q: this.filters.q,
        topics: this.filters.topics,
        ranks: this.filters.ranks,
        sort: this.filters.sort,
        mapMode: this.mapMode,
        lang: this.lang,
      });
    },

    // Back-compat: old single-select `rank=` URLs are translated to the new
    // multi-select `ranks=` array so existing bookmarks keep working.
    _legacyRankMap: {
      'core-a-star': ['core-A*'],
      'core-a-up':   ['core-A*', 'core-A'],
      'ccf-a':       ['ccf-A'],
      'ccf-ab':      ['ccf-A', 'ccf-B'],
    },

    restoreFromUrl() {
      const s = CT.utils.parseUrlState();
      if (s.view) this.view = s.view;
      if (s.q !== undefined) this.filters.q = s.q;
      if (s.topics) this.filters.topics = s.topics;
      if (s.ranks) this.filters.ranks = s.ranks;
      else if (s.rank && this._legacyRankMap[s.rank]) this.filters.ranks = this._legacyRankMap[s.rank];
      if (s.sort) this.filters.sort = s.sort;
      if (s.mapMode) this.mapMode = s.mapMode;
      if (s.lang && CT.i18n.supported.includes(s.lang)) {
        CT.i18n.setLang(s.lang);
        this.lang = s.lang;
      }
    },

    // -------------------------------------------------------------------
    // Cards helpers (delegate to CT.cards / CT.utils)
    // -------------------------------------------------------------------
    nextDeadline(conf) {
      void this.countdownTick;
      const nd = CT.utils.nextSubmissionFor(conf);
      if (nd.past) {
        return { urgency: 'past', past: true, label: 'Closed' };
      }
      const urgency = CT.utils.urgencyFor(nd.value);
      const label = CT.utils.countdownLabel(nd.value);
      return {
        urgency, past: false, label,
        deadline: nd.value, kind: nd.kind,
        trackName: nd.trackName, roundLabel: nd.roundLabel,
      };
    },

    nextDeadlineTitle(conf) {
      const nd = CT.utils.nextSubmissionFor(conf);
      if (nd.past) return 'All submission deadlines have passed';
      const kindLabel = CT.ics.KIND_LABELS[nd.kind] || nd.kind;
      const trackPart = nd.trackName ? ` — ${nd.trackName}${nd.roundLabel ? ' (' + nd.roundLabel + ')' : ''}` : '';
      return `Next submission: ${kindLabel}${trackPart}\n${CT.utils.formatDeadlineLocal(nd.value)}\nAoE: ${CT.utils.formatDeadlineAoE(nd.value)}`;
    },

    // Every upcoming submission deadline EXCEPT the one already shown as the
    // primary pill. This covers (a) later rounds of the main track, and
    // (b) any upcoming round of non-main tracks. Critically: if the main
    // track is fully closed, the primary pill says "Closed" but this list
    // still surfaces non-main tracks that are still accepting submissions.
    secondaryDeadlines(conf) {
      void this.countdownTick;
      const now = dayjs();
      const primary = CT.utils.nextSubmissionFor(conf);
      const primaryKey = primary && !primary.past
        ? `${primary.trackIndex}#${primary.roundIndex}#${primary.kind}`
        : null;
      const all = CT.utils.submissionDeadlinesFor(conf)
        .filter(d => d.value.isAfter(now))
        .sort((a, b) => a.value.diff(b.value));
      return all
        .filter(d => `${d.trackIndex}#${d.roundIndex}#${d.kind}` !== primaryKey)
        .map(d => {
          const trackLabel = d.trackName + (d.roundLabel ? ' · ' + d.roundLabel : '');
          return {
            trackLabel,
            shortLabel: trackLabel.length > 32 ? trackLabel.slice(0, 31) + '…' : trackLabel,
            kindLabel: CT.ics.KIND_LABELS[d.kind] || d.kind,
            countdown: CT.utils.countdownLabel(d.value),
            urgency: CT.utils.urgencyFor(d.value),
            deadline: d.value,
            // Stable key so the "Also open" pill can open the track_kind
            // popover with the right entry — same shape as trackKindKey().
            trackKindKey: `${CT.cards.inferTrackKind(d.trackName)}|${d.trackName}`,
          };
        });
    },

    formatConferenceDates(conf) { return CT.utils.formatConferenceDates(conf); },
    formatLocation(loc) { return CT.cards.formatLocation(loc); },
    hasAnyRanking(conf) { return CT.cards.hasAnyRanking(conf); },
    rankingChips(conf) { return CT.cards.rankingChips(conf, this.glossary); },
    // For the per-track ⓘ popover. Returns "kindId|TrackName" so the
    // popover can show the actual clicked name as the title.
    trackKindKey(trackName) {
      const id = CT.cards.inferTrackKind(trackName);
      return `${id}|${trackName}`;
    },

    // ---- Acceptance stats helpers ----
    // Returns the most recent acceptance entry that has both submitted &
    // accepted counts so we can compute a rate. Used for the row signal.
    latestAcceptance(conf) {
      const arr = (conf.acceptance || [])
        .filter(a => a && a.year && (a.rate != null || (a.submitted && a.accepted)))
        .sort((a, b) => (b.year || 0) - (a.year || 0));
      if (!arr.length) return null;
      const e = arr[0];
      const rate = e.rate != null
        ? Number(e.rate)
        : (e.submitted ? e.accepted / e.submitted : null);
      if (rate == null || isNaN(rate)) return null;
      return { year: e.year, rate, pct: Math.round(rate * 100) };
    },
    acceptanceHistory(conf) {
      return (conf.acceptance || [])
        .filter(a => a && a.year)
        .sort((a, b) => (b.year || 0) - (a.year || 0))
        .map(a => {
          const rate = a.rate != null
            ? Number(a.rate)
            : (a.submitted ? a.accepted / a.submitted : null);
          return {
            year: a.year,
            submitted: a.submitted,
            accepted: a.accepted,
            rate,
            pct: rate != null && !isNaN(rate) ? Math.round(rate * 100) : null,
            track: a.track || null,
          };
        });
    },

    // Cap topic chips per card so a venue with 8 tags doesn't make a
    // 5-line chip row. Show first 4; the rest collapses to "+N".
    visibleTopics(conf) {
      return (conf.topics || []).slice(0, 4);
    },
    overflowTopicsCount(conf) {
      return Math.max(0, (conf.topics || []).length - 4);
    },

    // Same idea for the "Also open" pills: 2 visible + overflow indicator
    visibleSecondaryDeadlines(conf) {
      return this.secondaryDeadlines(conf).slice(0, 2);
    },
    overflowSecondaryCount(conf) {
      return Math.max(0, this.secondaryDeadlines(conf).length - 2);
    },
    orderedDeadlines(deadlines) {
      void this.countdownTick;
      return CT.cards.orderedDeadlines(deadlines, this.glossary);
    },

    toggleExpanded(id) {
      this.expanded[id] = !this.expanded[id];
    },

    // -------------------------------------------------------------------
    // Calendar modal — pure client-side. Opens a modal listing every
    // deadline. Each row offers three actions: open in Google Calendar,
    // open in Outlook (both new-tab quick-add URLs), or download a
    // single-event .ics. A "download all as bundle" button at the bottom
    // packages every deadline into one .ics for users who want everything.
    // -------------------------------------------------------------------
    downloadIcs(conf) {
      // Function name kept for backwards-compat with all callers that say
      // `@click="downloadIcs(conf)"`; it now opens the chooser modal.
      const deadlines = CT.ics.listDeadlines(conf);
      // Default selection: only the next gating submission deadline.
      const primary = CT.utils.nextSubmissionFor(conf);
      const primaryKey = primary && !primary.past
        ? `${primary.trackIndex}#${primary.roundIndex}#${primary.kind}`
        : (deadlines[0]?.key || null);
      const selected = {};
      if (primaryKey) selected[primaryKey] = true;
      this.calModal = { open: true, conf, deadlines, selected, bulkHint: '' };
    },
    closeCalModal() {
      this.calModal = { open: false, conf: null, deadlines: [], selected: {}, bulkHint: '' };
    },
    toggleCalDeadline(key) {
      if (this.calModal.selected[key]) delete this.calModal.selected[key];
      else this.calModal.selected[key] = true;
    },
    selectAllCalDeadlines() {
      const sel = {};
      this.calModal.deadlines.forEach(d => { sel[d.key] = true; });
      this.calModal.selected = sel;
    },
    clearCalSelection() { this.calModal.selected = {}; },
    selectedCalCount() {
      return Object.keys(this.calModal.selected).length;
    },
    _selectedCalDeadlines() {
      const sel = this.calModal.selected;
      return this.calModal.deadlines.filter(d => sel[d.key]);
    },
    // Bulk actions on the ticked set. With multiple picks, we can't actually
    // open N tabs reliably (browsers block 2nd+ popups), so for N>1 we fall
    // back to: download a bundled .ics + show an inline hint with the
    // calendar's "Import" link the user can drop the file on. For N==1 the
    // quick-add URL opens directly — always allowed because it's a single
    // popup triggered by a single user click.
    calGcalSelected() {
      const picks = this._selectedCalDeadlines();
      if (!picks.length) return;
      if (picks.length === 1) {
        const ev = CT.ics.buildEvent(this.calModal.conf, picks[0]);
        const url = CT.ics.gcalUrl(ev);
        if (url) window.open(url, '_blank', 'noopener');
        return;
      }
      // Multi-pick: bundle into one .ics and instruct the user where to
      // import it. (Google Calendar has no URL-based multi-event quick-add.)
      CT.ics.downloadFor(this.calModal.conf, Object.keys(this.calModal.selected));
      this.calModal.bulkHint = 'gcal';
    },
    calOutlookSelected() {
      const picks = this._selectedCalDeadlines();
      if (!picks.length) return;
      if (picks.length === 1) {
        const ev = CT.ics.buildEvent(this.calModal.conf, picks[0]);
        const url = CT.ics.outlookUrl(ev);
        if (url) window.open(url, '_blank', 'noopener');
        return;
      }
      CT.ics.downloadFor(this.calModal.conf, Object.keys(this.calModal.selected));
      this.calModal.bulkHint = 'outlook';
    },
    calIcsSelected() {
      const keys = Object.keys(this.calModal.selected);
      if (!keys.length) return;
      CT.ics.downloadFor(this.calModal.conf, keys);
      this.calModal.bulkHint = '';   // explicit .ics action — no extra hint needed
    },

    // -------------------------------------------------------------------
    // Popover
    // -------------------------------------------------------------------
    openPopover(event, kind, key) {
      event.stopPropagation();
      const content = CT.glossary.buildContent(this.glossary, kind, key);
      if (!content) return;
      this.popover.content = content;
      this.popover.anchor = event.currentTarget;
      this.popover.style = CT.glossary.positionFor(event.currentTarget);
      this.popover.open = true;
    },
    closePopover() {
      this.popover.open = false;
      this.popover.content = null;
      this.popover.anchor = null;
    },

    // -------------------------------------------------------------------
    // Side panel (map upcoming mode)
    // -------------------------------------------------------------------
    openSidePanel(conf) {
      // Single-conference case (user clicked an individual marker).
      this.sidePanel.confs = [conf];
      this.sidePanel.page = 0;
      this.sidePanel.title = `${conf.acronym} ${conf.year}`;
      this.sidePanel.open = true;
    },
    openSidePanelMulti(confs, locationLabel) {
      // Cluster-click case: multiple confs at the same coordinate. Sort by
      // next-deadline urgency so the most imminent ones land on page 1.
      const sorted = [...confs].sort((a, b) => {
        const ad = CT.utils.nextSubmissionFor(a).value?.valueOf() ?? Infinity;
        const bd = CT.utils.nextSubmissionFor(b).value?.valueOf() ?? Infinity;
        return ad - bd;
      });
      this.sidePanel.confs = sorted;
      this.sidePanel.page = 0;
      this.sidePanel.title = locationLabel
        ? `${locationLabel} · ${sorted.length} ${this.t('side.confsLabel')}`
        : `${sorted.length} ${this.t('side.confsLabel')}`;
      this.sidePanel.open = true;
    },
    closeSidePanel() {
      this.sidePanel.open = false;
      this.sidePanel.confs = [];
      this.sidePanel.page = 0;
      this.sidePanel.title = '';
    },
    sidePanelPageConfs() {
      const start = this.sidePanel.page * this.sidePanel.perPage;
      return this.sidePanel.confs.slice(start, start + this.sidePanel.perPage);
    },
    sidePanelTotalPages() {
      return Math.max(1, Math.ceil(this.sidePanel.confs.length / this.sidePanel.perPage));
    },
    sidePanelNextPage() {
      if (this.sidePanel.page + 1 < this.sidePanelTotalPages()) this.sidePanel.page++;
    },
    sidePanelPrevPage() {
      if (this.sidePanel.page > 0) this.sidePanel.page--;
    },

    // -------------------------------------------------------------------
    // Feedback modal (anonymous comments → backend log → weekly digest)
    // -------------------------------------------------------------------
    openFeedback() {
      this.feedback.open = true;
      this.feedback.sent = false;
      this.feedback.error = '';
    },
    closeFeedback() {
      this.feedback.open = false;
      this.feedback.error = '';
    },
    async submitFeedback() {
      const msg = (this.feedback.message || '').trim();
      if (!msg) {
        this.feedback.error = this.t('feedback.errEmpty');
        return;
      }
      this.feedback.sending = true;
      this.feedback.error = '';
      try {
        const resp = await fetch('/api/submit-feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: (this.feedback.name || '').trim(),
            category: this.feedback.category,
            message: msg,
            lang: this.lang,
          }),
        });
        const data = await resp.json().catch(() => ({ ok: false }));
        if (!resp.ok || !data.ok) {
          this.feedback.error = data.error || `HTTP ${resp.status}`;
          this.feedback.sending = false;
          return;
        }
        this.feedback.sent = true;
        // Clear so a second comment doesn't accidentally re-send the same one.
        this.feedback.message = '';
      } catch (e) {
        this.feedback.error = String(e);
      } finally {
        this.feedback.sending = false;
      }
    },

    // -------------------------------------------------------------------
    // Slack post template — generates the lab's #paper-channel announcement
    // block. Can be opened either from a conf card (auto-fills 学会, URL,
    // and the conf's deadlines into a picker) or from the global header
    // button (everything blank). Authors line is persisted to localStorage
    // so members don't retype their collaborators.
    // -------------------------------------------------------------------
    openSlackModal(conf) {
      const deadlines = conf ? CT.ics.listDeadlines(conf) : [];
      const primary = conf ? CT.utils.nextSubmissionFor(conf) : null;
      const primaryKey = primary && !primary.past
        ? `${primary.trackIndex}#${primary.roundIndex}#${primary.kind}`
        : (deadlines[0]?.key || '');
      const initialDeadline = deadlines.find(d => d.key === primaryKey);
      this.slackModal = {
        open: true,
        conf,
        deadlines,
        deadlineKey: primaryKey,
        deadlineText: initialDeadline ? initialDeadline.value.format('MMM Do, YYYY') : '',
        topic: '',
        venue: conf
          ? `${conf.acronym} ${conf.year}` +
            (CT.utils.i18nText(conf.name) ? ` — ${CT.utils.i18nText(conf.name)}` : '')
          : '',
        url: conf?.website || '',
        paperType: 'Conference Papers',
        authors: localStorage.getItem('ct-slack-authors') || '',
        abstract: '',
        copied: false,
        error: '',
      };
    },
    closeSlackModal() {
      this.slackModal.open = false;
    },
    // When the user picks a different deadline from the dropdown, update
    // the editable date field to match. They can still hand-edit the text.
    slackPickDeadline() {
      const k = this.slackModal.deadlineKey;
      const d = this.slackModal.deadlines.find(x => x.key === k);
      this.slackModal.deadlineText = d ? d.value.format('MMM Do, YYYY') : '';
    },
    // The actual formatted text — also used as live preview in the modal.
    slackText() {
      const sm = this.slackModal;
      return [
        `【締切】 ${sm.deadlineText || '(TBD)'}`,
        `【研究ネタ】${sm.topic}`,
        `【学会】${sm.venue}`,
        `【URL】${sm.url}`,
        `【論文タイプ】${sm.paperType}`,
        `【Authors】${sm.authors}`,
        `【Abst】${sm.abstract}`,
      ].join('\n');
    },
    async copySlackPost() {
      // Persist the Authors line so future opens auto-populate it.
      if (this.slackModal.authors) {
        localStorage.setItem('ct-slack-authors', this.slackModal.authors);
      }
      const text = this.slackText();
      try {
        await navigator.clipboard.writeText(text);
        this.slackModal.copied = true;
        this.slackModal.error = '';
        setTimeout(() => { this.slackModal.copied = false; }, 1800);
      } catch (e) {
        // Fallback for browsers/contexts without clipboard API permission:
        // create a temporary textarea, select, execCommand('copy').
        try {
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed'; ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          ta.remove();
          this.slackModal.copied = true;
          setTimeout(() => { this.slackModal.copied = false; }, 1800);
        } catch (e2) {
          this.slackModal.error = String(e);
        }
      }
    },

    // -------------------------------------------------------------------
    // First-visit hint
    // -------------------------------------------------------------------
    maybeShowHint() {
      if (localStorage.getItem('firstVisitHintDismissed') !== 'true') {
        // delay so the toast doesn't flash before the cards load
        setTimeout(() => { this.showHint = true; }, 1500);
      }
    },
    dismissHint() {
      this.showHint = false;
      localStorage.setItem('firstVisitHintDismissed', 'true');
    },

    toggleHowto() {
      this.showHowto = !this.showHowto;
      localStorage.setItem('ct-howto-dismissed', this.showHowto ? '0' : '1');
    },
    dismissHowto() {
      this.showHowto = false;
      localStorage.setItem('ct-howto-dismissed', '1');
    },

    // -------------------------------------------------------------------
    // Map summary text
    // -------------------------------------------------------------------
    mapSummary() {
      void this.lang;
      if (this.mapMode === 'history') {
        const cities = new Set(this.publications
          .filter(p => p.location)
          .map(p => `${p.location.lat?.toFixed(4)},${p.location.lng?.toFixed(4)}`));
        const fmt = {
          en: `${this.t('map.history')} — ${this.publications.length} paper${this.publications.length === 1 ? '' : 's'} in ${cities.size} cit${cities.size === 1 ? 'y' : 'ies'}`,
          zh: `${this.t('map.history')} — ${this.publications.length} 篇论文，分布在 ${cities.size} 个城市`,
          ja: `${this.t('map.history')} — ${this.publications.length} 件、${cities.size} 都市`,
        };
        return fmt[this.lang] || fmt.en;
      }
      const upcoming = this.filteredConferences().filter(c => !CT.utils.nextSubmissionFor(c).past);
      const fmt = {
        en: `${this.t('map.upcoming')} — ${upcoming.length} conference${upcoming.length === 1 ? '' : 's'} with active deadlines`,
        zh: `${this.t('map.upcoming')} — ${upcoming.length} 个会议正在开放投稿`,
        ja: `${this.t('map.upcoming')} — ${upcoming.length} 件の会議が投稿受付中`,
      };
      return fmt[this.lang] || fmt.en;
    },

    resultSummary() {
      void this.countdownTick; void this.lang;
      const total = this.conferences.length;
      const shown = this.filteredConferences().length;
      const fmt = {
        en: shown === total
          ? `${total} conference${total === 1 ? '' : 's'}`
          : `${shown} of ${total} conference${total === 1 ? '' : 's'}`,
        zh: shown === total ? `共 ${total} 个会议` : `${total} 个中显示 ${shown} 个`,
        ja: shown === total ? `全 ${total} 件` : `${total} 件中 ${shown} 件`,
      };
      return fmt[this.lang] || fmt.en;
    },
  };
};
