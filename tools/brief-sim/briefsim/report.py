"""Write report.html: one row per simulated day with the world's events, what GAIA sent, and every finding."""

from collections import Counter
from datetime import datetime, timedelta
from html import escape
import json
from pathlib import Path
import re

from briefsim.oracle.logs import LoggedError, logged_errors
from briefsim.oracle.truth import Brief, Truth, load, parse_instant, read_jsonl

_STYLE = """
body{font:14px/1.45 -apple-system,Inter,sans-serif;margin:24px;background:#111;color:#ddd}
h1,h2{font-weight:600}table{border-collapse:collapse;width:100%}
td,th{vertical-align:top;border-top:1px solid #333;padding:10px;text-align:left}
th{color:#999;font-weight:500}.fault{color:#f87171}.ok{color:#86efac}.muted{color:#888}
.finding{background:#3b1d1d;border-radius:8px;padding:6px 8px;margin:0 0 6px}
.finding b{color:#fca5a5}img{max-width:340px;border-radius:8px;display:block;margin:6px 0}
pre{white-space:pre-wrap;font:13px/1.4 ui-monospace,monospace;color:#ccc;margin:4px 0}
.pill{display:inline-block;background:#222;border-radius:999px;padding:2px 8px;margin:2px}
"""
_EDITION = re.compile(r"briefing/editions/([A-Za-z0-9_-]+)")


def _edition_file(out: Path, brief: Brief) -> str | None:
    match = _EDITION.search(brief.doc.get("edition_image_url") or "")
    if match is None:
        return None
    name = f"editions/briefing_editions_{match.group(1)}.png"
    return name if (out / name).exists() else None


def _world_cell(truth: Truth, day_start: datetime) -> str:
    day_end = day_start + timedelta(days=1)
    lines = [
        f"<div>{c.at.astimezone(truth.tz):%H:%M} <span class=muted>{c.app.value}</span> {escape(c.summary)}</div>"
        for c in truth.world.changes_between(day_start, day_end)
    ]
    lines += [
        f"<div class=fault>{f.app.value} {f.mode.value} {f.start.astimezone(truth.tz):%a %H:%M}"
        f" - {f.end.astimezone(truth.tz):%a %H:%M}</div>"
        for f in truth.world.faults
        if f.start < day_end and f.end > day_start
    ]
    reads = Counter(
        (str(r["app"]), str(r["outcome"]))
        for r in truth.reads
        if day_start <= parse_instant(str(r["at"])) < day_end
    )
    lines += [
        f"<span class='pill {'ok' if outcome == 'ok' else 'fault'}'>{app} read {outcome} x{n}</span>"
        for (app, outcome), n in sorted(reads.items())
    ]
    return "".join(lines) or "<span class=muted>nothing happened</span>"


def _brief_cell(out: Path, truth: Truth, brief: Brief, emails: list[dict[str, object]]) -> str:
    payload = brief.payload
    edition = _edition_file(out, brief)
    unread = ", ".join(s.get("app", "") for s in payload.get("sources_unavailable") or [])
    parts = [
        f"<div><b>{escape(brief.kind)}</b> stored {brief.stored_at.astimezone(truth.tz):%H:%M} "
        f"<span class=muted>channels: {escape(', '.join(brief.doc.get('delivered_channels') or []) or 'none')}</span></div>",
        f"<div><b>{escape(str(payload.get('headline') or ''))}</b></div>",
        f"<div class=muted>{escape(str(payload.get('lede') or ''))}</div>",
        f"<img src='{edition}'>" if edition else "<div class=muted>(no edition image)</div>",
        f"<pre>{escape(str(payload.get('message') or ''))}</pre>",
    ]
    if unread:
        parts.append(f"<div class=fault>sources unavailable: {escape(unread)}</div>")
    if emails:
        parts.append(f"<div class=muted>email: {escape(str(emails[0].get('subject')))}</div>")
    return "".join(parts)


def _errors_cell(errors: list[LoggedError], start: datetime) -> str:
    """Return GAIA's own logged errors that day, grouped by message."""
    day = Counter(
        (e.message, e.error[:160]) for e in errors if start <= e.at < start + timedelta(days=1)
    )
    return "".join(
        f"<div class=muted>{escape(message)} <span class=fault>{escape(error)}</span> x{n}</div>"
        for (message, error), n in sorted(day.items())
    )


def write(out: Path) -> None:
    truth = load(out)
    run = json.loads((out / "run.json").read_text())
    findings = json.loads((out / "findings.json").read_text())
    calls = read_jsonl(out / "world_calls.jsonl")
    gaps = sorted(
        {f"{c['method']} {c['path']}: {c['why']}" for c in calls if c.get("kind") == "sim_gap"}
    )
    emails = [c for c in calls if c.get("sink") == "email"]
    errors = logged_errors(out, truth.connected_at)
    cost = sum(float(str(c.get("cost_usd") or 0)) for c in read_jsonl(out / "llm_calls.jsonl"))
    origin = parse_instant(run["origin"])
    first = origin.astimezone(truth.tz).date()
    rows = []
    for day in range(int(run["days"])):
        local = first + timedelta(days=day)
        start = datetime.combine(local, datetime.min.time(), truth.tz)
        briefs = [b for b in truth.briefs if b.local_date == local]
        day_emails = [
            e for e in emails if start <= parse_instant(str(e["at"])) < start + timedelta(days=1)
        ]
        sent = (
            "".join(_brief_cell(out, truth, b, day_emails) for b in briefs)
            or "<span class=fault>no brief stored</span>"
        )
        day_findings = "".join(
            f"<div class=finding><b>{escape(f['check'])}</b> {escape(f['item'])}<br>"
            f"<span class=muted>expected</span> {escape(f['expected'])}<br><span class=muted>got</span> {escape(f['got'])}</div>"
            for f in findings
            if f["day"] == local.isoformat()
        )
        rows.append(
            f"<tr><th>Day {day}<br>{local:%a %d %b}</th><td>{_world_cell(truth, start)}</td>"
            f"<td>{sent}</td><td>{day_findings or '<span class=ok>no findings</span>'}{_errors_cell(errors, start)}</td></tr>"
        )
    totals = Counter(f["check"] for f in findings)
    header = " ".join(
        f"<span class=pill>{escape(k)}: {v}</span>" for k, v in sorted(totals.items())
    )
    gap_list = "".join(f"<li>{escape(g)}</li>" for g in gaps) or "<li class=muted>none</li>"
    html = (
        f"<!doctype html><meta charset=utf-8><title>brief-sim {escape(run['user_id'])}</title><style>{_STYLE}</style>"
        f"<h1>Brief simulator: busy founder, {run['days']} days from {first:%a %d %b %Y} ({escape(run['timezone'])})</h1>"
        f"<p>{len(truth.briefs)} briefs stored, {len(findings)} findings, wall clock {run['wall_clock_s'] // 60} min, "
        f"LLM cost ${cost:.2f}</p><p>{header}</p><h2>Sim gaps (routes the fake world does not implement)</h2><ul>{gap_list}</ul>"
        f"<table><tr><th></th><th>World</th><th>What GAIA sent</th><th>Findings</th></tr>{''.join(rows)}</table>"
    )
    (out / "report.html").write_text(html)
