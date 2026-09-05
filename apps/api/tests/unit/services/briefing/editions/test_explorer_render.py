"""Unit tests for the vendored-explorer HTML document builder.

``render_explorer_edition`` produces a self-contained document that a headless
Chromium later rasters. These tests assert on the document itself — the
inlined modules, the embedded ``ed``/seed literals, the script-tag escaping
and the failure path — not on the rastered pixels, which need a real browser
and belong to the render pipeline's own tier.
"""

from collections.abc import Iterator
import json
from pathlib import Path
import re
from typing import Any

import pytest

from app.services.briefing.editions import explorer_render
from app.services.briefing.editions.explorer_render import (
    _art_credit,
    _asset_data_uris,
    _font_faces_css,
    _module_sources,
    explorer_family_ids,
    render_explorer_edition,
)

# Every loader is @lru_cache(maxsize=1) over a file read, and the cache outlives
# the test that fills it — without this each test would assert against whatever
# an earlier test happened to load, and a broken loader would only ever be seen
# by the first test to call it.
_CACHED_LOADERS = (
    _module_sources,
    explorer_family_ids,
    _asset_data_uris,
    _art_credit,
    _font_faces_css,
)


@pytest.fixture(autouse=True)
def _clear_loader_caches() -> Iterator[None]:
    for loader in _CACHED_LOADERS:
        loader.cache_clear()
    yield
    for loader in _CACHED_LOADERS:
        loader.cache_clear()


EXPECTED_FAMILIES = (
    "band",
    "playfair",
    "postal",
    "metromap",
    "boardingpass",
    "librarycard",
    "menu",
    "gradient",
    "invoice",
    "exhibition",
    "weekly",
    "receipt",
    "swiss",
    "dayline",
    "playbill",
    "memo",
    "broadsheet",
    "almanac",
    "flightplan",
    "instrument",
)

EXPECTED_ASSET_KEYS = {
    "ART1",
    "BAND",
    "STAMP_TOKYO",
    "STAMP_LONDON",
    "STAMP_PARIS",
    "STAMP_VENICE",
    "STAMP_ROME",
    "STAMP_KYOTO",
    "STAMP_NEWYORK",
    "STAMP_AMSTERDAM",
    "STAMP_ISTANBUL",
    "STAMP_AGRA",
}


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kicker": "Daily brief",
        "date": "2026-07-05",
        "headline": "A quiet Sunday",
        "lede": "Two approvals and one flight.",
        "stats": [{"value": "3", "label": "Done overnight"}],
        "sections": [
            {"numeral": "I", "title": "Today", "items": [{"text": "Standup", "kind": "note"}]},
        ],
        "caption": "Made by GAIA",
    }
    payload.update(overrides)
    return payload


def _render(payload: dict[str, Any] | None = None, **overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "family": "swiss",
        "skin_seed": "2026-07-05",
        "edition_no": 12,
        "generated_local": "6:02 AM",
    }
    kwargs.update(overrides)
    return render_explorer_edition(payload or _payload(), **kwargs)


def _embedded_const(html: str, name: str) -> Any:
    match = re.search(rf"^const {name} = (.*);$", html, re.MULTILINE)
    assert match is not None, f"{name} literal not found in the document"
    return json.loads(match.group(1).replace("<\\/", "</").replace("<\\!--", "<!--"))


@pytest.mark.unit
class TestFamilyIds:
    def test_ids_are_read_from_the_vendored_register_calls(self) -> None:
        assert explorer_family_ids() == EXPECTED_FAMILIES

    def test_there_are_twenty_distinct_families(self) -> None:
        ids = explorer_family_ids()

        assert len(ids) == 20
        assert len(set(ids)) == 20

    def test_axis_option_ids_are_not_mistaken_for_families(self) -> None:
        ids = explorer_family_ids()

        for axis_option in ("thermal", "canary", "slate", "putty", "baize", "walnut"):
            assert axis_option not in ids

    def test_result_is_cached_so_the_js_files_are_read_once(self) -> None:
        assert explorer_family_ids() is explorer_family_ids()


@pytest.mark.unit
class TestUnknownFamily:
    def test_unknown_family_raises_before_any_document_is_built(self) -> None:
        with pytest.raises(ValueError, match=r"^unknown explorer family: 'nope'$"):
            _render(family="nope")

    def test_empty_family_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"^unknown explorer family: ''$"):
            _render(family="")

    def test_an_axis_option_id_is_not_an_accepted_family(self) -> None:
        with pytest.raises(ValueError, match="unknown explorer family"):
            _render(family="thermal")


