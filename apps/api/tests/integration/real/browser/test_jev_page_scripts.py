"""Jev's page scripts in a real Chrome, on the shapes GitHub's device login is made of.

Regression for GAIA-715: on GitHub's "Authorize GitHub CLI" page Jev was offered one
button, labelled "0" (Cancel, named by its form value), and never saw the disabled
Authorize button at all, so it found no way forward and the run clicked Cancel. On
the code page it took GitHub's eight one-character boxes for eight fields, one
decision per character, and lost characters as the page moved focus between them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright
import pytest
import pytest_asyncio

from app.services.browser.jev import page as page_mod
from tests.integration.real.browser._stack.stack import required_binary

_SNAPSHOT = (Path(page_mod.__file__).parent / "snapshot.js").read_text()
_ACT = (Path(page_mod.__file__).parent / "act.js").read_text()
_CODE = "WDJBMJHT"

#: GitHub's /login/device: eight boxes that move focus as each takes a character, a dash box between.
_DEVICE = """<!doctype html><html><body><form action="/confirm" method="post">
<p>Enter the code displayed on the device you're signing in to.</p>
<input id="user-code-0" aria-label="User code 0" maxlength="1">
<input id="user-code-1" aria-label="User code 1" maxlength="1">
<input id="user-code-2" aria-label="User code 2" maxlength="1">
<input id="user-code-3" aria-label="User code 3" maxlength="1">
<input id="user-code-4" aria-label="User code 4" value="-" readonly>
<input id="user-code-5" aria-label="User code 5" maxlength="1">
<input id="user-code-6" aria-label="User code 6" maxlength="1">
<input id="user-code-7" aria-label="User code 7" maxlength="1">
<input id="user-code-8" aria-label="User code 8" maxlength="1">
<input type="submit" name="commit" value="Continue"></form>
<script>
const boxes=[...document.querySelectorAll('input[maxlength="1"]')];
boxes.forEach((box,i)=>box.addEventListener('input',()=>{ if (box.value && boxes[i+1]) boxes[i+1].focus(); }));
</script></body></html>"""

#: GitHub's device confirmation: Cancel first in the form, Authorize disabled until the page enables it.
_CONSENT = """<!doctype html><html><body><h1>Authorize GitHub CLI</h1>
<form action="/authorize" method="post">
<button type="submit" name="authorize" value="0">Cancel</button>
<button type="submit" name="authorize" value="1" disabled>Authorize github</button>
</form></body></html>"""


@pytest_asyncio.fixture
async def page() -> AsyncIterator[Page]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=required_binary("CHROMIUM_BIN", "google-chrome"), headless=True
        )
        yield await browser.new_page(viewport={"width": 1280, "height": 800})
        await browser.close()


async def _snapshot(page: Page, html: str) -> dict[str, Any]:
    await page.set_content(html)
    snapshot: dict[str, Any] = await page.evaluate(_SNAPSHOT)
    return snapshot


def _labels(snapshot: dict[str, Any], kind: str) -> list[str]:
    return [a["label"] for a in snapshot["actions"] if a["kind"] == kind]


@pytest.mark.regression
async def test_a_button_is_named_by_its_text_never_by_the_value_its_form_sends(page: Page) -> None:
    snapshot = await _snapshot(page, _CONSENT)

    assert _labels(snapshot, "click") == ["Cancel"]


@pytest.mark.regression
async def test_a_disabled_control_is_reported_so_jev_can_wait_for_it_but_never_offered(
    page: Page,
) -> None:
    snapshot = await _snapshot(page, _CONSENT)

    assert snapshot["disabled"] == ["Authorize github"]
    assert "Authorize github" not in _labels(snapshot, "click")


@pytest.mark.regression
async def test_one_character_boxes_are_offered_as_one_field(page: Page) -> None:
    snapshot = await _snapshot(page, _DEVICE)

    fills = [a for a in snapshot["actions"] if a["kind"] == "fill"]
    assert [f["label"] for f in fills] == ["User code"]
    assert len(fills[0]["segments"]) == 8
    assert not any(label.startswith("Open User code") for label in _labels(snapshot, "click"))


@pytest.mark.regression
async def test_a_code_typed_into_the_first_box_is_read_back_whole(page: Page) -> None:
    snapshot = await _snapshot(page, _DEVICE)
    field = next(a for a in snapshot["actions"] if a["kind"] == "fill")

    await page.click("#user-code-0")
    await page.keyboard.type(_CODE)
    held = await page.evaluate(f"(() => {{ {_ACT}; return gaiaJevValue({json.dumps(field)}); }})()")

    assert held == _CODE
