/* likes.js — floating 👍 button pinned to the bottom-right corner.
 *
 * Self-contained Alpine component used by both index.html and glossary.html.
 * One like per page load: the `liked` flag resets on every refresh so the
 * button becomes clickable again. The server throttles a /24 IP block to one
 * like every couple of seconds — that stops button-mashing scripts without
 * stopping a normal "refresh → click → see +1" cycle. When the backend isn't
 * reachable (e.g. static GitHub Pages deployment), the button still renders
 * but the counter stays at '—'.
 */
window.likeWidget = function () {
  return {
    count: null,             // null = unknown / offline, number = loaded
    liked: false,            // per-page-load only; refresh resets
    pulse: false,            // triggers the +1 bump animation
    showThanks: false,       // ephemeral "thanks!" toast after a click
    _lang: (CT.i18n && CT.i18n.getLang()) || 'en',

    init() {
      this.fetchCount();
    },

    t(key) {
      // re-read so x-text using t() picks up language changes elsewhere
      void this._lang;
      return CT.i18n.t(key);
    },

    async fetchCount() {
      try {
        const r = await fetch('/api/likes', { method: 'GET' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        this.count = typeof j.count === 'number' ? j.count : 0;
      } catch (e) {
        // Backend not reachable (offline / GitHub Pages). Keep button usable;
        // counter just stays as '—'.
        this.count = null;
      }
    },

    async like() {
      if (this.liked) return;       // one click per page load; refresh re-enables
      this.liked = true;
      // Optimistic bump so the click feels instant; the server response
      // overwrites with the authoritative total a moment later.
      if (typeof this.count === 'number') this.count += 1;
      this.pulse = true;
      setTimeout(() => { this.pulse = false; }, 600);
      this.showThanks = true;
      setTimeout(() => { this.showThanks = false; }, 2200);

      try {
        const r = await fetch('/api/likes', { method: 'POST' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (typeof j.count === 'number') this.count = j.count;
      } catch (e) {
        // Offline / no backend — keep the optimistic count + liked state so
        // the UI stays responsive.
      }
    },

    displayCount() {
      if (this.count === null) return '—';
      // Compact >= 1k as "1.2k" to keep the badge narrow
      if (this.count >= 1000) return (this.count / 1000).toFixed(1) + 'k';
      return String(this.count);
    },
  };
};
