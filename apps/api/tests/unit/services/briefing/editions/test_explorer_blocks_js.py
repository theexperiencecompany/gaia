"""The shared plot script, run in node: signed values keep a zero line, and extra series stay distinguishable."""

import json
from pathlib import Path
import subprocess
from typing import Any

from app.services.briefing.editions import explorer_render

_BLOCKS = Path(explorer_render._SHELL_DIR) / "blocks.js"
_HARNESS = """
const window = { devicePixelRatio: 1 };
const EXPLORER = { logoKinds: {} };
const input = JSON.parse(process.argv[1]);
%s
console.log(JSON.stringify(eval(input.expr)));
"""


def _node(expr: str) -> Any:
    script = _HARNESS % _BLOCKS.read_text()
    done = subprocess.run(
        ["node", "-e", script, json.dumps({"expr": expr})],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def _series(name: str, values: list[float]) -> dict[str, Any]:
    return {
        "name": name,
        "total": str(sum(values)),
        "values": values,
        "shown": [str(v) for v in values],
    }


def _rects(svg: str) -> list[dict[str, float]]:
    import re

    return [
        {k: float(v) for k, v in re.findall(r'(x|y|width|height)="([\d.\-]+)"', tag)}
        for tag in re.findall(r"<rect [^>]*>", svg)
    ]


_ST = "{w: 400, h: 200, font: 'x', size: 12, ink: '#000', soft: '#888', rule: '#ccc', fills: ['#111', '#999'], baseline: true}"


def test_a_negative_bar_hangs_below_the_zero_line_the_positive_one_stands_on() -> None:
    chart = {"x": ["Mon", "Tue"], "series": [_series("Net", [30, -30])]}

    svg = _node(f"EXPLORER.blocks.bars({json.dumps(chart)}, {_ST})")
    bars = [r for r in _rects(svg) if r.get("width", 0) > 5 and r.get("height", 0) > 5]
    positive, negative = sorted(bars, key=lambda r: r["x"])

    assert positive["y"] + positive["height"] == negative["y"]
    assert positive["height"] == negative["height"]


def test_ticks_cross_zero_when_a_series_dips_below_it() -> None:
    ticks = _node("EXPLORER.blocks.niceTicksBetween(-40, 90)")

    assert min(ticks) <= -40 and max(ticks) >= 90 and 0 in ticks


def test_ticks_for_positive_data_are_unchanged() -> None:
    assert _node("EXPLORER.blocks.niceTicksBetween(5, 61)") == _node(
        "EXPLORER.blocks.niceTicks(61)"
    )


def test_a_line_chart_draws_its_negative_point_inside_the_plot() -> None:
    chart = {
        "x": ["Mon", "Tue", "Wed"],
        "series": [_series("Refunds", [-50, -10, -30])],
    }
    st = "{w: 400, h: 200, font: 'x', size: 12, ink: '#000', soft: '#888', rule: '#ccc', lines: [{color: '#f00', width: 2}]}"

    svg = _node(f"EXPLORER.blocks.line({json.dumps(chart)}, {st})")

    ys = [float(y) for y in __import__("re").findall(r'cy="([\d.\-]+)"', svg)]
    assert ys and all(0 <= y <= 200 for y in ys)


def test_a_third_series_repeats_the_first_style_dotted_and_the_key_says_so() -> None:
    lines = "[{color: 'a', width: 2}, {color: 'b', width: 2, dash: '5 4'}]"

    styles = _node(f"[0, 1, 2, 3].map((k) => EXPLORER.blocks.lineStyle({lines}, k))")
    keys = _node("[0, 1, 2, 3].map((k) => EXPLORER.blocks.lineKeyClass(k, 2))")

    assert [s["color"] for s in styles] == ["a", "b", "a", "b"]
    assert [bool(s.get("dash")) for s in styles] == [False, True, True, True]
    assert styles[2]["dash"] == styles[3]["dash"] != styles[1]["dash"]
    assert keys == ["", " dash", " dot", " dash dot"]
