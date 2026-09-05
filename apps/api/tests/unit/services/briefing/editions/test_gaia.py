"""Unit tests for the GAIA-design-language edition renderer.

``render_edition`` is pure and returns a self-contained HTML document, so
every test asserts on the exact markup fragment the renderer emits — the
dateline, the stat strip, section numerals, item markers, and the branches
that omit a block entirely.
"""

from typing import Any

import pytest

from app.services.briefing.editions.gaia import render_edition

ACCENT = "#00bbff"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kicker": "Daily brief",
        "date": "2026-07-05",
        "headline": "A quiet Sunday",
        "lede": "Two approvals and one flight.",
        "stats": [],
        "sections": [],
        "caption": "Made by GAIA",
    }
    payload.update(overrides)
    return payload


def _render(payload: dict[str, Any] | None = None, **overrides: Any) -> str:
    kwargs: dict[str, Any] = {"edition_no": 12, "generated_local": "6:02 AM"}
    kwargs.update(overrides)
    return render_edition(_payload() if payload is None else payload, **kwargs)


@pytest.mark.unit
class TestDocumentShell:
    def test_document_is_a_full_html_page_at_the_1180px_canvas(self) -> None:
        html = _render()

        assert html.startswith('<!doctype html>\n<html lang="en">')
        assert html.endswith("</body>\n</html>")
        assert '<meta name="viewport" content="width=1180">' in html
        assert "width: 1180px;" in html

    def test_masthead_carries_the_wordmark_and_the_accent_mark(self) -> None:
        html = _render()

        assert '<span class="wordmark">GAIA</span>' in html
        assert '<span class="mark"></span>' in html

    def test_both_editorial_font_weights_are_embedded_as_data_uris(self) -> None:
        html = _render()

        assert html.count("@font-face{font-family:'PP Editorial New'") == 2
        assert html.count("font-weight:200;font-display:block") == 1
        assert html.count("font-weight:400;font-display:block") == 1
        assert "src:url(data:font/woff2;base64," in html

    def test_cyan_is_the_accent_on_the_mark_marker_and_numeral(self) -> None:
        html = _render()

        assert (
            f".mark {{\n  width: 10px;\n  height: 10px;\n  border-radius: 3px;\n  background: {ACCENT};"
            in html
        )
        assert ".marker.accent { color: #00bbff; }" in html
        assert ".numeral" in html and "color: #00bbff;" in html

    def test_rendering_the_same_payload_twice_is_byte_identical(self) -> None:
        assert _render() == _render()


@pytest.mark.unit
class TestDateline:
    def test_dateline_joins_date_edition_and_generation_time(self) -> None:
        html = _render()

        assert (
            '<div class="dateline">July 5, 2026 &middot; Edition 12 &middot; Generated 6:02 AM</div>'
            in html
        )

    def test_timezone_label_is_appended_after_a_thin_space(self) -> None:
        html = _render(tz_label="IST")

        assert "Generated 6:02 AM&#8201;IST</div>" in html

    def test_no_timezone_label_leaves_the_time_bare(self) -> None:
        html = _render(tz_label="")

        assert "Generated 6:02 AM</div>" in html
        assert "&#8201;" not in html.split('<div class="dateline">')[1].split("</div>")[0]

    def test_edition_number_is_printed_verbatim(self) -> None:
        html = _render(edition_no=7)

        assert "&middot; Edition 7 &middot;" in html

    def test_unparseable_date_is_escaped_into_the_dateline(self) -> None:
        html = _render(_payload(date="<b>soon</b>"))

        assert '<div class="dateline">&lt;b&gt;soon&lt;/b&gt; &middot; Edition 12' in html

    def test_generation_time_is_escaped(self) -> None:
        html = _render(generated_local='"><script>x</script>')

        assert "<script>x</script>" not in html
        assert "Generated &quot;&gt;&lt;script&gt;x&lt;/script&gt;" in html

    def test_timezone_label_is_escaped(self) -> None:
        html = _render(tz_label="<i>IST</i>")

        assert "<i>IST</i>" not in html
        assert "&#8201;&lt;i&gt;IST&lt;/i&gt;" in html


