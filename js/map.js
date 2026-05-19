/* =========================================================================
   map.js — Leaflet setup, mode toggle, marker rendering, pulse markers.
   ========================================================================= */

window.CT = window.CT || {};

CT.map = (function () {

  let leafletMap = null;
  let layerGroup = null;
  let onMarkerSelect = null;   // callback set by app: (conf) => {}
  let onClusterSelect = null;  // callback set by app: (confs, label) => {}

  function rankSize(conf) {
    const r = conf.rankings || {};
    if (r.core === 'A*' || r.ccf === 'A') return 20;
    if (r.core === 'A')  return 16;
    if (r.core === 'B' || r.ccf === 'B') return 12;
    return 10;
  }

  function init(elementId) {
    if (leafletMap) return leafletMap;
    leafletMap = L.map(elementId, {
      center: [25, 30],
      zoom: 3,
      minZoom: 2,
      maxZoom: 18,
      worldCopyJump: true,
      zoomControl: true,
    });

    const osmAttr = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
    const cartoAttr = osmAttr + ' &copy; <a href="https://carto.com/attributions">CARTO</a>';
    const esriAttr = 'Tiles &copy; Esri &mdash; Source: Esri, Earthstar Geographics';

    const voyager = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
      { subdomains: 'abcd', maxZoom: 19, attribution: cartoAttr }
    );
    const darkMatter = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      { subdomains: 'abcd', maxZoom: 19, attribution: cartoAttr }
    );
    const positron = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      { subdomains: 'abcd', maxZoom: 19, attribution: cartoAttr }
    );
    const satellite = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { maxZoom: 18, attribution: esriAttr }
    );

    // Pick default based on user's color-scheme preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const defaultLayer = prefersDark ? darkMatter : voyager;
    defaultLayer.addTo(leafletMap);

    // Layer switcher placed bottom-left so the side-panel (right) and
    // popup-tooltips (which open above markers) can't be hidden by it.
    L.control.layers(
      {
        'Voyager': voyager,
        'Light (Positron)': positron,
        'Dark Matter': darkMatter,
        'Satellite': satellite,
      },
      null,
      { position: 'bottomleft', collapsed: true }
    ).addTo(leafletMap);

    // Live-switch base layer when the user toggles their OS dark mode
    try {
      window.matchMedia('(prefers-color-scheme: dark)')
        .addEventListener('change', e => {
          if (e.matches && !leafletMap.hasLayer(darkMatter)) {
            leafletMap.eachLayer(l => { if (l.options && l.options.subdomains === 'abcd') leafletMap.removeLayer(l); });
            darkMatter.addTo(leafletMap);
          } else if (!e.matches && !leafletMap.hasLayer(voyager)) {
            leafletMap.eachLayer(l => { if (l.options && l.options.subdomains === 'abcd') leafletMap.removeLayer(l); });
            voyager.addTo(leafletMap);
          }
        });
    } catch (_) { /* older browsers */ }

    return leafletMap;
  }

  function clearLayer() {
    if (layerGroup) {
      leafletMap.removeLayer(layerGroup);
      layerGroup = null;
    }
  }

  // -----------------------------------------------------------------------
  // Upcoming mode
  // -----------------------------------------------------------------------
  function renderUpcoming(conferences) {
    clearLayer();
    const cluster = L.markerClusterGroup({
      maxClusterRadius: 40,
      showCoverageOnHover: false,
      spiderfyOnMaxZoom: true,
      zoomToBoundsOnClick: false,    // we handle cluster clicks ourselves
    });

    conferences.forEach(conf => {
      if (!conf.location || conf.location.lat == null) return;
      const nd = CT.utils.nextSubmissionFor(conf);
      const urgency = nd.past ? 'past' : CT.utils.urgencyFor(nd.value);
      const size = rankSize(conf);

      const html = `
        <div class="marker-upcoming" data-urgency="${urgency}"
             style="width:${size}px;height:${size}px;">
          <div class="marker-circle" style="width:${size}px;height:${size}px;"></div>
        </div>`;
      const icon = L.divIcon({
        className: 'marker-upcoming-wrap',
        html,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      });

      const m = L.marker([conf.location.lat, conf.location.lng], {
        icon,
        title: `${conf.acronym} ${conf.year} — ${CT.utils.countdownLabel(nd.value)}`,
        keyboard: true,
        alt: `${conf.acronym} ${conf.year}, ${CT.utils.countdownLabel(nd.value)}`,
      });
      // Stash the conf on the marker so cluster-click can extract them.
      m._conf = conf;
      m.on('click', () => { if (onMarkerSelect) onMarkerSelect(conf); });
      cluster.addLayer(m);
    });

    // Override the default cluster behaviour (zoom-in) — open the side
    // panel with the paginated list of clustered confs instead. The map
    // doesn't move, the user doesn't lose context.
    cluster.on('clusterclick', e => {
      const childMarkers = e.layer.getAllChildMarkers();
      const confs = childMarkers.map(m => m._conf).filter(Boolean);
      if (!confs.length) return;
      // Build a location label from the first conf's city; if more than one
      // distinct city in this cluster (rare at small radius), join them.
      const cities = Array.from(new Set(
        confs.map(c => c.location?.city).filter(Boolean)
      ));
      const label = cities.length === 1 ? cities[0] : cities.join(', ');
      if (onClusterSelect) onClusterSelect(confs, label);
    });

    cluster.addTo(leafletMap);
    layerGroup = cluster;
  }

  // -----------------------------------------------------------------------
  // Lab papers mode (pulse markers, grouped by exact city coords)
  // -----------------------------------------------------------------------
  function renderHistory(publications) {
    clearLayer();
    const group = L.layerGroup();

    const byCity = {};
    publications.forEach(pub => {
      if (!pub.location || pub.location.lat == null) return;
      const key = `${pub.location.lat.toFixed(4)},${pub.location.lng.toFixed(4)}`;
      (byCity[key] ||= { loc: pub.location, papers: [] }).papers.push(pub);
    });

    Object.values(byCity).forEach(group2 => {
      const sortedPapers = [...group2.papers].sort((a, b) => (b.year || 0) - (a.year || 0));
      const html = `
        <div class="marker-pulse" aria-label="${CT.utils.escapeHtml(group2.loc.city)}, ${group2.papers.length} paper${group2.papers.length === 1 ? '' : 's'}">
          <svg width="40" height="40" viewBox="-20 -20 40 40">
            <circle class="pulse-ring r1" r="16"></circle>
            <circle class="pulse-ring r2" r="16"></circle>
            <circle class="pulse-ring r3" r="16"></circle>
            <circle class="pulse-core" r="3.5"></circle>
          </svg>
        </div>`;
      const icon = L.divIcon({
        className: 'marker-pulse-wrap',
        html,
        iconSize: [40, 40],
        iconAnchor: [20, 20],
      });
      const m = L.marker([group2.loc.lat, group2.loc.lng], {
        icon,
        keyboard: true,
        alt: `${group2.loc.city}, ${group2.papers.length} paper${group2.papers.length === 1 ? '' : 's'}`,
      });

      const popHtml = buildLabPopover(group2.loc, sortedPapers);
      m.bindPopup(popHtml, { className: 'lab-popover-wrap', maxWidth: 320 });
      group.addLayer(m);
    });

    group.addTo(leafletMap);
    layerGroup = group;
  }

  function buildLabPopover(loc, papers) {
    const esc = CT.utils.escapeHtml;
    const head = `<div class="lab-popover__head">${esc(loc.city)} · ${papers.length} paper${papers.length === 1 ? '' : 's'}</div>`;
    const body = papers.map(p => {
      const authors = (p.authors || []).slice(0, 4).join(', ') +
                      (p.authors && p.authors.length > 4 ? ', et al.' : '');
      const link = p.url
        ? `<a class="lab-paper__link" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">View paper ↗</a>`
        : '';
      return `
        <div class="lab-paper">
          <div class="lab-paper__title">${esc(p.title)}</div>
          <div class="lab-paper__venue">${esc(p.venue || '')}${p.year ? ' ' + p.year : ''}</div>
          <div class="lab-paper__authors">${esc(authors)}</div>
          ${link}
        </div>`;
    }).join('');
    return `<div class="lab-popover">${head}${body}</div>`;
  }

  function setSelectCallback(cb) { onMarkerSelect = cb; }
  function setClusterSelectCallback(cb) { onClusterSelect = cb; }

  function invalidate() {
    if (leafletMap) setTimeout(() => leafletMap.invalidateSize(), 50);
  }

  return {
    init,
    renderUpcoming,
    renderHistory,
    setSelectCallback,
    setClusterSelectCallback,
    invalidate,
    clearLayer,
  };
})();
