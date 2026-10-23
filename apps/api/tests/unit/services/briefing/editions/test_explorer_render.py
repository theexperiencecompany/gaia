"""Unit tests for the vendored-explorer HTML document builder.

Assertions are on the document itself (inlined modules, embedded ed/seed literals,
script-tag escaping, the failure path), not on rastered pixels.
"""

from collections.abc import Iterator
import json
import re
from typing import Any

import pytest

from app.models.briefing_models import BriefingPayload
from app.services.briefing.editions.artworks import ARTWORKS
from app.services.briefing.editions.explorer_render import (
    _asset_data_uris,
    _font_faces_css,
    _module_sources,
    _raw_assets,
    explorer_family_ids,
    render_explorer_edition,
)
from app.services.briefing.editions.stamps import hosted_stamp_weights, stamp_asset_url, stamp_for

# Every loader is @lru_cache(maxsize=1) and the cache outlives the test that fills it,
# so each test must start cold.
_CACHED_LOADERS = (
    _module_sources,
    explorer_family_ids,
    _raw_assets,
    _asset_data_uris,
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
    "broadsheet",
    "gradient",
    "exhibition",
    "weekly",
    "librarycard",
    "menu",
    "invoice",
    "postal",
    "swiss",
    "memo",
    "almanac",
    "receipt",
    "flightplan",
    "instrument",
    "metromap",
    "boardingpass",
)

EXPECTED_ASSET_KEYS = {"BAND", "TEC_MARK"}


def _payload(**overrides: Any) -> BriefingPayload:
    payload: dict[str, Any] = {
        "kicker": "Daily brief",
        "date": "2026-07-05",
        "headline": "A quiet Sunday",
        "lede": "Two approvals and one flight.",
        "tallies": {"done_by_you": 1, "done_by_gaia": 2},
        "calendar": [{"date": "2026-07-05", "start": "09:00", "title": "Standup"}],
        "mood": "clear",
        "caption": "Made by GAIA",
    }
    payload.update(overrides)
    return BriefingPayload.model_validate(payload)


def _render(payload: BriefingPayload | None = None, **overrides: Any) -> str:
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

    def test_there_are_eighteen_distinct_families_and_no_cut_ones(self) -> None:
        ids = explorer_family_ids()

        assert len(ids) == 18
        assert len(set(ids)) == 18
        assert "playbill" not in ids
        assert "dayline" not in ids

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
    def test_document_is_a_full_html_page_at_the_540px_canvas(self) -> None:
        html = _render()

        assert html.startswith('<!doctype html>\n<html lang="en">')
        assert html.endswith("</body>\n</html>")
        assert '<meta name="viewport" content="width=540">' in html
        assert "body { width: 540px; }" in html

    def test_root_node_and_render_call_are_present(self) -> None:
        html = _render()

        assert '<div id="root"></div>' in html
        assert "const article = tpl.render(ed, skin);" in html
        assert 'document.getElementById("root").innerHTML = article;' in html

    def test_every_vendored_module_is_inlined(self) -> None:
        html = _render()

        assert html.count("EXPLORER.register({") == 18
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
        # The templates' own inline SVG styles name these fonts too; count the head's rules only.
        faces = html[html.index("@font-face{") : html.index("* { margin")]

        assert html.count("@font-face{") == 5
        assert faces.count("font-family:'Aeonik Extended'") == 2
        assert faces.count("font-family:'Playfair Display'") == 3
        assert faces.count("font-style:italic") == 1
        assert "src:url(data:font/woff2;base64," in faces
        # The rules are concatenated with nothing between them, so each one
        # butts straight against the next.
        assert faces.count("format('woff2');}@font-face{") == 4


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
        assert ed["deck"] == "A quiet Sunday"
        assert ed["dateLong"] == "Sunday, 5 July 2026"
        assert ed["content"]["today"][0]["label"] == "Standup"
        assert ed["content"]["stats"]["done"] == 3

    def test_the_painting_and_its_catalogue_line_come_from_the_artwork_pool(self) -> None:
        artwork = ARTWORKS[12 % len(ARTWORKS)]

        art = _embedded_const(_render(edition_no=12), "ed")["art"]

        assert (art["title"], art["artist"]) == (artwork.title, artwork.artist)
        assert (art["year"], art["medium"]) == (artwork.year, artwork.medium)
        assert art["src"] == f"data:image/jpeg;base64,{_raw_assets()[artwork.asset_key]}"

    def test_consecutive_editions_hang_different_paintings(self) -> None:
        titles = [
            _embedded_const(_render(edition_no=n), "ed")["art"]["title"]
            for n in range(len(ARTWORKS))
        ]

        assert sorted(titles) == sorted(a.title for a in ARTWORKS)

    def test_the_asset_map_is_the_band_and_the_experience_company_mark(self) -> None:
        ed = _embedded_const(_render(), "ed")

        assert set(ed["assets"]) == EXPECTED_ASSET_KEYS
        assert ed["assets"]["BAND"].startswith("data:image/webp;base64,")
        assert ed["assets"]["TEC_MARK"].startswith("data:image/webp;base64,UklGR")

    def test_assets_are_exposed_on_the_explorer_shim_too(self) -> None:
        html = _render()

        shim_match = re.search(r"^  assets: (\{.*\}),$", html, re.MULTILINE)

        assert shim_match is not None
        assert json.loads(shim_match.group(1)) == _embedded_const(html, "ed")["assets"]

    def test_every_family_leads_with_the_headline(self) -> None:
        ed = _embedded_const(_render(family="memo"), "ed")

        assert ed["deck"] == "A quiet Sunday"