@pytest.mark.unit
class TestHero:
    def test_headline_and_lede_are_rendered(self) -> None:
        html = _render()

        assert '<h1 class="headline">A quiet Sunday</h1>' in html
        assert '<p class="lede">Two approvals and one flight.</p>' in html

    def test_headline_is_html_escaped(self) -> None:
        html = _render(_payload(headline='<script>alert("x")</script>'))

        assert "<script>alert" not in html
        assert '<h1 class="headline">&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;</h1>' in html

    def test_empty_lede_omits_the_paragraph_entirely(self) -> None:
        html = _render(_payload(lede=""))

        assert 'class="lede"' not in html
        assert '<h1 class="headline">A quiet Sunday</h1>\n      \n    </section>' in html

    def test_empty_kicker_omits_the_kicker_div(self) -> None:
        html = _render(_payload(kicker=""))

        assert 'class="kicker"' not in html
        assert '<span class="wordmark">GAIA</span>\n        \n      </div>' in html

    def test_kicker_is_rendered_and_escaped(self) -> None:
        html = _render(_payload(kicker="Weekly & digest"))

        assert '<div class="kicker">Weekly &amp; digest</div>' in html

    def test_empty_caption_omits_the_colophon(self) -> None:
        html = _render(_payload(caption=""))

        assert '<footer class="colophon">' not in html
        assert html.endswith("</div>\n\n    \n  </div>\n</main>\n</body>\n</html>")

    def test_caption_is_rendered_as_the_colophon(self) -> None:
        html = _render()

        assert '<footer class="colophon">Made by GAIA</footer>' in html


@pytest.mark.unit
class TestStats:
    def test_no_stats_omits_the_strip(self) -> None:
        html = _render(_payload(stats=[]))

        assert '<div class="stats">' not in html
        assert '</section>\n\n    \n\n    <div class="sections">' in html

    def test_each_stat_renders_value_then_label(self) -> None:
        html = _render(
            _payload(
                stats=[
                    {"value": "12", "label": "drafts staged"},
                    {"value": "3", "label": "need you"},
                ]
            )
        )

        assert (
            '<div class="stats">'
            '<div class="stat"><span class="s-value">12</span>'
            '<span class="s-label">drafts staged</span></div>'
            '<div class="stat"><span class="s-value">3</span>'
            '<span class="s-label">need you</span></div>'
            "</div>"
        ) in html

    def test_delta_renders_inside_the_value(self) -> None:
        html = _render(_payload(stats=[{"value": "12", "label": "done", "delta": "+4"}]))

        assert (
            '<span class="s-value">12<span class="s-delta">+4</span></span>'
            '<span class="s-label">done</span>'
        ) in html

    def test_absent_delta_emits_no_delta_span(self) -> None:
        html = _render(_payload(stats=[{"value": "12", "label": "done"}]))

        assert '<span class="s-value">12</span>' in html
        assert '<span class="s-delta">' not in html

    def test_empty_delta_string_emits_no_delta_span(self) -> None:
        html = _render(_payload(stats=[{"value": "12", "label": "done", "delta": ""}]))

        assert '<span class="s-value">12</span>' in html
        assert '<span class="s-delta">' not in html

    def test_stat_text_is_escaped(self) -> None:
        html = _render(_payload(stats=[{"value": "<b>1</b>", "label": "a & b", "delta": "<i>"}]))

        assert '<span class="s-value">&lt;b&gt;1&lt;/b&gt;' in html
        assert '<span class="s-label">a &amp; b</span>' in html
        assert '<span class="s-delta">&lt;i&gt;</span>' in html

    def test_missing_value_and_label_keys_render_empty(self) -> None:
        html = _render(_payload(stats=[{}]))

        assert (
            '<div class="stat"><span class="s-value"></span><span class="s-label"></span></div>'
            in html
        )


@pytest.mark.unit
class TestSections:
    def test_section_renders_its_numeral_title_and_items(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "Today",
                        "items": [{"text": "Standup at nine", "kind": "note"}],
                    }
                ]
            )
        )

        assert '<span class="numeral">I</span>' in html
        assert '<span class="s-title">Today</span>' in html
        assert '<p class="item"><span class="i-text">Standup at nine</span></p>' in html

    def test_section_with_no_items_is_omitted(self) -> None:
        html = _render(
            _payload(sections=[{"numeral": "I", "title": "Today", "items": []}]),
        )

        assert 'class="section-head"' not in html
        assert "Today" not in html
        assert '<div class="sections">\n\n    </div>' in html

    def test_sections_render_in_payload_order(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {"numeral": "I", "title": "First", "items": [{"text": "a", "kind": "note"}]},
                    {"numeral": "II", "title": "Second", "items": [{"text": "b", "kind": "note"}]},
                ]
            )
        )

        assert html.index('<span class="s-title">First</span>') < html.index(
            '<span class="s-title">Second</span>'
        )

    def test_adjacent_sections_are_separated_by_a_single_newline(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {"numeral": "I", "title": "First", "items": [{"text": "a", "kind": "note"}]},
                    {"numeral": "II", "title": "Second", "items": [{"text": "b", "kind": "note"}]},
                ]
            )
        )

        assert '      </section>\n      <section class="section">' in html

    def test_section_missing_its_numeral_and_title_renders_them_empty(self) -> None:
        html = _render(_payload(sections=[{"items": [{"text": "a", "kind": "note"}]}]))

        assert '<span class="numeral"></span>' in html
        assert '<span class="s-title"></span>' in html

    def test_section_numeral_and_title_are_escaped(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {
                        "numeral": "<I>",
                        "title": "Ana & Bo",
                        "items": [{"text": "x", "kind": "note"}],
                    }
                ]
            )
        )

        assert '<span class="numeral">&lt;I&gt;</span>' in html
        assert '<span class="s-title">Ana &amp; Bo</span>' in html

    def test_no_sections_leaves_the_container_empty(self) -> None:
        html = _render(_payload(sections=[]))

        assert '<div class="sections">\n\n    </div>' in html


