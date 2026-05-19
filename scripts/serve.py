#!/usr/bin/env python3
"""serve.py — unified static server + /api/send-calendar email endpoint.

Replaces `python3 -m http.server 8000`. Serves the repo root as static
files AND exposes ONE POST endpoint:

    POST /api/send-calendar
    body: {"to": "user@example.com", "ics": "BEGIN:VCALENDAR...",
           "subject": "...", "body": "...", "filename": "cvpr-2026.ics"}
    -> {"ok": true} or {"ok": false, "error": "..."}

Sends a multipart email with the .ics attached, via the SMTP server
configured in mail_config.json at the repo root. Designed for QQ Mail
out of the box (smtp.qq.com:465 SSL with an authorization code) but any
SMTP host with login auth works.

To configure:
  1. Copy mail_config.example.json -> mail_config.json
  2. Fill in your QQ email + SMTP authorization code (NOT your QQ login
     password — generate the code at https://service.mail.qq.com/detail/0/75)
  3. Run:  python3 scripts/serve.py 8000

mail_config.json is gitignored — never commit credentials.
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import os
import smtplib
import ssl
import sys
import traceback
from email.message import EmailMessage
from http.server import HTTPServer, ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent

# Credentials MUST live outside the served web root — the static file
# handler below would happily serve any path under ROOT, including any
# `mail_config.json` left there, leaking the SMTP authorization code to
# anyone on the network. Order of precedence:
#   1. $CT_MAIL_CONFIG env var (explicit path)
#   2. ~/.ct_mail_config.json (default, outside the web root)
# A path inside ROOT is refused with an error to prevent footguns.
def _config_path() -> Path:
    p = Path(os.environ.get("CT_MAIL_CONFIG") or (Path.home() / ".ct_mail_config.json"))
    return p.resolve()


def load_config():
    """Read the mail config from outside the served directory. Returns None
    if missing — the handler then refuses sends with a clear error so the
    frontend can surface it."""
    p = _config_path()
    # Refuse to read anything inside ROOT — that file would also be served
    # by the static handler below, which would leak credentials.
    try:
        p.relative_to(ROOT)
        sys.stderr.write(
            f"[serve] REFUSING to load credentials from {p}: path is inside "
            f"the served web root {ROOT}. Move the file outside ROOT (default: "
            f"~/.ct_mail_config.json) or set CT_MAIL_CONFIG to a safe path.\n"
        )
        return None
    except ValueError:
        pass  # not under ROOT — good
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[serve] {p} is malformed: {e}\n")
        return None


# Defence-in-depth: even if a future maintainer drops a credentials file
# into the repo, the static handler should refuse to serve it.
_FORBIDDEN_NAMES = {"mail_config.json", ".ct_mail_config.json", "comments.jsonl", ".ct_comments.jsonl", "likes.json", ".ct_likes.json"}


# Likes counter — single integer kept in a JSON file outside the web root.
# Crude per-IP-block daily rate limit (in-memory) prevents trivial spam from a
# single browser hammering the endpoint; the localStorage check on the frontend
# is the primary one-per-user gate, this is just belt-and-suspenders.
def _likes_path() -> Path:
    p = Path(os.environ.get("CT_LIKES_FILE") or (Path.home() / ".ct_likes.json"))
    return p.resolve()


_LIKES_LOCK_RECENT: dict[str, float] = {}   # ip_block -> monotonic ts of last like
_LIKES_THROTTLE_SECONDS = 2.0                # min gap between accepted likes from one /24


def _read_likes_count() -> int:
    p = _likes_path()
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data.get("count", 0))
    except Exception:
        return 0


def _write_likes_count(n: int) -> None:
    p = _likes_path()
    # Refuse to write inside ROOT (mirrors other path-safety checks).
    try:
        p.relative_to(ROOT)
        sys.stderr.write(f"[serve] REFUSING to write likes to {p}: inside web root.\n")
        return
    except ValueError:
        pass
    p.write_text(json.dumps({"count": int(n)}), encoding="utf-8")


# Feedback / comment journal — append-only file outside the web root. Each
# line is one JSON object. Every submission ALSO triggers an immediate email
# to the maintainer (via _send_feedback_email); the journal + weekly digest
# script are kept as a backup in case SMTP is temporarily down.
def _feedback_path() -> Path:
    p = Path(os.environ.get("CT_FEEDBACK_LOG") or (Path.home() / ".ct_comments.jsonl"))
    return p.resolve()


# Where each feedback notification is sent. Read from $CT_FEEDBACK_RECIPIENT
# at startup so the maintainer's mailbox never lives in the repo. If unset,
# notifications are skipped (still appended to the journal file — the weekly
# digest script can ship them later).
_FEEDBACK_RECIPIENT = (os.environ.get("CT_FEEDBACK_RECIPIENT") or "").strip()

_FEEDBACK_CATEGORY_LABELS = {
    "bug":        "🐛 Bug",
    "feature":    "✨ Feature request",
    "conference": "🎓 Conference suggestion",
    "other":      "💬 Other",
}


def _send_feedback_email(entry: dict) -> None:
    """Send a single feedback entry as an email. Raises on any SMTP error so
    the caller can decide whether to surface it (we don't — the journal file
    is the source of truth and the weekly digest acts as a backup)."""
    if not _FEEDBACK_RECIPIENT:
        # No recipient configured — entry stays in journal; weekly digest
        # script (also env-driven) can ship it later. Silent no-op.
        return
    cfg = load_config()
    if not cfg:
        raise RuntimeError("mail config missing — cannot send feedback email")

    cat_label = _FEEDBACK_CATEGORY_LABELS.get(entry.get("category", "other"), "💬 Other")
    name = entry.get("name") or "(anonymous)"
    subject = f"[CT Feedback] {cat_label} from {name}"
    # Stamp + crude origin info goes in the body, not the subject — keeps the
    # subject line short and grep-able.
    plain = (
        f"Time: {entry.get('ts', '')}\n"
        f"From: {name}\n"
        f"Category: {cat_label}\n"
        f"Lang: {entry.get('lang') or '(unspecified)'}\n"
        f"IP block: {entry.get('ip_block') or '(unknown)'}\n"
        f"\n"
        f"{entry.get('message', '')}\n"
    )
    esc = _html.escape
    html = (
        "<!doctype html>"
        "<html><body style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
        "max-width:600px;margin:0 auto;padding:20px;color:#0f172a\">"
        f"<h2 style=\"font-size:16px;margin:0 0 12px;color:#1e293b\">{esc(cat_label)} from {esc(name)}</h2>"
        f"<p style=\"color:#64748b;font-size:12px;margin:0 0 14px\">"
        f"{esc(entry.get('ts', ''))} &middot; lang={esc(entry.get('lang') or '?')} &middot; "
        f"ip={esc(entry.get('ip_block') or '?')}</p>"
        "<div style=\"border-left:3px solid #cbd5e1;padding:10px 14px;background:#f8fafc;border-radius:4px;"
        "white-space:pre-wrap;word-wrap:break-word;font-size:14px;line-height:1.5\">"
        f"{esc(entry.get('message', ''))}</div>"
        "</body></html>"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    from_name = cfg.get("from_name") or "CS Conference Tracker"
    msg["From"] = f"{from_name} <{cfg['from_addr']}>"
    msg["To"] = _FEEDBACK_RECIPIENT
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    host = cfg.get("smtp_host", "smtp.qq.com")
    port = int(cfg.get("smtp_port", 465))
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo(); s.starttls(context=ctx); s.ehlo()
            s.login(user, password)
            s.send_message(msg)
    sys.stderr.write(f"[serve] feedback email sent to {_FEEDBACK_RECIPIENT}\n")


# ---------------------------------------------------------------------------
# Email body rendering
# ---------------------------------------------------------------------------
def _gcal_url(event: dict) -> str:
    """Build a Google Calendar quick-add URL.

    Format: https://calendar.google.com/calendar/render?action=TEMPLATE
        &text=...&dates=YYYYMMDDTHHMMSSZ/YYYYMMDDTHHMMSSZ&details=...&location=...

    `dates` is two UTC timestamps in the basic ISO format separated by '/'.
    Frontend passes start_utc / end_utc already formatted that way.
    """
    title = event.get("title") or "Conference deadline"
    start = event.get("start_utc") or ""
    end = event.get("end_utc") or start
    details = event.get("description") or ""
    location = event.get("location") or ""
    if not start:
        return ""
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(title)}"
        f"&dates={start}/{end}"
        f"&details={quote(details)}"
        f"&location={quote(location)}"
        "&sf=true&output=xml"
    )


def _outlook_url(event: dict) -> str:
    """Build an Outlook.com calendar quick-add URL.

    Outlook expects local-time ISO datetimes. We pass the UTC stamp as-is
    with the trailing Z stripped — Outlook web will interpret it as UTC.
    """
    title = event.get("title") or "Conference deadline"
    details = event.get("description") or ""
    location = event.get("location") or ""
    # Convert YYYYMMDDTHHMMSSZ -> YYYY-MM-DDTHH:MM:SSZ for Outlook
    def fmt(s: str) -> str:
        if not s or len(s) < 16:
            return s
        return f"{s[0:4]}-{s[4:6]}-{s[6:11]}:{s[11:13]}:{s[13:]}"
    start = fmt(event.get("start_utc") or "")
    end = fmt(event.get("end_utc") or start)
    if not start:
        return ""
    return (
        "https://outlook.live.com/calendar/0/deeplink/compose"
        "?path=%2Fcalendar%2Faction%2Fcompose"
        "&rru=addevent"
        f"&subject={quote(title)}"
        f"&startdt={quote(start)}"
        f"&enddt={quote(end)}"
        f"&body={quote(details)}"
        f"&location={quote(location)}"
    )


def _render_bodies(plain_text: str, events: list, to_addr: str) -> tuple[str, str]:
    """Return (plain_text_body, html_body). Both bodies include one
    Google-Calendar and one Outlook quick-add link per event in `events`
    so the user can add multiple selected deadlines from one email."""
    # Plain-text body lists each event with its two URLs underneath.
    plain_lines = [plain_text or "Calendar event attached."]
    for ev in events or []:
        gcal = _gcal_url(ev)
        outl = _outlook_url(ev)
        title = ev.get("title") or "Deadline"
        plain_lines.append(f"\n— {title}")
        if gcal:
            plain_lines.append(f"  Google: {gcal}")
        if outl:
            plain_lines.append(f"  Outlook: {outl}")
    plain_body = "\n".join(plain_lines) + "\n"

    # HTML body — minimal inline-styled card-per-event layout. Tables
    # avoided so QQ Mail, Gmail web, Outlook desktop all render the same.
    safe_intro = _html.escape(plain_text or "Calendar event attached.").replace("\n", "<br>")
    event_blocks = []
    for ev in events or []:
        gcal = _gcal_url(ev)
        outl = _outlook_url(ev)
        title = _html.escape(ev.get("title") or "Deadline")
        when_local = _html.escape(ev.get("when_label") or "")
        loc = _html.escape(ev.get("location") or "")
        meta = " · ".join(s for s in (when_local, loc) if s)
        meta_html = (
            f'<div style="color:#666;font-size:12px;margin:2px 0 10px;">{meta}</div>'
            if meta else ""
        )
        btns = []
        if gcal:
            btns.append(
                f'<a href="{gcal}" '
                'style="display:inline-block;padding:9px 16px;margin:0 6px 6px 0;'
                'background:#1a73e8;color:#fff;text-decoration:none;border-radius:5px;'
                'font-weight:500;font-size:13px;">＋ Google Calendar</a>'
            )
        if outl:
            btns.append(
                f'<a href="{outl}" '
                'style="display:inline-block;padding:9px 16px;margin:0 6px 6px 0;'
                'background:#0078d4;color:#fff;text-decoration:none;border-radius:5px;'
                'font-weight:500;font-size:13px;">＋ Outlook</a>'
            )
        event_blocks.append(
            '<div style="border:1px solid #e5e5e5;border-radius:8px;padding:14px 16px;'
            'margin:10px 0;background:#fafafa;">'
            f'<div style="font-weight:600;font-size:14px;color:#111;margin-bottom:2px;">{title}</div>'
            f'{meta_html}{"".join(btns)}'
            '</div>'
        )
    events_section = "".join(event_blocks) or (
        '<p style="color:#888;font-size:12px;">'
        "Open the attached .ics file to import these events into your calendar.</p>"
    )
    return plain_body, (
        '<!doctype html><html><body style="margin:0;padding:18px;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'font-size:14px;line-height:1.55;color:#1a1a1a;background:#fff;">'
        '<div style="max-width:600px;margin:0 auto;">'
        f'<p style="margin:0 0 14px;">{safe_intro}</p>'
        f'{events_section}'
        '<p style="color:#888;font-size:11px;margin:18px 0 0;">'
        "The .ics file with all selected events is also attached as fallback.</p>"
        '</div></body></html>'
    )


class Handler(SimpleHTTPRequestHandler):
    # Pin the directory so the server can be launched from anywhere.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[serve] {self.address_string()} {fmt % args}\n")

    def do_GET(self):
        if self.path.split("?")[0] == "/api/likes":
            return self._json(200, {"ok": True, "count": _read_likes_count()})
        # Block credential-bearing filenames even if someone drops them
        # into the served directory. Belt-and-suspenders alongside the
        # _config_path() check.
        name = self.path.lstrip("/").split("?")[0].rsplit("/", 1)[-1]
        if name in _FORBIDDEN_NAMES:
            sys.stderr.write(f"[serve] blocked GET of sensitive file: {self.path}\n")
            self.send_error(403, "forbidden")
            return
        super().do_GET()

    # --- small JSON helpers ---------------------------------------------
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Permissive CORS — same-origin usage is the default, this just
        # allows curl / dev tooling against the endpoint from another tab.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # CORS pre-flight (only relevant if someone serves the static site
        # from a different origin). Mirrors the headers we accept.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # --- POST router -----------------------------------------------------
    def do_POST(self):
        # /api/send-calendar removed — calendar buttons are now client-side
        # (Google Calendar / Outlook quick-add URLs + .ics file download)
        # so the site can be hosted on GitHub Pages without a backend.
        if self.path == "/api/submit-feedback":
            return self._handle_submit_feedback()
        if self.path == "/api/likes":
            return self._handle_like()
        self.send_error(404, "Not Found")

    def _handle_like(self) -> None:
        """Increment the global like counter and return the new total.

        Each page-refresh-then-click should be accepted (the frontend resets
        its `liked` flag on every load), so the only gate here is a short
        per-/24 burst limit. That blocks button-mashing scripts without
        stopping a human refreshing a few times. Concurrency: HTTPServer is
        threaded, so the read-modify-write is best-effort under high load.
        """
        import time as _time
        ip = self.client_address[0] if self.client_address else ""
        if ":" in ip:
            ip_block = ":".join(ip.split(":")[:4]) + "::/64"
        else:
            ip_block = ".".join(ip.split(".")[:3]) + ".0/24"
        now = _time.monotonic()
        last = _LIKES_LOCK_RECENT.get(ip_block, 0.0)
        if now - last < _LIKES_THROTTLE_SECONDS:
            return self._json(200, {"ok": True, "count": _read_likes_count(), "throttled": True})

        try:
            current = _read_likes_count()
            new_count = current + 1
            _write_likes_count(new_count)
            _LIKES_LOCK_RECENT[ip_block] = now
            sys.stderr.write(f"[serve] like #{new_count} from {ip_block}\n")
            return self._json(200, {"ok": True, "count": new_count})
        except Exception as e:
            sys.stderr.write(f"[serve] like failed: {e}\n")
            return self._json(500, {"ok": False, "error": "could not record like"})

    def _handle_submit_feedback(self) -> None:
        """Append a single feedback entry to the journal file.

        Frontend POSTs JSON: {name?, category, message}. We attach a
        server-side timestamp + client IP (truncated) for spam triage. The
        file is OUTSIDE the web root (default ~/.ct_comments.jsonl) so it
        cannot be GET'd. A separate weekly digest script ships unread
        entries to the maintainer mailbox.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4_096:    # 4 KiB cap — generous for a 200-char comment
                return self._json(413, {"ok": False, "error": "payload too large"})
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return self._json(400, {"ok": False, "error": f"bad request: {e}"})

        name = (payload.get("name") or "").strip()
        category = (payload.get("category") or "other").strip().lower()
        message = (payload.get("message") or "").strip()
        lang = (payload.get("lang") or "").strip()

        if not message:
            return self._json(400, {"ok": False, "error": "message is required"})
        if len(message) > 200:
            return self._json(400, {"ok": False, "error": "message too long (max 200 chars)"})
        if len(name) > 80:
            return self._json(400, {"ok": False, "error": "name too long (max 80 chars)"})
        if category not in {"bug", "feature", "conference", "other"}:
            category = "other"

        # IP truncation for crude spam triage (we don't keep full IPs).
        ip = self.client_address[0] if self.client_address else ""
        if ":" in ip:
            ip = ":".join(ip.split(":")[:4]) + "::/64"   # IPv6 prefix
        else:
            ip = ".".join(ip.split(".")[:3]) + ".0/24"   # IPv4 /24

        entry = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "name": name or "(anonymous)",
            "category": category,
            "lang": lang,
            "message": message,
            "ip_block": ip,
        }
        try:
            path = _feedback_path()
            # Refuse to write inside ROOT (mirrors the credentials path check)
            try:
                path.relative_to(ROOT)
                sys.stderr.write(
                    f"[serve] REFUSING to write feedback to {path}: inside web root.\n"
                )
                return self._json(500, {"ok": False, "error": "server misconfigured"})
            except ValueError:
                pass
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            sys.stderr.write(f"[serve] failed to append feedback: {e}\n")
            return self._json(500, {"ok": False, "error": "could not store feedback"})

        sys.stderr.write(
            f"[serve] feedback: {category} from {entry['name']!r} "
            f"({len(message)} chars)\n"
        )

        # Fire-and-forget email to the maintainer. We don't want a transient
        # SMTP error to fail the user's submission (the entry is already in
        # the journal file and the weekly digest will pick it up), so any
        # exception is logged and swallowed.
        try:
            _send_feedback_email(entry)
        except Exception as e:
            sys.stderr.write(f"[serve] feedback email failed (entry kept in log): {e}\n")

        return self._json(200, {"ok": True})

    def _handle_send_calendar(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_048_576:    # 1 MiB cap
                return self._json(413, {"ok": False, "error": "payload too large"})
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            return self._json(400, {"ok": False, "error": f"bad request: {e}"})

        to = (payload.get("to") or "").strip()
        ics = payload.get("ics") or ""
        subject = (payload.get("subject") or "Conference deadline").strip()
        body = payload.get("body") or ""
        filename = (payload.get("filename") or "event.ics").strip()
        # The "events" list carries the deadlines the user picked in the
        # modal. Each entry is {title, start_utc, end_utc, description,
        # location, when_label?}. The email renders one quick-add button
        # pair (Google / Outlook) per event. Optional — if missing, the
        # email still ships with the .ics attached as fallback.
        events = payload.get("events") or []
        if not isinstance(events, list):
            events = []

        # Defensive validation — reject obviously malformed input before
        # paying the SMTP round-trip.
        if not to or "@" not in to or "\n" in to:
            return self._json(400, {"ok": False, "error": "invalid recipient address"})
        if not ics.startswith("BEGIN:VCALENDAR"):
            return self._json(400, {"ok": False, "error": "payload is not a valid .ics file"})
        if "\n" in subject or len(subject) > 200:
            return self._json(400, {"ok": False, "error": "invalid subject"})

        cfg = load_config()
        if not cfg:
            return self._json(500, {
                "ok": False,
                "error": ("mail_config.json missing or malformed. "
                          "Copy mail_config.example.json and fill in your "
                          "QQ mail account + SMTP authorization code."),
            })

        msg = EmailMessage()
        msg["Subject"] = subject
        from_name = cfg.get("from_name") or "CS Conference Tracker"
        msg["From"] = f"{from_name} <{cfg['from_addr']}>"
        msg["To"] = to

        # Body: plain-text fallback first, then HTML alternative with
        # one-click "Add to Google Calendar" / "Add to Outlook" buttons.
        # Most modern mail clients render the HTML version; very old ones
        # fall back to plain text. QQ Mail web client renders HTML fine
        # and the inline buttons are the entire point of this change.
        plain_body, html_body = _render_bodies(body, events, to)
        msg.set_content(plain_body or "Calendar event attached.")
        msg.add_alternative(html_body, subtype="html")

        # Attach the .ics. Using `text/calendar; method=REQUEST` causes
        # native mail clients (Outlook desktop, Apple Mail, recent Gmail
        # web) to surface an inline "Add to calendar" / accept button at
        # the top of the message — REQUEST is the iCalendar method for
        # invitations; PUBLISH is just "FYI here's an event". REQUEST is
        # the right signal even though we're not actually inviting them
        # to attend anything.
        msg.add_attachment(
            ics.encode("utf-8"),
            maintype="text",
            subtype="calendar; method=REQUEST; charset=UTF-8",
            filename=filename,
        )

        host = cfg.get("smtp_host", "smtp.qq.com")
        port = int(cfg.get("smtp_port", 465))
        user = cfg["smtp_user"]
        password = cfg["smtp_password"]

        try:
            ctx = ssl.create_default_context()
            if port == 465:
                with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                    s.login(user, password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=30) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                    s.login(user, password)
                    s.send_message(msg)
        except smtplib.SMTPAuthenticationError as e:
            sys.stderr.write(f"[serve] SMTP auth failed: {e}\n")
            return self._json(502, {
                "ok": False,
                "error": ("SMTP authentication failed. For QQ Mail, the password "
                          "field must be the 16-char authorization code, not your "
                          "QQ login password."),
            })
        except Exception as e:
            sys.stderr.write(f"[serve] SMTP send failed: {e}\n{traceback.format_exc()}")
            return self._json(502, {"ok": False, "error": f"smtp error: {e}"})

        sys.stderr.write(f"[serve] sent calendar to {to} ({filename})\n")
        return self._json(200, {"ok": True})


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    addr = os.environ.get("CT_BIND", "0.0.0.0")
    sys.stderr.write(
        f"[serve] root={ROOT} listening on http://{addr}:{port}\n"
        f"[serve] mail config: {'OK' if load_config() else 'MISSING — copy mail_config.example.json'}\n"
    )
    ThreadingHTTPServer((addr, port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