@pytest.mark.unit
class TestPostalStamp:
    def test_postal_loads_the_drawn_citys_hosted_art_as_the_stamp_asset(self) -> None:
        html = _render(_payload(stamp_city="paris"), family="postal")
        ed = _embedded_const(html, "ed")

        assert set(ed["assets"]) == EXPECTED_ASSET_KEYS | {"CITY_PARIS"}
        assert ed["assets"]["CITY_PARIS"] == stamp_asset_url("paris")
        assert ed["assets"]["CITY_PARIS"].startswith("https://")
        assert ed["stamp"]["id"] == "paris"
        assert ed["stamp"]["key"] == "CITY_PARIS"

    def test_postal_without_a_drawn_city_loads_every_hosted_citys_art(self) -> None:
        ed = _embedded_const(_render(family="postal"), "ed")

        hosted = hosted_stamp_weights()
        assert len(hosted) == 85
        assert set(ed["assets"]) == EXPECTED_ASSET_KEYS | {
            f"CITY_{slug.upper()}" for slug in hosted
        }
        assert ed["assets"]["CITY_NEW_YORK_CITY"] == stamp_asset_url("new_york_city")
        assert ed["stamp"] is None

    def test_the_template_city_axis_is_every_hosted_city(self) -> None:
        html = _render(family="swiss")
        match = re.search(r"\n  cities: (\[.*?\]),\n\};", html, re.S)

        assert match is not None
        cities = json.loads(match.group(1))
        assert [c["id"] for c in cities] == list(hosted_stamp_weights())
        assert cities[0] == stamp_for(cities[0]["id"])

    def test_other_families_ignore_the_stamp_city(self) -> None:
        ed = _embedded_const(_render(_payload(stamp_city="paris"), family="swiss"), "ed")

        assert set(ed["assets"]) == EXPECTED_ASSET_KEYS
        assert ed["stamp"] is None

    def test_a_postal_city_without_hosted_art_fails_loud(self) -> None:
        with pytest.raises(KeyError, match="atlantis"):
            _render(_payload(stamp_city="atlantis"), family="postal")


@pytest.mark.unit
class TestScriptEscaping:
    def test_payload_text_cannot_close_the_inline_script_tag(self) -> None:
        html = _render(_payload(headline="</script><img src=x>"))

        assert "</script><img src=x>" not in html
        assert '"deck": "<\\/script><img src=x>"' in html

    def test_payload_text_cannot_open_an_html_comment(self) -> None:
        html = _render(_payload(headline="<!--hide"))

        assert "<!--hide" not in html
        assert "<\\!--hide" in html

    def test_escaped_payload_still_decodes_to_the_original_text(self) -> None:
        ed = _embedded_const(_render(_payload(headline="</script><!--boom")), "ed")

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
