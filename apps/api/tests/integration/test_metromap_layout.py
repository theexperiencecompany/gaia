"""The metromap edition keeps every label on the map and clear of every other, at real lengths.

Its stations sit at fixed coordinates; real item text once ran off the canvas and the
decision labels overprinted each other. Measured in headless Chromium, never estimated.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import async_playwright
import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions import EXPLORER_RENDERER

_LONG = (
    "Approve the reply to Priya about the revised term sheet and the board seat question",
    "Sync the Stripe invoices for September and October into the finance sheet again",
    "Investor update draft for October with the churn numbers and the hiring plan attached",
    "Q4 hiring plan pulled together from your notes, two interviews and the budget thread",
    "Weekly metrics digest assembled from Mixpanel, Stripe and the support inbox overnight",
    "Sequoia partner meeting about the Series A timeline and the data room checklist",
    "Design review with Dhruv and the whole mobile team on the onboarding flow rework",
    "Quarterly planning offsite logistics with the leadership team and the venue contract",
    "Sand Hill Road, Menlo Park, the second floor conference room past reception",
    "Zoom link in the invite, dial-in for the team in Bangalore and Lisbon",
)
_SHORT = (
    "Approve Priya",
    "Sync invoices",
    "Investor update",
    "Hiring plan",
    "Metrics digest",
    "Sequoia",
    "Design review",
    "Offsite",
    "Menlo Park",
    "Zoom",
)


def _payload(texts: tuple[str, ...]) -> dict[str, Any]:
    return {
        "kicker": "THE MORNING BRIEF",
        "date": "2026-10-14",
        "headline": "Two replies need you before your 11:00.",
        "lede": "I drafted both.",
        "sections": [
            {
                "numeral": "I",
                "title": "NEEDS YOU",
                "items": [
                    {"text": texts[0], "kind": "you"},
                    {"text": texts[1], "kind": "failed"},
                ],
            },
            {
                "numeral": "II",
                "title": "GAIA'S WORK",
                "items": [
                    {"text": texts[2], "kind": "lookback"},
                    {"text": texts[3], "kind": "gaia"},
                    {"text": texts[4], "kind": "lookback"},
                ],
            },
        ],
        "calendar": [
            {"date": "2026-10-14", "start": "09:30", "title": texts[5], "location": texts[8]},
            {"date": "2026-10-14", "start": "11:00", "title": texts[6], "location": texts[9]},
            {"date": "2026-10-14", "start": "15:00", "title": texts[7], "location": texts[8]},
        ],
        "mood": "packed",
        "caption": "Onward.",
        "hue": 0,
    }


_MEASURE = """() => {
  const svg = document.querySelector("svg.t-metromap__map");
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
  };
  const labels = [...svg.querySelectorAll("text")]
    .filter((el) => el.textContent.trim())
    .map((el) => {
      const lines = [...el.querySelectorAll("tspan")].map((t) => t.textContent);
      return { text: lines.length ? lines.join(" ") : el.textContent, ...rect(el) };
    });
  const notes = svg.querySelectorAll(".mm-note, .mm-ixnote").length;
  return { frame: rect(svg), labels, notes };
}"""

# The skin (full or terse station notes) is seeded by the brief's date; these
# dates are enough to draw both, which the test asserts rather than assumes.
_DATES = tuple(f"2026-10-{day}" for day in range(10, 22))


async def _measure_each_date(texts: tuple[str, ...]) -> list[dict[str, Any]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            measured: list[dict[str, Any]] = []
            for date in _DATES:
                data = BriefingPayload.model_validate({**_payload(texts), "date": date})
                html = EXPLORER_RENDERER["metromap"](
                    data.model_dump(), edition_no=287, generated_local="", tz_label=""
                )
                # A fresh page per render: the document's top-level script globals persist.
                page = await browser.new_page(viewport={"width": 1180, "height": 800})
                await page.set_content(html, wait_until="networkidle")
                measured.append(await page.evaluate(_MEASURE))
                await page.close()
            return measured
        finally:
            await browser.close()


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a["left"] < b["right"]
        and b["left"] < a["right"]
        and a["top"] < b["bottom"]
        and b["top"] < a["bottom"]
    )


def _off_map(frame: dict[str, Any], label: dict[str, Any]) -> bool:
    return (
        label["left"] < frame["left"]
        or label["right"] > frame["right"]
        or label["top"] < frame["top"]
        or label["bottom"] > frame["bottom"]
    )


@pytest.mark.integration
@pytest.mark.parametrize("texts", [_SHORT, _LONG], ids=["short", "long"])
async def test_every_label_stays_on_the_map_and_clear_of_the_others(
    texts: tuple[str, ...],
) -> None:
    renders = await _measure_each_date(texts)

    assert {render["notes"] > 0 for render in renders} == {True, False}
    for render in renders:
        frame, labels = render["frame"], render["labels"]
        assert [label["text"] for label in labels if _off_map(frame, label)] == []
        overprinted = [
            (a["text"], b["text"])
            for i, a in enumerate(labels)
            for b in labels[i + 1 :]
            if _overlap(a, b)
        ]
        assert overprinted == []


@pytest.mark.integration
async def test_a_long_label_is_cut_with_an_ellipsis_not_dropped() -> None:
    (render, *_) = await _measure_each_date(_LONG)

    printed = " ".join(label["text"] for label in render["labels"])
    assert "sequoia partner meeting" in printed.lower()
    assert "…" in printed
