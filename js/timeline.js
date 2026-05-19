/* =========================================================================
   timeline.js — Horizontal Gantt-style view.
   Renders months across the top, one row per conference, deadline dots
   positioned by date. Conference event date is a wider neutral bar.
   ========================================================================= */

window.CT = window.CT || {};

CT.timeline = (function () {

  function render(mountId, conferences) {
    const mount = document.getElementById(mountId);
    if (!mount) return;
    mount.innerHTML = '';

    if (!conferences.length) {
      mount.innerHTML = '<p class="cards-empty">No conferences match.</p>';
      return;
    }

    const now = dayjs();
    const start = now.subtract(1, 'month').startOf('month');
    const end = start.add(12, 'month');
    const totalMs = end.diff(start);

    const NAME_COL = 140; // px
    const MONTH_COL = 70; // px
    const months = [];
    let cursor = start.clone();
    while (cursor.isBefore(end)) {
      months.push(cursor.clone());
      cursor = cursor.add(1, 'month');
    }

    const totalWidth = NAME_COL + months.length * MONTH_COL;

    const table = document.createElement('div');
    table.className = 'tl-table';
    table.style.gridTemplateColumns = `${NAME_COL}px repeat(${months.length}, ${MONTH_COL}px)`;
    table.style.width = `${totalWidth}px`;
    mount.appendChild(table);

    // Header row
    const headerCell = document.createElement('div');
    headerCell.className = 'tl-month tl-row-name';
    headerCell.textContent = '';
    table.appendChild(headerCell);
    months.forEach(m => {
      const cell = document.createElement('div');
      cell.className = 'tl-month';
      cell.textContent = m.format('MMM YYYY');
      table.appendChild(cell);
    });

    // Today indicator position
    const todayPct = (now.diff(start) / totalMs) * (months.length * MONTH_COL);

    conferences.forEach(conf => {
      const nameCell = document.createElement('div');
      nameCell.className = 'tl-row-name';
      nameCell.innerHTML = `${conf.acronym} <span style="color:var(--color-text-tertiary)">${conf.year}</span>`;
      table.appendChild(nameCell);

      const trackCell = document.createElement('div');
      trackCell.className = 'tl-row-track';
      trackCell.style.gridColumn = `span ${months.length}`;
      trackCell.style.position = 'relative';
      table.appendChild(trackCell);

      // Today line for this row
      if (todayPct >= 0 && todayPct <= months.length * MONTH_COL) {
        const line = document.createElement('div');
        line.className = 'tl-today';
        line.style.left = `${todayPct}px`;
        trackCell.appendChild(line);
      }

      // Conference event bar
      if (conf.dates && conf.dates.start) {
        const eStart = dayjs(conf.dates.start);
        const eEnd = dayjs(conf.dates.end || conf.dates.start);
        if (eEnd.isAfter(start) && eStart.isBefore(end)) {
          const xs = Math.max(0, (eStart.diff(start) / totalMs) * (months.length * MONTH_COL));
          const xe = Math.min(months.length * MONTH_COL, (eEnd.diff(start) / totalMs) * (months.length * MONTH_COL));
          const bar = document.createElement('div');
          bar.className = 'tl-event';
          bar.style.left = `${xs}px`;
          bar.style.width = `${Math.max(4, xe - xs)}px`;
          bar.title = `${conf.acronym} ${conf.year} — ${eStart.format('MMM D')}${eEnd.isSame(eStart, 'day') ? '' : '–' + eEnd.format('MMM D')}`;
          trackCell.appendChild(bar);
        }
      }

      // Deadline dots
      const dls = CT.utils.allDeadlines(conf);
      dls.forEach(d => {
        if (d.value.isBefore(start) || d.value.isAfter(end)) return;
        const x = (d.value.diff(start) / totalMs) * (months.length * MONTH_COL);
        const dot = document.createElement('div');
        const urgency = CT.utils.urgencyFor(d.value, now);
        dot.className = `tl-dot tl-dot--${urgency}`;
        dot.style.left = `${x}px`;
        dot.title = `${d.kind} (${d.trackName}${d.roundLabel ? ' — ' + d.roundLabel : ''}) — ${d.value.format('MMM D, YYYY')}`;
        trackCell.appendChild(dot);
      });
    });
  }

  return { render };
})();