@pytest.mark.unit
class TestDocumentShell:
    def test_document_is_a_full_html_page_at_the_1180px_canvas(self) -> None:
        html = _render()

        assert html.startswith('<!doctype html>\n<html lang="en">')
        assert html.endswith("</body>\n</html>")
        assert '<meta name="viewport" content="width=1180">' in html
        assert "body { width: 1180px; }" in html

    def test_root_node_and_render_call_are_present(self) -> None:
        html = _render()

        assert '<div id="root"></div>' in html
        assert "const article = tpl.render(ed, skin);" in html
        assert 'document.getElementById("root").innerHTML = article;' in html

    def test_every_vendored_module_is_inlined(self) -> None:
        html = _render()

        assert html.count("EXPLORER.register({") == 20
        assert len(_module_sources()) == 10

    def test_each_module_gets_its_own_script_tag_on_its_own_line(self) -> None:
        html = _render()

        # 10 modules => 9 joins between them, plus the shim before and the
        # bootstrap after — anything else means the modules ran together.
        assert html.count("</script>\n<script>") == 11

    def test_deterministic_rng_shim_is_inlined(self) -> None:
        html = _render()

        assert "function mulberry32(a) {" in html
        assert "function strSeed(s) {" in html

    def test_five_font_faces_are_embedded_as_data_uris(self) -> None:
        html = _render()

        assert html.count("@font-face{") == 5
        assert html.count("font-family:'Aeonik Extended'") == 2
        assert html.count("font-family:'Playfair Display'") == 3
        assert html.count("font-style:italic") == 1
        assert "src:url(data:font/woff2;base64," in html
        # The rules are concatenated with nothing between them, so each one
        # butts straight against the next.
        assert html.count("format('woff2');}@font-face{") == 4


@pytest.mark.unit
class TestEmbeddedLiterals:
    def test_family_literal_matches_the_requested_family(self) -> None:
        assert _embedded_const(_render(family="memo"), "FAMILY") == "memo"

    def test_skin_seed_literal_is_namespaced_by_family(self) -> None:
        html = _render(family="memo", skin_seed="2026-07-05")

        assert _embedded_const(html, "SKIN_SEED") == "2026-07-05|memo"

    def test_same_seed_and_family_produce_a_byte_identical_document(self) -> None:
        assert _render() == _render()

    def test_a_different_family_changes_the_document(self) -> None:
        assert _render(family="memo") != _render(family="swiss")

    def test_ed_literal_carries_the_adapted_payload(self) -> None:
        ed = _embedded_const(_render(), "ed")

        assert ed["editionNo"] == 12
        assert ed["n"] == 12
        assert ed["time"] == "6:02 AM"
        assert ed["time24"] == "06:02"
        assert ed["deck"] == "Two approvals and one flight."
        assert ed["dateLong"] == "Sunday, 5 July 2026"
        assert ed["content"]["today"][0]["label"] == "Standup"
        assert ed["content"]["stats"]["done"] == 3

    def test_art_credit_comes_from_the_vendored_credits_file(self) -> None:
        ed = _embedded_const(_render(), "ed")

        assert ed["art"]["title"] == "Wheat Field with Cypresses"
        assert ed["art"]["artist"] == "Vincent van Gogh"

    def test_asset_map_is_restricted_to_the_known_mime_keys(self) -> None:
        ed = _embedded_const(_render(), "ed")

        assert set(ed["assets"]) == EXPECTED_ASSET_KEYS
        assert ed["assets"]["ART1"].startswith("data:image/jpeg;base64,")
        assert ed["assets"]["BAND"].startswith("data:image/webp;base64,")
        assert ed["art"]["src"] == ed["assets"]["ART1"]

    def test_assets_are_exposed_on_the_explorer_shim_too(self) -> None:
        html = _render()

        shim_match = re.search(r"^  assets: (\{.*\}),$", html, re.MULTILINE)

        assert shim_match is not None
        assert json.loads(shim_match.group(1)) == _embedded_const(html, "ed")["assets"]


@pytest.mark.unit
class TestArtCredit:
    def test_credit_is_the_art1_entry_of_the_vendored_credits_file(self) -> None:
        assert _art_credit() == "Wheat Field with Cypresses — Vincent van Gogh"

    def test_a_credits_file_without_art1_degrades_to_an_empty_credit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty string, never None: build_ed splits the credit on an em dash,
        # so a None here would crash the render instead of dropping the caption.
        (tmp_path / "credits.json").write_text(json.dumps({"STAMP_ROME": "A statue — Someone"}))
        monkeypatch.setattr(explorer_render, "_ASSETS_DIR", tmp_path)

        assert _art_credit() == ""


@pytest.mark.unit
class TestScriptEscaping:
    def test_payload_text_cannot_close_the_inline_script_tag(self) -> None:
        html = _render(_payload(lede="</script><img src=x>"))

        assert "</script><img src=x>" not in html
        assert '"deck": "<\\/script><img src=x>"' in html

    def test_payload_text_cannot_open_an_html_comment(self) -> None:
        html = _render(_payload(lede="<!--hide"))

        assert "<!--hide" not in html
        assert "<\\!--hide" in html

    def test_escaped_payload_still_decodes_to_the_original_text(self) -> None:
        ed = _embedded_const(_render(_payload(lede="</script><!--boom")), "ed")

        assert ed["deck"] == "</script><!--boom"

    def test_item_text_is_escaped_for_the_script_context_as_well(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "Today",
                        "items": [{"text": "</script>alert(1)", "kind": "note"}],
                    }
                ]
            )
        )

        assert "</script>alert(1)" not in html
        assert "<\\/script>alert(1)" in html


@pytest.mark.unit
class TestTimezoneLabel:
    def test_tz_label_is_accepted_for_parity_and_changes_nothing(self) -> None:
        assert _render(tz_label="IST") == _render(tz_label="")

    def test_tz_label_never_reaches_the_document(self) -> None:
        assert "Antarctica/Troll" not in _render(tz_label="Antarctica/Troll")
