#!/usr/bin/env python3
"""send_feedback_digest.py — email accumulated user comments to the maintainer.

Reads ~/.ct_comments.jsonl (or $CT_FEEDBACK_LOG) for entries newer than the
last send marker (~/.ct_comments_last_sent), groups them by category, and
sends a single digest email. Intended to be run weekly via cron:

    # 09:00 every Monday
    0 9 * * 1  /usr/bin/python3 /home/camob/conferences/scripts/send_feedback_digest.py

Reuses ~/.ct_mail_config.json for SMTP credentials (same file the website's
calendar mailer uses). Recipient comes from $CT_FEEDBACK_RECIPIENT — set it
in the cron environment or your shell profile.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

# Read recipient from $CT_FEEDBACK_RECIPIENT so the maintainer's mailbox
# never lives in the repo. Required — script exits 1 if unset.
RECIPIENT = (os.environ.get("CT_FEEDBACK_RECIPIENT") or "").strip()
SUBJECT_PREFIX = "[CS Conference Tracker] Weekly feedback digest"

CATEGORY_LABELS = {
    "bug":        "🐛 Bug reports",
    "feature":    "✨ Feature requests",
    "conference": "🎓 Conference suggestions",
    "other":      "💬 Other",
}
CATEGORY_ORDER = ["bug", "feature", "conference", "other"]


def feedback_path() -> Path:
    return Path(os.environ.get("CT_FEEDBACK_LOG") or (Path.home() / ".ct_comments.jsonl")).resolve()


def marker_path() -> Path:
    return Path(os.environ.get("CT_FEEDBACK_MARKER") or (Path.home() / ".ct_comments_last_sent")).resolve()


def mail_config_path() -> Path:
    return Path(os.environ.get("CT_MAIL_CONFIG") or (Path.home() / ".ct_mail_config.json")).resolve()


def load_entries_since(since_iso: str | None) -> list[dict]:
    path = feedback_path()
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since_iso and entry.get("ts", "") <= since_iso:
            continue
        out.append(entry)
    return out


def read_marker() -> str | None:
    p = marker_path()
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def write_marker(iso: str) -> None:
    marker_path().write_text(iso, encoding="utf-8")


def render_plain(entries: list[dict], since_iso: str | None) -> str:
    lines = []
    if since_iso:
        lines.append(f"Comments received since {since_iso}:")
    else:
        lines.append("All collected comments to date:")
    lines.append(f"Total: {len(entries)}")
    lines.append("")
    by_cat: dict[str, list[dict]] = {k: [] for k in CATEGORY_ORDER}
    for e in entries:
        by_cat.setdefault(e.get("category", "other"), []).append(e)
    for cat in CATEGORY_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append("=" * 60)
        lines.append(f"{CATEGORY_LABELS.get(cat, cat)}  ({len(items)})")
        lines.append("=" * 60)
        for e in items:
            ts = e.get("ts", "")
            name = e.get("name") or "(anonymous)"
            lang = e.get("lang") or "?"
            ip = e.get("ip_block") or "?"
            lines.append(f"\n[{ts}] {name}  · lang={lang} · ip={ip}")
            lines.append(e.get("message", "").rstrip())
        lines.append("")
    return "\n".join(lines)


def render_html(entries: list[dict], since_iso: str | None) -> str:
    import html
    def esc(s: str) -> str: return html.escape(str(s or ""))

    by_cat: dict[str, list[dict]] = {k: [] for k in CATEGORY_ORDER}
    for e in entries:
        by_cat.setdefault(e.get("category", "other"), []).append(e)

    sections = []
    for cat in CATEGORY_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        rows = []
        for e in items:
            rows.append(f"""
              <div style="border-left:3px solid #cbd5e1;padding:8px 12px;margin:8px 0;background:#f8fafc;border-radius:4px">
                <div style="font-size:12px;color:#64748b;margin-bottom:4px">
                  <strong>{esc(e.get('name') or '(anonymous)')}</strong>
                  &middot; {esc(e.get('ts', ''))}
                  &middot; lang={esc(e.get('lang') or '?')}
                  &middot; ip={esc(e.get('ip_block') or '?')}
                </div>
                <pre style="margin:0;font-family:inherit;white-space:pre-wrap;word-wrap:break-word;font-size:14px;color:#0f172a">{esc(e.get('message', ''))}</pre>
              </div>
            """)
        sections.append(f"""
          <section style="margin-bottom:24px">
            <h2 style="font-size:15px;color:#1e293b;margin:0 0 8px;padding-bottom:4px;border-bottom:1px solid #e2e8f0">
              {esc(CATEGORY_LABELS.get(cat, cat))} <span style="color:#94a3b8;font-weight:normal">({len(items)})</span>
            </h2>
            {''.join(rows)}
          </section>
        """)

    since_line = f"Comments since <strong>{esc(since_iso)}</strong>" if since_iso else "All collected comments to date"
    return f"""<!doctype html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:720px;margin:0 auto;padding:24px;color:#0f172a">
  <h1 style="font-size:18px;margin:0 0 4px">CS Conference Tracker — Weekly feedback</h1>
  <p style="color:#64748b;font-size:13px;margin:0 0 24px">{since_line} &middot; Total: <strong>{len(entries)}</strong></p>
  {''.join(sections) or '<p style="color:#94a3b8">(no new entries)</p>'}
  <hr style="border:0;border-top:1px solid #e2e8f0;margin:32px 0 12px">
  <p style="color:#94a3b8;font-size:11px">Sent by send_feedback_digest.py. Raw log: ~/.ct_comments.jsonl</p>
</body></html>
"""


def send(subject: str, plain: str, html: str, cfg: dict) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    from_name = cfg.get("from_name") or "CS Conference Tracker"
    msg["From"] = f"{from_name} <{cfg['from_addr']}>"
    msg["To"] = RECIPIENT
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    host = cfg.get("smtp_host", "smtp.qq.com")
    port = int(cfg.get("smtp_port", 465))
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo(); s.starttls(context=ctx); s.ehlo()
            s.login(user, password)
            s.send_message(msg)


def main() -> int:
    if not RECIPIENT:
        print(
            "ERROR: CT_FEEDBACK_RECIPIENT env var is not set. Add the "
            "maintainer's email address before running this script.",
            file=sys.stderr,
        )
        return 1
    cfg_path = mail_config_path()
    if not cfg_path.exists():
        print(f"ERROR: mail config not found at {cfg_path}", file=sys.stderr)
        return 1
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    since = read_marker()
    entries = load_entries_since(since)
    if not entries:
        print(f"No new feedback since {since or '<beginning>'} — nothing to send.")
        return 0

    today = dt.date.today().isoformat()
    subject = f"{SUBJECT_PREFIX} — {today} ({len(entries)} entries)"
    plain = render_plain(entries, since)
    html = render_html(entries, since)

    # Allow --dry-run to preview without sending
    if "--dry-run" in sys.argv:
        print(plain)
        print("\n(dry run — no email sent, no marker updated)")
        return 0

    try:
        send(subject, plain, html, cfg)
    except Exception as e:
        print(f"ERROR: send failed: {e}", file=sys.stderr)
        return 2

    # Advance the marker to the timestamp of the newest entry shipped
    latest_ts = max(e.get("ts", "") for e in entries)
    write_marker(latest_ts)
    print(f"Sent {len(entries)} entries to {RECIPIENT}. Marker → {latest_ts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
