/* =========================================================================
   utils.js — Date formatting, URL state, dayjs helpers, slugify.
   ========================================================================= */

window.CT = window.CT || {};

CT.utils = (function () {

  const AOE_OFFSET = '-12:00';

  // -----------------------------------------------------------------------
  // Date parsing & formatting
  // -----------------------------------------------------------------------

  // Accepts ISO 8601 string. Date-only values (`2026-04-15`) are treated as
  // 23:59:59 AoE per spec §4.1.
  function parseDeadline(value) {
    if (!value) return null;
    if (typeof value !== 'string') {
      // YAML may parse short dates as JS Date objects
      if (value instanceof Date) {
        const iso = value.toISOString().slice(0, 10);
        return dayjs(iso + 'T23:59:59' + AOE_OFFSET);
      }
      return null;
    }
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
    const str = dateOnly ? `${value}T23:59:59${AOE_OFFSET}` : value;
    const d = dayjs(str);
    return d.isValid() ? d : null;
  }

  function urgencyFor(deadline, now) {
    if (!deadline) return 'past';
    now = now || dayjs();
    if (deadline.isBefore(now)) return 'past';
    const days = deadline.diff(now, 'day', true);
    if (days < 7) return 'danger';
    if (days < 30) return 'warning';
    return 'success';
  }

  // Precise to-the-second countdown: "Xd Yh Zm Ws left"
  // Components with leading zeros are dropped (e.g. "12h 5m 3s left" when days==0).
  function countdownLabel(deadline, now) {
    if (!deadline) return 'Past';
    now = now || dayjs();
    const diffMs = deadline.diff(now);
    if (diffMs <= 0) return 'Past';

    const totalSeconds = Math.floor(diffMs / 1000);
    const days  = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const mins  = Math.floor((totalSeconds % 3600) / 60);
    const secs  = totalSeconds % 60;

    const parts = [];
    if (days  > 0) parts.push(`${days}d`);
    if (days  > 0 || hours > 0) parts.push(`${String(hours).padStart(2, '0')}h`);
    if (days  > 0 || hours > 0 || mins > 0) parts.push(`${String(mins).padStart(2, '0')}m`);
    parts.push(`${String(secs).padStart(2, '0')}s`);
    return parts.join(' ') + ' left';
  }

  // "Feb 8, 2026 18:00 JST" — display in user's local zone
  function formatDeadlineLocal(deadline) {
    if (!deadline) return '';
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const localized = deadline.tz(tz);
    const abbr = tzAbbr(tz, localized);
    return `${localized.format('MMM D, YYYY HH:mm')} ${abbr}`;
  }

  function formatDeadlineAoE(deadline) {
    if (!deadline) return '';
    return deadline.utcOffset(-12 * 60).format('MMM D, YYYY HH:mm') + ' AoE';
  }

  // Cheap timezone abbreviation. Intl gives long names; we want short.
  function tzAbbr(tz, dayjsInstance) {
    try {
      const dtf = new Intl.DateTimeFormat('en-US', {
        timeZone: tz,
        timeZoneName: 'short',
      });
      const parts = dtf.formatToParts(dayjsInstance.toDate());
      const tznPart = parts.find(p => p.type === 'timeZoneName');
      return tznPart ? tznPart.value : '';
    } catch {
      return '';
    }
  }

  function formatConferenceDates(conf) {
    if (!conf.dates || !conf.dates.start) return '';
    const s = dayjs(conf.dates.start);
    const e = conf.dates.end ? dayjs(conf.dates.end) : null;
    if (!e || s.isSame(e, 'day')) return s.format('MMM D, YYYY');
    if (s.month() === e.month() && s.year() === e.year()) {
      return `${s.format('MMM D')}–${e.format('D, YYYY')}`;
    }
    if (s.year() === e.year()) {
      return `${s.format('MMM D')} – ${e.format('MMM D, YYYY')}`;
    }
    return `${s.format('MMM D, YYYY')} – ${e.format('MMM D, YYYY')}`;
  }

  // Aggregate every deadline across a conference's tracks/rounds.
  function allDeadlines(conf) {
    const out = [];
    (conf.tracks || []).forEach((track, ti) => {
      (track.rounds || []).forEach((round, ri) => {
        const ds = round.deadlines || {};
        Object.keys(ds).forEach(kind => {
          const parsed = parseDeadline(ds[kind]);
          if (parsed) out.push({
            kind,
            value: parsed,
            trackName: track.name,
            trackIndex: ti,
            roundLabel: round.label,
            roundIndex: ri,
            hasRebuttal: !!track.has_rebuttal,
          });
        });
      });
    });
    return out;
  }

  function nextDeadlineFor(conf, now) {
    now = now || dayjs();
    const future = allDeadlines(conf)
      .filter(d => d.value.isAfter(now))
      .sort((a, b) => a.value.diff(b.value));
    if (future.length === 0) {
      // All past — return the latest past deadline for "Past" display
      const all = allDeadlines(conf).sort((a, b) => b.value.diff(a.value));
      return all.length ? { ...all[0], past: true } : { past: true, value: null };
    }
    return { ...future[0], past: false };
  }

  // Per-round submission deadline: abstract if present (it's the controlling
  // gate — miss it and you cannot submit the paper), else paper. Anything
  // after a submission deadline closes is "no longer submittable" for that
  // round, even if notification/camera-ready are still in the future.
  function submissionDeadlinesFor(conf) {
    const out = [];
    (conf.tracks || []).forEach((track, ti) => {
      (track.rounds || []).forEach((round, ri) => {
        const ds = round.deadlines || {};
        const kind = ds.abstract != null ? 'abstract'
                   : ds.paper    != null ? 'paper'
                   : ds.proposal != null ? 'proposal'
                   : null;
        if (!kind) return;
        const parsed = parseDeadline(ds[kind]);
        if (!parsed) return;
        out.push({
          kind,
          value: parsed,
          trackName: track.name,
          trackIndex: ti,
          roundLabel: round.label,
          roundIndex: ri,
        });
      });
    });
    return out;
  }

  // The headline deadline for a conference card: ONLY the main track's
  // (tracks[0]) soonest still-open submission. If the main track is fully
  // closed, the pill shows "Closed" — secondary deadlines from other tracks
  // still surface in the "Also open" row so the user can see they're alive.
  function nextSubmissionFor(conf, now) {
    now = now || dayjs();
    const all = submissionDeadlinesFor(conf);
    const main = all.filter(d => d.trackIndex === 0);

    const mainUpcoming = main
      .filter(d => d.value.isAfter(now))
      .sort((a, b) => a.value.diff(b.value));
    if (mainUpcoming.length > 0) {
      return { ...mainUpcoming[0], past: false };
    }
    if (main.length > 0) {
      const mainPast = [...main].sort((a, b) => b.value.diff(a.value));
      return { ...mainPast[0], past: true };
    }
    // Conference has no main track with submission kinds at all (rare —
    // e.g. an entry with only workshop proposals). Fall back to any deadline.
    const anyUpcoming = all
      .filter(d => d.value.isAfter(now))
      .sort((a, b) => a.value.diff(b.value));
    if (anyUpcoming.length > 0) return { ...anyUpcoming[0], past: false };
    const anyPast = [...all].sort((a, b) => b.value.diff(a.value));
    return anyPast.length ? { ...anyPast[0], past: true } : { past: true, value: null };
  }

  // -----------------------------------------------------------------------
  // URL state
  // -----------------------------------------------------------------------
  function parseUrlState() {
    const hash = window.location.hash.replace(/^#/, '');
    const params = new URLSearchParams(hash);
    const state = {};
    if (params.has('view')) state.view = params.get('view');
    if (params.has('q'))    state.q = params.get('q');
    if (params.has('topics')) state.topics = params.get('topics').split(',').filter(Boolean);
    if (params.has('ranks')) state.ranks = params.get('ranks').split(',').filter(Boolean);
    if (params.has('rank')) state.rank = params.get('rank');
    if (params.has('sort')) state.sort = params.get('sort');
    if (params.has('mode')) state.mapMode = params.get('mode');
    if (params.has('lang')) state.lang = params.get('lang');
    return state;
  }

  function writeUrlState(state) {
    const params = new URLSearchParams();
    if (state.view && state.view !== 'cards') params.set('view', state.view);
    if (state.q) params.set('q', state.q);
    if (state.topics && state.topics.length) params.set('topics', state.topics.join(','));
    if (state.ranks && state.ranks.length) params.set('ranks', state.ranks.join(','));
    if (state.sort && state.sort !== 'next-ddl') params.set('sort', state.sort);
    if (state.view === 'map' && state.mapMode) params.set('mode', state.mapMode);
    if (state.lang && state.lang !== 'en') params.set('lang', state.lang);
    const str = params.toString();
    // Use replaceState to avoid polluting back history with every keystroke
    const newHash = str ? '#' + str : '';
    if (window.location.hash !== newHash) {
      history.replaceState(null, '', window.location.pathname + window.location.search + newHash);
    }
  }

  // -----------------------------------------------------------------------
  // Misc
  // -----------------------------------------------------------------------
  function slugify(s, maxLen = 60) {
    return String(s || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, maxLen);
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Resolve a string-or-{en,zh,ja} value down to a string for the current
  // UI language. Either a flat string (legacy / English-only) or an object
  // with locale keys is accepted; missing locales fall back to en. The lang
  // argument is taken from CT.i18n at call time so callers don't have to
  // thread it through.
  function i18nText(value) {
    if (value == null) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'object') {
      const lang = (window.CT && CT.i18n) ? CT.i18n.getLang() : 'en';
      return value[lang] || value.en || value.zh || value.ja || '';
    }
    return String(value);
  }

  return {
    AOE_OFFSET,
    parseDeadline,
    i18nText,
    urgencyFor,
    countdownLabel,
    formatDeadlineLocal,
    formatDeadlineAoE,
    formatConferenceDates,
    allDeadlines,
    nextDeadlineFor,
    submissionDeadlinesFor,
    nextSubmissionFor,
    parseUrlState,
    writeUrlState,
    slugify,
    escapeHtml,
  };
})();
