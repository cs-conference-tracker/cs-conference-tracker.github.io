/* =========================================================================
   ics.js — Client-side .ics file generation.
   One VEVENT per deadline across all tracks/rounds, zero-duration events.
   ========================================================================= */

window.CT = window.CT || {};

CT.ics = (function () {

  const PROD_ID = '-//Koshizuka Lab//CS Conference Tracker//EN';

  const KIND_LABELS = {
    abstract: 'Abstract',
    paper: 'Paper',
    rebuttal_start: 'Rebuttal start',
    rebuttal_end: 'Rebuttal end',
    commitment: 'ARR commitment',
    notification: 'Notification',
    camera_ready: 'Camera-ready',
    proposal: 'Proposal',
  };

  // Escape per RFC 5545
  function escapeIcsText(s) {
    return String(s ?? '')
      .replace(/\\/g, '\\\\')
      .replace(/;/g, '\\;')
      .replace(/,/g, '\\,')
      .replace(/\n/g, '\\n');
  }

  // Fold a line at 75 octets (we approximate by chars)
  function foldLine(line) {
    const out = [];
    while (line.length > 75) {
      out.push(line.slice(0, 75));
      line = ' ' + line.slice(75);
    }
    out.push(line);
    return out.join('\r\n');
  }

  // UTC stamp: YYYYMMDDTHHMMSSZ
  function utcStamp(d) {
    return d.utc().format('YYYYMMDD[T]HHmmss[Z]');
  }

  function generate(conf) {
    const lines = [
      'BEGIN:VCALENDAR',
      'VERSION:2.0',
      `PRODID:${PROD_ID}`,
      'CALSCALE:GREGORIAN',
      'METHOD:PUBLISH',
      `X-WR-CALNAME:${escapeIcsText(`${conf.acronym} ${conf.year} deadlines`)}`,
    ];

    const now = dayjs();
    const dtstamp = utcStamp(now);
    const locText = conf.location
      ? `${conf.location.city || ''}, ${conf.location.country || ''}`
      : '';

    (conf.tracks || []).forEach(track => {
      const trackSlug = CT.utils.slugify(track.name || 'track');
      (track.rounds || []).forEach((round, ri) => {
        const roundSlug = CT.utils.slugify(round.label || `round-${ri + 1}`);
        const ds = round.deadlines || {};
        Object.keys(ds).forEach(kind => {
          const deadline = CT.utils.parseDeadline(ds[kind]);
          if (!deadline) return;
          const kindLabel = KIND_LABELS[kind] || kind;
          const summary = `${conf.acronym} ${conf.year} — ${track.name}` +
                          (round.label ? ` ${round.label}` : '') +
                          ` ${kindLabel}`;
          const uid = `${conf.id}-${trackSlug}-${roundSlug}-${kind}@koshizuka-lab-tracker`;
          const description =
            `${conf.name}\\n` +
            (conf.website ? `${conf.website}\\n` : '') +
            `Track: ${track.name}` +
            (round.label ? ` (${round.label})` : '') +
            `\\nDeadline type: ${kindLabel}`;

          lines.push('BEGIN:VEVENT');
          lines.push(foldLine(`UID:${uid}`));
          lines.push(`DTSTAMP:${dtstamp}`);
          lines.push(`DTSTART:${utcStamp(deadline)}`);
          lines.push(`DTEND:${utcStamp(deadline)}`);
          lines.push(foldLine(`SUMMARY:${escapeIcsText(summary)}`));
          lines.push(foldLine(`DESCRIPTION:${escapeIcsText(description)}`));
          if (locText) lines.push(foldLine(`LOCATION:${escapeIcsText(locText)}`));
          if (conf.website) lines.push(foldLine(`URL:${conf.website}`));
          lines.push('END:VEVENT');
        });
      });
    });

    lines.push('END:VCALENDAR');
    return lines.join('\r\n') + '\r\n';
  }

  // Enumerate every (trackIndex, roundIndex, kind) deadline of a conf as
  // a flat array of selectable items. Used by the email modal to render
  // checkbox rows the user can pick from.
  function listDeadlines(conf) {
    const items = [];
    (conf.tracks || []).forEach((track, ti) => {
      (track.rounds || []).forEach((round, ri) => {
        const ds = round.deadlines || {};
        Object.keys(ds).forEach(kind => {
          const parsed = CT.utils.parseDeadline(ds[kind]);
          if (!parsed) return;
          items.push({
            trackIndex: ti,
            roundIndex: ri,
            kind,
            kindLabel: KIND_LABELS[kind] || kind,
            trackName: track.name || `Track ${ti + 1}`,
            roundLabel: round.label || (track.rounds.length > 1 ? `Round ${ri + 1}` : ''),
            value: parsed,
            key: `${ti}#${ri}#${kind}`,
          });
        });
      });
    });
    items.sort((a, b) => a.value.diff(b.value));
    return items;
  }

  // Produce an .ics containing only the deadlines whose key (trackIdx#
  // roundIdx#kind) is in `selectedKeys`. Falls back to generate(conf)
  // when selectedKeys is null/empty.
  function generateFor(conf, selectedKeys) {
    if (!selectedKeys || !selectedKeys.length) return generate(conf);
    const wanted = new Set(selectedKeys);
    const lines = [
      'BEGIN:VCALENDAR',
      'VERSION:2.0',
      `PRODID:${PROD_ID}`,
      'CALSCALE:GREGORIAN',
      'METHOD:REQUEST',
      `X-WR-CALNAME:${escapeIcsText(`${conf.acronym} ${conf.year} deadlines`)}`,
    ];
    const dtstamp = utcStamp(dayjs());
    const locText = conf.location
      ? `${conf.location.city || ''}, ${conf.location.country || ''}`.replace(/^, |, $/g, '')
      : '';
    (conf.tracks || []).forEach((track, ti) => {
      const trackSlug = CT.utils.slugify(track.name || 'track');
      (track.rounds || []).forEach((round, ri) => {
        const roundSlug = CT.utils.slugify(round.label || `round-${ri + 1}`);
        const ds = round.deadlines || {};
        Object.keys(ds).forEach(kind => {
          if (!wanted.has(`${ti}#${ri}#${kind}`)) return;
          const deadline = CT.utils.parseDeadline(ds[kind]);
          if (!deadline) return;
          const kindLabel = KIND_LABELS[kind] || kind;
          const summary = `${conf.acronym} ${conf.year} — ${track.name}` +
                          (round.label ? ` ${round.label}` : '') +
                          ` ${kindLabel}`;
          const uid = `${conf.id}-${trackSlug}-${roundSlug}-${kind}@koshizuka-lab-tracker`;
          const description =
            `${conf.name && (conf.name.en || conf.name)}\\n` +
            (conf.website ? `${conf.website}\\n` : '') +
            `Track: ${track.name}` +
            (round.label ? ` (${round.label})` : '') +
            `\\nDeadline type: ${kindLabel}`;
          // Deadline is a single moment; iCal events need start+end. Use
          // a one-hour window ending at the deadline so the event shows
          // up clearly on a calendar grid.
          const start = deadline.subtract(1, 'hour');
          lines.push('BEGIN:VEVENT');
          lines.push(foldLine(`UID:${uid}`));
          lines.push(`DTSTAMP:${dtstamp}`);
          lines.push(`DTSTART:${utcStamp(start)}`);
          lines.push(`DTEND:${utcStamp(deadline)}`);
          lines.push(foldLine(`SUMMARY:${escapeIcsText(summary)}`));
          lines.push(foldLine(`DESCRIPTION:${escapeIcsText(description)}`));
          if (locText) lines.push(foldLine(`LOCATION:${escapeIcsText(locText)}`));
          if (conf.website) lines.push(foldLine(`URL:${conf.website}`));
          lines.push('END:VEVENT');
        });
      });
    });
    lines.push('END:VCALENDAR');
    return lines.join('\r\n') + '\r\n';
  }

  function download(conf) {
    const content = generate(conf);
    triggerDownload(content, `${slug(conf.acronym)}-${conf.year}.ics`);
  }

  // Download only the picked deadlines as a single bundle .ics
  function downloadFor(conf, selectedKeys) {
    const content = generateFor(conf, selectedKeys);
    const suffix = selectedKeys && selectedKeys.length === 1 ? '-1' :
                   selectedKeys ? `-${selectedKeys.length}` : '';
    triggerDownload(content, `${slug(conf.acronym)}-${conf.year}${suffix}.ics`);
  }

  function triggerDownload(content, filename) {
    const blob = new Blob([content], { type: 'text/calendar;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
  }

  function slug(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-');
  }

  // ----------------------------------------------------------------------
  // Quick-add URL builders for Google Calendar + Outlook web.
  // Pure client-side — opening the returned URL in a new tab pre-fills
  // the create-event form in the user's chosen calendar.
  // ----------------------------------------------------------------------
  function _utcBasic(d) {
    return d ? d.utc().format('YYYYMMDD[T]HHmmss[Z]') : '';
  }
  function _utcDashed(d) {
    return d ? d.utc().format('YYYY-MM-DD[T]HH:mm:ss[Z]') : '';
  }

  // event = { title, deadline (dayjs), description, location }
  function gcalUrl(event) {
    const end = event.deadline;
    const start = end ? end.subtract(1, 'hour') : null;
    if (!start || !end) return '';
    const params = new URLSearchParams({
      action: 'TEMPLATE',
      text: event.title || 'Conference deadline',
      dates: `${_utcBasic(start)}/${_utcBasic(end)}`,
      details: event.description || '',
      location: event.location || '',
      sf: 'true',
      output: 'xml',
    });
    return `https://calendar.google.com/calendar/render?${params.toString()}`;
  }

  function outlookUrl(event) {
    const end = event.deadline;
    const start = end ? end.subtract(1, 'hour') : null;
    if (!start || !end) return '';
    const params = new URLSearchParams({
      path: '/calendar/action/compose',
      rru: 'addevent',
      subject: event.title || 'Conference deadline',
      body: event.description || '',
      location: event.location || '',
      startdt: _utcDashed(start),
      enddt: _utcDashed(end),
    });
    return `https://outlook.live.com/calendar/0/deeplink/compose?${params.toString()}`;
  }

  // Build the {title, description, location, deadline} payload for a single
  // (conf, deadline) pair so gcalUrl/outlookUrl can render their URLs.
  function buildEvent(conf, d) {
    const trackTag = d.trackName + (d.roundLabel ? ` · ${d.roundLabel}` : '');
    const title = `${conf.acronym} ${conf.year} — ${d.kindLabel} (${trackTag})`;
    const confName = CT.utils.i18nText(conf.name) || conf.acronym;
    const locStr = (conf.location
      ? [conf.location.city, conf.location.country].filter(Boolean).join(', ')
      : '') || 'TBD';
    return {
      deadline: d.value,
      title,
      description: `${confName}\n${conf.website || ''}\nDeadline (AoE): ${CT.utils.formatDeadlineAoE(d.value)}`,
      location: locStr,
    };
  }

  return {
    generate, generateFor, listDeadlines, download, downloadFor,
    gcalUrl, outlookUrl, buildEvent, KIND_LABELS,
  };
})();
