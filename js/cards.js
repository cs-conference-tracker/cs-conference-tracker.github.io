/* =========================================================================
   cards.js — Per-card derived helpers used by the Alpine template.
   Most card rendering happens in index.html; this module provides pure
   functions for computed values referenced from the template.
   ========================================================================= */

window.CT = window.CT || {};

CT.cards = (function () {

  const RANKING_DESCRIPTIONS = {
    'A*': 'A*', 'A': 'A', 'B': 'B', 'C': 'C',
  };

  function hasAnyRanking(conf) {
    const r = conf.rankings || {};
    return !!(r.core || r.ccf || r.thu);
  }

  function rankingChips(conf, glossary) {
    const r = conf.rankings || {};
    const chips = [];
    // Glossary `.full` is now an i18n object {en,zh,ja}; resolve it through
    // the helper, otherwise tooltips render as "[object Object]".
    const itx = CT.utils.i18nText;
    if (r.core) {
      const key = CT.glossary.rankingKey('core', r.core);
      const meta = (glossary?.rankings || {})[key] || {};
      chips.push({
        key,
        short: meta.short || `CORE ${r.core}`,
        tooltip: itx(meta.full) || `CORE Ranking — ${r.core}`,
      });
    }
    if (r.ccf) {
      const key = CT.glossary.rankingKey('ccf', r.ccf);
      const meta = (glossary?.rankings || {})[key] || {};
      chips.push({
        key,
        short: meta.short || `CCF ${r.ccf}`,
        tooltip: itx(meta.full) || `CCF Ranking — ${r.ccf}`,
      });
    }
    if (r.thu) {
      const key = CT.glossary.rankingKey('thu', r.thu);
      const meta = (glossary?.rankings || {})[key] || {};
      chips.push({
        key,
        short: meta.short || `THU ${r.thu}`,
        tooltip: itx(meta.full) || `THU CS Paper List — ${r.thu}`,
      });
    }
    return chips;
  }

  // Order deadlines within a round in a natural chronological / kind order.
  const KIND_ORDER = [
    'abstract', 'paper',
    'rebuttal_start', 'rebuttal_end',
    'commitment', 'notification', 'camera_ready', 'proposal',
  ];

  function orderedDeadlines(deadlines, glossary) {
    if (!deadlines) return [];
    const now = dayjs();
    const items = Object.keys(deadlines).map(kind => {
      const parsed = CT.utils.parseDeadline(deadlines[kind]);
      if (!parsed) return null;
      const past = parsed.isBefore(now);
      const urgency = past ? 'past' : CT.utils.urgencyFor(parsed, now);
      const kindLabel = CT.utils.i18nText(glossary?.deadline_kinds?.[kind]?.full) || prettyKind(kind);
      return {
        kind,
        kindLabel,
        value: parsed,
        when: CT.utils.formatDeadlineLocal(parsed),
        aoeTitle: 'AoE: ' + CT.utils.formatDeadlineAoE(parsed),
        urgency,
        past,
      };
    }).filter(Boolean);

    items.sort((a, b) => {
      const ka = KIND_ORDER.indexOf(a.kind);
      const kb = KIND_ORDER.indexOf(b.kind);
      if (ka !== -1 && kb !== -1 && ka !== kb) return ka - kb;
      return a.value.diff(b.value);
    });
    return items;
  }

  function prettyKind(k) {
    return k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function formatLocation(loc) {
    if (!loc) return '';
    return [loc.city, loc.country].filter(Boolean).join(', ');
  }

  // Map a free-form track name string ("Late-Breaking Work", "Applied Data
  // Science Track", "Workshop Proposals", etc.) to one of the canonical
  // track_kinds keys defined in glossary.yaml. Order matters — match the
  // most specific patterns first.
  function inferTrackKind(name) {
    const n = String(name || '').toLowerCase();
    if (/journal|tvcg|pvldb|pacm\s*hci|pacm\s*imwut|imwut(\s|$)/.test(n))   return 'journal';
    if (/vision|position|blue.?sky/.test(n))                                return 'vision';
    if (/late.?breaking|lbw|\bposter/.test(n))                              return 'posters';
    if (/demo|demonstration|interactive\s*demo/.test(n))                    return 'demos';
    if (/tutorial/.test(n))                                                 return 'tutorials';
    if (/doctoral|phd\s*forum|consortium|colloquium|symposium/.test(n))     return 'doctoral';
    if (/industr|applied\s*data\s*science|\bads\b|applications?\s*track|deployed|practice\s*track/.test(n)) return 'industry';
    if (/special\s*(session|track)|resource\s*track|reproducibility/.test(n)) return 'special';
    if (/wip\b|work[\s-]?in[\s-]?progress|short\s*paper|fast\s*abstract/.test(n)) return 'wip';
    if (/student.*(competition|innovation|forum)|innovation\s*contest|src\b/.test(n)) return 'src';
    if (/panel|meet.?up|birds\s*of\s*a\s*feather|real.?time\s*live|emerging\s*tech/.test(n)) return 'panel';
    if (/workshop/.test(n))                                                 return 'workshops';
    if (/paper|research|main|technical|full|conference|symposia/.test(n))   return 'papers';
    return 'papers';   // default: treat unknown tracks as main papers
  }

  return {
    hasAnyRanking,
    rankingChips,
    orderedDeadlines,
    formatLocation,
    inferTrackKind,
  };
})();
