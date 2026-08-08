"""Self-contained HTML report (Inspect view-bundle style) + markdown summary.

One static file per run: summary scoreboard, per-case cards with transcript +
tool calls + scores, provider/token/cost tables, inline SVG bar charts.
Regenerable from the journal alone.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import html
import json
from pathlib import Path
from typing import Any

from .journal import RunJournal
from .types import PriceBook, ProviderPrice


def _svg_bars(rows: list[tuple[str, float]], width: int = 640) -> str:
    """Horizontal bar chart as inline SVG (no JS, no deps)."""
    if not rows:
        return "<p>no data</p>"
    max_val = max(v for _, v in rows) or 1.0
    bar_h = 18
    gap = 8
    label_w = 150
    top = 10
    bars = []
    for i, (label, value) in enumerate(rows):
        y = top + i * (bar_h + gap)
        bar_w = (width - label_w - 60) * (value / max_val)
        bars.append(
            f'<text x="0" y="{y + 13}" class="lbl">{html.escape(label[:28])}</text>'
            f'<rect x="{label_w}" y="{y}" width="{bar_w:.0f}" height="{bar_h}" rx="4" '
            f'class="bar{" bad" if value < 0.5 else ""}"/>'
            f'<text x="{label_w + bar_w + 6}" y="{y + 13}" class="val">{value:.2f}</text>'
        )
    svg_height = top + len(rows) * (bar_h + gap) + 10
    bars_svg = "".join(bars)
    return (
        f'<svg viewBox="0 0 {width} {svg_height}" '
        f'width="{width}" height="{svg_height}">{bars_svg}</svg>'
    )


def _fmt_usd(value: float) -> str:
    return f"${value:,.2f}"


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _case_passed(record: dict[str, Any]) -> bool:
    return bool(record.get("status") == "passed")


def _case_errored(record: dict[str, Any]) -> bool:
    """A case that never produced an answer — excluded from every accuracy.

    Averaging these in turns an outage into a quality score: a run where the
    datastore died once reported an entire question type as 0%.
    """
    return bool(record.get("status") == "errored")


def render_html(journal: RunJournal, suite_label: str, prices: PriceBook) -> str:
    meta = journal.load_meta()
    records = journal.records()
    passed = sum(1 for r in records if _case_passed(r))
    errored = sum(1 for r in records if _case_errored(r))
    total = len(records) - errored
    pct = (passed / total * 100) if total else 0.0

    score_keys: Counter[str] = Counter()
    score_sums: dict[str, float] = defaultdict(float)
    per_category: dict[str, list[float]] = defaultdict(list)
    provider_counts: Counter[str] = Counter()
    provider_tokens_in: Counter[str] = Counter()
    provider_tokens_out: Counter[str] = Counter()

    for r in records:
        provider_counts[r.get("provider", "?")] += 1
        provider_tokens_in[r.get("provider", "?")] += int(r.get("tokens", {}).get("input", 0))
        provider_tokens_out[r.get("provider", "?")] += int(r.get("tokens", {}).get("output", 0))
        for name, value in (r.get("scores") or {}).items():
            score_keys[name] += 1
            score_sums[name] += float(value)
        category = r.get("category")
        if category and not _case_errored(r):
            per_category[category].append(1.0 if _case_passed(r) else 0.0)

    total_in = sum(provider_tokens_in.values())
    total_out = sum(provider_tokens_out.values())
    total_cost = journal.cost_usd(prices)

    metric_rows = [
        (name, score_sums[name] / score_keys[name])
        for name in sorted(score_keys)
        if score_keys[name] > 0
    ]
    category_rows = [(cat, sum(v) / len(v)) for cat, v in sorted(per_category.items())]

    provider_rows = [
        (
            p,
            provider_tokens_in[p],
            provider_tokens_out[p],
            sum(
                prices.get(p, ProviderPrice()).paid_cost(
                    int(r.get("tokens", {}).get("input", 0)),
                    int(r.get("tokens", {}).get("output", 0)),
                )
                for r in records
                if r.get("provider") == p
            ),
        )
        for p in provider_counts
    ]

    cards = []
    for r in records:
        status = r.get("status", "unknown")
        scores = r.get("scores") or {}
        score_html = "".join(
            f'<span class="chip {"ok" if v >= 0.5 else "no"}">{html.escape(n)}={v:.2f}</span>'
            for n, v in sorted(scores.items())
        )
        messages = "".join(
            f'<div class="msg {html.escape(m.get("role", "?")).replace("assistant", "asst")}">'
            f"<b>{html.escape(m.get('role', '?'))}:</b> {html.escape(m.get('content', ''))}</div>"
            for m in r.get("messages") or []
        )
        tool_calls = "".join(
            f'<div class="tool"><code>{html.escape(str(t.get("name", "")))}</code> '
            f"<pre>{html.escape(json.dumps(t.get('args', {}), default=str)[:400])}</pre></div>"
            for t in r.get("tool_calls") or []
        )
        tokens = r.get("tokens") or {}
        cards.append(
            f"""<details class="card {status}">
  <summary><b>{html.escape(r.get("case_id", "?"))}</b>
    <span class="status">{status}</span>
    {score_html}
    <span class="meta">provider={r.get("provider", "?")} · {_fmt_tokens(int(tokens.get("input", 0)))} in /
    {_fmt_tokens(int(tokens.get("output", 0)))} out · {r.get("duration_s", 0):.1f}s</span>
  </summary>
  <div class="body">
    <div class="ticket">{html.escape(r.get("ticket", ""))}</div>
    <div class="prompt"><b>prompt:</b> {html.escape(r.get("prompt", ""))}</div>
    <div class="expected"><b>expected:</b> <pre>{html.escape(json.dumps(r.get("expected", {}), indent=1, default=str)[:1200])}</pre></div>
    <div class="msglist">{messages}</div>
    <div class="tools">{tool_calls}</div>
    <div class="error">{html.escape(r.get("error") or "")}</div>
  </div>
