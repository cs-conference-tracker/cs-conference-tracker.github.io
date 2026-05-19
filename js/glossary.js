/* =========================================================================
   glossary.js — Popover content builder + glossary page renderer.
   The popover DOM itself lives in index.html; this module supplies content
   given (kind, key) lookups against the loaded glossary data.
   ========================================================================= */

window.CT = window.CT || {};

CT.glossary = (function () {

  // Map the conference-entry ranking value (e.g. "A*", "A", "B", "C") to
  // its glossary key (e.g. "core_a_star").
  function rankingKey(system, value) {
    if (!value) return null;
    const v = String(value).toLowerCase();
    if (system === 'core') {
      if (v === 'a*') return 'core_a_star';
      if (v === 'a')  return 'core_a';
      if (v === 'b')  return 'core_b';
      if (v === 'c')  return 'core_c';
    }
    if (system === 'ccf') {
      if (v === 'a') return 'ccf_a';
      if (v === 'b') return 'ccf_b';
      if (v === 'c') return 'ccf_c';
    }
    if (system === 'thu') {
      if (v === 'a') return 'thu_a';
    }
    return null;
  }

  function buildContent(glossary, kind, key) {
    if (!glossary) return null;
    if (kind === 'topic') {
      const t = (glossary.topics || {})[key];
      if (!t) return null;
      const flagship = (t.flagship || []).join(', ');
      const itx = CT.utils.i18nText;
      const flagshipLabel = (CT.i18n && CT.i18n.t('popover.flagship')) || 'Flagship venues';
      return {
        titleKey: key,
        titleName: itx(t.full_name),
        subtitle: itx(t.category),
        description: itx(t.description),
        extra: flagship ? `${flagshipLabel}: ${CT.utils.escapeHtml(flagship)}` : '',
      };
    }
    if (kind === 'ranking') {
      const r = (glossary.rankings || {})[key];
      if (!r) return null;
      const itx = CT.utils.i18nText;
      const t = (k) => (CT.i18n && CT.i18n.t(k)) || k;
      let extra = r.source ? `${t('popover.source')}: ${CT.utils.escapeHtml(r.source)}` : '';
      if (r.url) {
        extra += `<br><a href="${CT.utils.escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">${t('popover.rankingPortal')}</a>`;
      }
      return {
        titleKey: r.short || key,
        titleName: itx(r.full),
        subtitle: '',
        description: itx(r.description),
        extra,
      };
    }
    if (kind === 'kind') {
      const lookup = key === 'rebuttal' ? 'rebuttal_start' : key;
      const k = (glossary.deadline_kinds || {})[lookup];
      if (!k) return null;
      const itx = CT.utils.i18nText;
      return {
        titleKey: itx(k.full) || lookup,
        titleName: '',
        subtitle: 'Deadline type',
        description: itx(k.description),
        extra: '',
      };
    }
    if (kind === 'concept') {
      const c = (glossary.concepts || {})[key];
      if (!c) return null;
      const itx = CT.utils.i18nText;
      return {
        titleKey: itx(c.full) || key,
        titleName: '',
        subtitle: 'Concept',
        description: itx(c.description),
        extra: '',
      };
    }
    if (kind === 'track_kind') {
      const [tkId, tkName] = String(key).split('|');
      const tk = (glossary.track_kinds || {})[tkId];
      const itx = CT.utils.i18nText;
      if (!tk) {
        const c = (glossary.concepts || {}).track;
        return c ? {
          titleKey: tkName || 'Track',
          titleName: '',
          subtitle: 'Submission track',
          description: itx(c.description),
          extra: '',
        } : null;
      }
      return {
        titleKey: tkName || itx(tk.full),
        titleName: '',
        subtitle: itx(tk.full),
        description: itx(tk.description),
        extra: '',
      };
    }
    return null;
  }

  // Position the popover relative to the trigger element.
  // Returns { style: {...} } suitable for x-bind:style.
  function positionFor(triggerEl) {
    if (!triggerEl) return { left: '50%', top: '50%' };
    const rect = triggerEl.getBoundingClientRect();
    const popWidth = 280;
    const popHeightEst = 180;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;

    // Mobile uses bottom-sheet via CSS @media; coordinates ignored
    if (vw <= 600) return { left: '0px', top: '0px' };

    let left = rect.left + scrollX;
    let top = rect.bottom + scrollY + 6;

    if (left + popWidth > vw + scrollX - 12) {
      left = Math.max(scrollX + 12, rect.right + scrollX - popWidth);
    }
    if (top + popHeightEst > vh + scrollY - 12) {
      top = rect.top + scrollY - popHeightEst - 6;
    }
    return { left: `${left}px`, top: `${top}px` };
  }

  return { rankingKey, buildContent, positionFor };
})();
