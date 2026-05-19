/* likes.js — floating 👍 button pinned to the bottom-right corner.
 *
 * Self-contained Alpine component used by both index.html and glossary.html.
 * One click per page load: the `liked` flag resets on every refresh so the
 * button becomes clickable again.
 *
 * Backend: a free third-party counter service (https://abacus.jasoncameron.dev)
 * because the site is served from GitHub Pages and has no backend of its own.
 * Namespace + key are URL-safe constants pinned to this site. The service
 * returns {"value": N} for both GET (just read) and HIT (increment + read).
 *
 * No PII is sent — Abacus only sees the namespace/key and the visitor IP.
 */
window.likeWidget = function () {
  const NAMESPACE = 'cs-conference-tracker';
  const KEY       = 'likes';
  const GET_URL   = `https://abacus.jasoncameron.dev/get/${NAMESPACE}/${KEY}`;
  const HIT_URL   = `https://abacus.jasoncameron.dev/hit/${NAMESPACE}/${KEY}`;

  return {
    count: null,             // null = unknown / fetch failed, number = loaded
    liked: false,            // per-page-load only; refresh resets
    pulse: false,            // triggers the +1 bump animation
    showThanks: false,       // ephemeral "thanks!" toast after a click
    _lang: (CT.i18n && CT.i18n.getLang()) || 'ja',

    init() {
      this.fetchCount();
    },

    t(key) {
      void this._lang;       // reactive dep so x-text re-reads on lang change
      return CT.i18n.t(key);
    },

    async fetchCount() {
      try {
        const r = await fetch(GET_URL);
        // Abacus returns 404 ("Key not found") until the very first HIT
        // creates the counter — treat that as "0 likes yet", not an error.
        if (r.status === 404) { this.count = 0; return; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        this.count = typeof j.value === 'number' ? j.value : 0;
      } catch (e) {
        // Counter service unreachable — show '—' rather than freaking out.
        this.count = null;
      }
    },

    async like() {
      if (this.liked) return; // one click per page load; refresh re-enables
      this.liked = true;
      // Optimistic bump so the click feels instant; the server response
      // overwrites with the authoritative total a moment later.
      if (typeof this.count === 'number') this.count += 1;
      this.pulse = true;
      setTimeout(() => { this.pulse = false; }, 600);
      this.showThanks = true;
      setTimeout(() => { this.showThanks = false; }, 2200);

      try {
        const r = await fetch(HIT_URL);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (typeof j.value === 'number') this.count = j.value;
      } catch (e) {
        // Failed to record — keep the optimistic state so the UI stays
        // responsive. Worst case the count just doesn't match the server.
      }
    },

    displayCount() {
      if (this.count === null) return '—';
      if (this.count >= 1000) return (this.count / 1000).toFixed(1) + 'k';
      return String(this.count);
    },
  };
};