</details>"""
        )

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    run_id = html.escape(journal.dir.name)
    suite = html.escape(suite_label)
    experiment = meta.experiment_name or ""
    status = meta.status if meta else "?"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Eval report — {suite} — {run_id}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; margin: 0; background: #0f1115; color: #e5e7eb; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 80px; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 16px; margin-top: 32px; border-bottom: 1px solid #26292f; padding-bottom: 6px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid #26292f; }}
  .score {{ font-size: 44px; font-weight: 700; }} .pct {{ color: #9ca3af; font-size: 16px; }}
  svg text {{ font-size: 12px; }} .lbl {{ fill: #d1d5db; }} .val {{ fill: #fbbf24; }}
  .bar {{ fill: #34d399; }} .bar.bad {{ fill: #f87171; }}
  details.card {{ border: 1px solid #26292f; border-radius: 10px; margin: 8px 0; background: #14161c; }}
  details.card summary {{ padding: 10px 14px; cursor: pointer; }}
  .status {{ text-transform: uppercase; font-size: 11px; padding: 2px 8px; border-radius: 999px; }}
  .passed .status {{ background: #065f46; }} .failed .status {{ background: #7f1d1d; }}
  .errored .status {{ background: #78350f; }}
  .chip {{ display: inline-block; font-size: 11px; margin: 0 3px; padding: 1px 6px; border-radius: 6px; background: #1f2937; }}
  .chip.ok {{ background: #065f46; }} .chip.no {{ background: #7f1d1d; }}
  .meta {{ color: #6b7280; font-size: 11px; margin-left: 8px; }}
  .body {{ padding: 4px 14px 14px; font-size: 13px; }}
  .msg {{ margin: 4px 0; }} .asst {{ color: #a7f3d0; }}
  .tool pre, .expected pre {{ background: #0b0d11; padding: 8px; border-radius: 8px; overflow-x: auto; font-size: 12px; }}
  .ticket {{ color: #fbbf24; margin: 4px 0; }}
  .error {{ color: #f87171; }}
  .banner {{ color: #9ca3af; font-size: 13px; }}
</style></head><body><div class="wrap">
<h1>GAIA eval — {suite}</h1>
<div class="banner">run <code>{run_id}</code> · finished {now} · status <b>{status}</b> · experiment {experiment}</div>
<div class="score">{pct:.1f}%</div>
<div class="pct">{passed}/{total} cases passed{f" · {errored} errored (not scored)" if errored else ""}</div>
<h2>Metrics</h2>{_svg_bars(metric_rows) if metric_rows else "<p>no metrics</p>"}
<h2>Categories</h2>{_svg_bars(category_rows) if category_rows else "<p>no categories</p>"}
<h2>Provider usage</h2>
<table><tr><th>provider</th><th>cases</th><th>tokens in</th><th>tokens out</th><th>est. USD</th></tr>
{"".join(f"<tr><td>{html.escape(p)}</td><td>{provider_counts[p]}</td><td>{_fmt_tokens(i)}</td><td>{_fmt_tokens(o)}</td><td>{_fmt_usd(c)}</td></tr>" for p, i, o, c in provider_rows)}
<tr><td><b>total</b></td><td>{len(records)}</td><td>{_fmt_tokens(total_in)}</td><td>{_fmt_tokens(total_out)}</td><td>{_fmt_usd(total_cost)}</td></tr>
</table>
<h2>Cases</h2>
{"".join(cards)}
</div></body></html>"""


def render_markdown(journal: RunJournal, suite_label: str, prices: PriceBook) -> str:
    records = journal.records()
    passed = sum(1 for r in records if _case_passed(r))
    errored = sum(1 for r in records if _case_errored(r))
    total = len(records) - errored
    lines = [
        f"# {suite_label} — {journal.dir.name}",
        "",
        f"- **Score:** {passed}/{total} ({passed / total * 100 if total else 0:.1f}%)",
        f"- **Errored:** {errored} (never answered — excluded from the score)",
        f"- **Tokens:** {journal.tokens()[0]:,} in / {journal.tokens()[1]:,} out",
        f"- **Est. cost:** {_fmt_usd(journal.cost_usd(prices))}",
        "",
        "| case | status | provider | score |",
        "|---|---|---|---|",
    ]
    for r in records:
        score = " / ".join(f"{n}={v:.2f}" for n, v in (r.get("scores") or {}).items())
        lines.append(
            f"| {r.get('case_id', '?')} | {r.get('status', '?')} | {r.get('provider', '?')} | {score} |"
        )
    return "\n".join(lines) + "\n"


def write_report(journal: RunJournal, suite_label: str, prices: PriceBook) -> Path:
    html_path = journal.dir / "report.html"
    html_path.write_text(render_html(journal, suite_label, prices), encoding="utf-8")
    (journal.dir / "summary.md").write_text(
        render_markdown(journal, suite_label, prices), encoding="utf-8"
    )
    latest_dir = journal.dir.parent.parent / "reports"
    latest_dir.mkdir(exist_ok=True)
    (latest_dir / "latest.html").write_text(html_path.read_text(), encoding="utf-8")
    return html_path