@pytest.mark.unit
class TestItemMarkers:
    @pytest.mark.parametrize(
        ("kind", "marker", "tone"),
        [
            ("proposal", "Needs your approval", "accent"),
            ("needs_you", "Your move", "accent"),
            ("you", "Your move", "accent"),
            ("lookback", "Done", "dim"),
            ("gaia", "Done", "dim"),
        ],
    )
    def test_kind_maps_to_its_marker_and_tone(self, kind: str, marker: str, tone: str) -> None:
        html = _render(
            _payload(
                sections=[
                    {"numeral": "I", "title": "T", "items": [{"text": "a thing", "kind": kind}]}
                ]
            )
        )

        assert (
            f'<p class="item"><span class="marker {tone}">{marker}</span>'
            f'<span class="i-text">a thing</span></p>'
        ) in html

    @pytest.mark.parametrize("kind", ["note", "made-up-kind"])
    def test_plain_and_unknown_kinds_carry_no_marker(self, kind: str) -> None:
        html = _render(
            _payload(
                sections=[
                    {"numeral": "I", "title": "T", "items": [{"text": "a thing", "kind": kind}]}
                ]
            )
        )

        assert 'class="marker' not in html.split('<div class="items">')[1]
        assert '<p class="item"><span class="i-text">a thing</span></p>' in html

    def test_item_without_a_kind_defaults_to_no_marker(self) -> None:
        html = _render(
            _payload(sections=[{"numeral": "I", "title": "T", "items": [{"text": "bare"}]}])
        )

        assert '<p class="item"><span class="i-text">bare</span></p>' in html

    def test_item_text_is_escaped(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "T",
                        "items": [{"text": "<img src=x onerror=1>", "kind": "note"}],
                    }
                ]
            )
        )

        assert "<img src=x" not in html
        assert "&lt;img src=x onerror=1&gt;" in html

    def test_linked_item_gets_the_open_hint_and_never_the_raw_url(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "T",
                        "items": [
                            {
                                "text": "Draft ready",
                                "kind": "gaia",
                                "link": "https://heygaia.link/abc123",
                            }
                        ],
                    }
                ]
            )
        )

        assert '<span class="open">&middot;&#8201;Open</span>' in html
        assert "heygaia.link" not in html
        assert (
            '<span class="i-text">Draft ready<span class="open">&middot;&#8201;Open</span></span>'
            in html
        )

    def test_item_without_a_link_has_no_open_hint(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {"numeral": "I", "title": "T", "items": [{"text": "Draft", "kind": "gaia"}]}
                ]
            )
        )

        assert 'class="open"' not in html.split('<div class="items">')[1]

    def test_items_render_in_payload_order(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "T",
                        "items": [
                            {"text": "first", "kind": "note"},
                            {"text": "second", "kind": "note"},
                        ],
                    }
                ]
            )
        )

        assert html.index(">first<") < html.index(">second<")

    def test_adjacent_items_are_separated_by_a_single_newline(self) -> None:
        html = _render(
            _payload(
                sections=[
                    {
                        "numeral": "I",
                        "title": "T",
                        "items": [
                            {"text": "first", "kind": "note"},
                            {"text": "second", "kind": "note"},
                        ],
                    }
                ]
            )
        )

        assert '</p>\n          <p class="item">' in html

    def test_item_missing_its_text_renders_an_empty_text_span(self) -> None:
        html = _render(_payload(sections=[{"numeral": "I", "title": "T", "items": [{}]}]))

        assert '<p class="item"><span class="i-text"></span></p>' in html


@pytest.mark.unit
class TestMissingPayloadKeys:
    """A payload with a key absent renders the slot empty — never ``"None"``."""

    def test_missing_headline_renders_an_empty_headline(self) -> None:
        assert '<h1 class="headline"></h1>' in _render({})

    def test_missing_kicker_lede_and_caption_render_no_element_at_all(self) -> None:
        html = _render({})

        assert 'class="kicker"' not in html
        assert 'class="lede"' not in html
        assert 'class="colophon"' not in html

    def test_missing_date_drops_the_dateline_segment_rather_than_filling_it(self) -> None:
        html = _render({})

        assert '<div class="dateline">Edition 12 &middot; Generated 6:02 AM</div>' in html
