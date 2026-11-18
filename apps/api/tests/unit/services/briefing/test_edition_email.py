"""Unit tests for the edition-as-image briefing email.

The rasterizer is faked at the boundary this module imports it from; the edition renderer is faked so the assertions pin *this* module's
contract (options, public id, escaping, the message as text) rather
than the edition template's markup. The email wraps an already-stored image, so
its tests also prove it never rasterizes a second copy.
"""

from typing import Any

from pydantic import ValidationError
import pytest

from app.config.settings import settings
from app.constants.briefing import (
    FOLD_MARKER_SELECTOR,
    PAPER_MARKER_SELECTOR,
    EditionFamily,
)
from app.models.brief_payload_models import BriefingPayload
from app.services.briefing import edition_email
from app.services.briefing.edition_email import (
    render_edition_email,
    render_edition_png,
)
from app.services.briefing.editions import EXPLORER_RENDERER
from app.services.render.image import RenderedImage

IMAGE_URL = "https://cdn.example.com/edition.png"
BRIEFING_ID = "brief-1"
BRIEF_URL = "https://heygaia.link/brief1short"
UNSUBSCRIBE_URL = "https://heygaia.io/unsubscribe?t=abc"
FRONTEND_URL = "https://app.example.com"

MESSAGE = "Priya's deck needs a yes.\nSequoia at 11:00.\n\nThe investor update went out."

# The strip is what an image-blocked inbox actually shows, so its markup is
# pinned verbatim: a dropped tag, a changed colour or a lost HTML entity is a
# regression the reader of the mail would see, and only exact text catches it.
_SANS = "Inter,-apple-system,Helvetica,Arial,sans-serif"
_PARAGRAPH = f'<p style="margin:0 0 14px 0;font:400 15px/1.6 {_SANS};color:#f4f4f5;">'
EXPECTED_STRIP = (
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
    'style="max-width:600px;margin:0 auto;background:#000000;">'
    '<tr><td style="padding:24px 32px 4px 32px;">'
    f"{_PARAGRAPH}Priya&#x27;s deck needs a yes.<br>Sequoia at 11:00.</p>"
    f"{_PARAGRAPH}The investor update went out.</p></td></tr>"
    '<tr><td align="center" style="padding:12px 24px 8px 24px;">'
    f'<a href="{BRIEF_URL}" style="display:inline-block;background:#00bbff;'
    f"color:#000000;text-decoration:none;font:600 15px/1.2 {_SANS};"
    'padding:13px 30px;border-radius:10px;">'
    "Open today&#39;s brief in GAIA</a></td></tr>"
    '<tr><td align="center" style="padding:20px 24px 28px 24px;">'
    f'<div style="font:400 11px/1.5 {_SANS};color:#a1a1aa;">'
    "You get this because daily briefs are on in GAIA. "
    f'<a href="{UNSUBSCRIBE_URL}" style="color:#a1a1aa;">Unsubscribe</a>.'
    "</div></td></tr></table>"
)
EXPECTED_EMAIL = (
    '<div style="margin:0;padding:0;background:#000000;">'
    '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
    "Priya&#x27;s deck needs a yes. Sequoia at 11:00. The investor update went out.</div>"
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
    'style="background:#000000;">'
    '<tr><td align="center" style="padding:0;">'
    f'<a href="{BRIEF_URL}" style="text-decoration:none;">'
    f'<img src="{IMAGE_URL}" alt="Your Friday — Three things need you." width="600" '
    'style="display:block;width:100%;max-width:600px;height:auto;border:0;" /></a>'
    "</td></tr></table>" + EXPECTED_STRIP + "</div>"
)


def make_payload(**overrides: Any) -> BriefingPayload:
    payload: dict[str, Any] = {
        "kicker": "THE MORNING BRIEF",
        "date": "2026-01-10",
        "headline": "Your Friday",
        "lede": "Three things need you.",
        "sections": [],
        "mood": "clear",
        "caption": "Onward.",
        "message": MESSAGE,
        "template_family": "swiss",
    }
    payload.update(overrides)
    return BriefingPayload.model_validate(payload)


class Harness:
    def __init__(self) -> None:
        self.image = b"edition-png-bytes"
        self.fold: float | None = 0.31
        self.paper: tuple[float, float, float, float] | None = None
        self.render_calls: list[dict[str, Any]] = []
        self.image_calls: list[dict[str, Any]] = []
        self.render_error: Exception | None = None


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    h = Harness()

    def fake_renderer(family: str) -> Any:
        def render(payload: BriefingPayload, **kwargs: Any) -> str:
            h.render_calls.append({"renderer": family, "payload": payload, **kwargs})
            return f"<edition>{family}</edition>"

        return render

    async def fake_render_html_to_image(html: str, options: Any) -> RenderedImage:
        h.image_calls.append({"html": html, "options": options})
        if h.render_error is not None:
            raise h.render_error
        return RenderedImage(image=h.image, fold=h.fold, paper=h.paper)

    monkeypatch.setattr(
        edition_email,
        "EXPLORER_RENDERER",
        {family: fake_renderer(family) for family in EXPLORER_RENDERER},
    )
    monkeypatch.setattr(edition_email, "render_html_to_image", fake_render_html_to_image)
    monkeypatch.setattr(settings, "FRONTEND_URL", FRONTEND_URL)
    return h


def render(payload: BriefingPayload, **overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "image_url": IMAGE_URL,
        "brief_url": BRIEF_URL,
        "unsubscribe_url": UNSUBSCRIBE_URL,
    }
    kwargs.update(overrides)
    return render_edition_email(payload, **kwargs)


async def host(payload: BriefingPayload) -> RenderedImage:
    return await render_edition_png(payload, BRIEF_URL)


@pytest.mark.unit
class TestEditionRendering:
    async def test_the_payloads_family_renders_with_its_link_and_edition_number(
        self, harness: Harness
    ) -> None:
        await host(make_payload(date="2026-01-10", template_family=EditionFamily.RECEIPT))

        assert harness.render_calls == [
            {
                "renderer": "receipt",
                "payload": make_payload(date="2026-01-10", template_family=EditionFamily.RECEIPT),
                "link": BRIEF_URL,
                "edition_no": 10,
            }
        ]
        assert harness.image_calls[0]["html"] == "<edition>receipt</edition>"

    def test_a_payload_without_a_family_fails_validation(self) -> None:
        data = make_payload().model_dump()
        del data["template_family"]

        with pytest.raises(ValidationError, match="template_family"):
            BriefingPayload.model_validate(data)

    def test_a_brief_cannot_name_the_retired_classic_family(self) -> None:
        with pytest.raises(ValidationError, match="template_family"):
            make_payload(template_family="edition")

    async def test_a_quiet_note_has_no_edition_to_render(self, harness: Harness) -> None:
        with pytest.raises(ValueError, match="quiet note"):
            await host(make_payload(template_family=None))

        assert harness.render_calls == []

    async def test_edition_epoch_makes_the_first_of_january_2026_edition_one(
        self, harness: Harness
    ) -> None:
        await host(make_payload(date="2026-01-01"))

        assert harness.render_calls[0]["edition_no"] == 1

    @pytest.mark.parametrize("bad_date", ["not-a-date", ""])
    async def test_an_unparseable_date_fails_the_render_loudly(
        self, harness: Harness, bad_date: str
    ) -> None:
        with pytest.raises(ValueError, match="Invalid isoformat"):
            await host(make_payload(date=bad_date))


@pytest.mark.unit
class TestImage:
    async def test_a_paper_on_a_desk_is_trimmed_to_an_even_margin(self, harness: Harness) -> None:
        await host(make_payload(template_family=EditionFamily.MEMO))

        options = harness.image_calls[0]["options"]
        assert (options.width, options.device_scale_factor) == (636, 3)
        assert (options.clip_selector, options.trim_margin_px) == ("#root > article", 16)
        assert (options.clip_bleed_px, options.omit_background) == (48, True)

    async def test_the_render_is_asked_for_the_fold_and_paper_boxes_by_their_markers(
        self, harness: Harness
    ) -> None:
        await host(make_payload())

        options = harness.image_calls[0]["options"]
        assert options.fold_selector == FOLD_MARKER_SELECTOR
        assert options.paper_selector == PAPER_MARKER_SELECTOR

    async def test_the_paper_the_render_measured_is_what_it_returns(self, harness: Harness) -> None:
        harness.paper = (0.02, 0.03, 0.97, 0.9)

        hosted = await host(make_payload())

        assert hosted.paper == (0.02, 0.03, 0.97, 0.9)

    async def test_a_full_bleed_family_is_its_whole_page(self, harness: Harness) -> None:
        await host(make_payload(template_family=EditionFamily.SWISS))

        options = harness.image_calls[0]["options"]
        assert (options.width, options.device_scale_factor) == (540, 3)
        assert (options.clip_selector, options.trim_margin_px) == ("#root > article", None)
        assert (options.clip_bleed_px, options.omit_background) == (0, False)

    async def test_render_failure_propagates(self, harness: Harness) -> None:
        harness.render_error = RuntimeError("chromium died")

        with pytest.raises(RuntimeError, match="chromium died"):
            await host(make_payload())


@pytest.mark.unit
class TestEmailBody:
    def test_email_body_markup_is_exactly_this(self, harness: Harness) -> None:
        assert render(make_payload()) == EXPECTED_EMAIL

    def test_the_email_wraps_the_stored_image_without_rendering_a_second_copy(
        self, harness: Harness
    ) -> None:
        html = render(make_payload(), image_url="https://cdn.example.com/stored.png")

        assert 'src="https://cdn.example.com/stored.png"' in html
        assert harness.render_calls == []
        assert harness.image_calls == []

    def test_the_image_links_to_the_briefs_heygaia_link(self, harness: Harness) -> None:
        html = render(make_payload(), brief_url="https://heygaia.link/b9short")

        assert '<a href="https://heygaia.link/b9short" style="text-decoration:none;"><img' in html

    def test_image_url_is_html_escaped(self, harness: Harness) -> None:
        html = render(make_payload(), image_url="https://cdn.example.com/a.png?x=1&y=2")

        assert 'src="https://cdn.example.com/a.png?x=1&amp;y=2"' in html

    def test_preheader_is_the_message_hidden_ahead_of_the_image_and_escaped(
        self, harness: Harness
    ) -> None:
        html = render(make_payload(message="Pick <a>\n\nslot"))

        assert (
            '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
            "Pick &lt;a&gt; slot</div><table"
        ) in html

    def test_a_brief_without_a_message_cannot_be_emailed(self, harness: Harness) -> None:
        with pytest.raises(ValueError, match="no message"):
            render(make_payload(message=None))


@pytest.mark.unit
class TestAltText:
    def test_alt_joins_headline_and_lede(self, harness: Harness) -> None:
        html = render(make_payload(headline="Big day", lede="Two calls."))

        assert 'alt="Big day — Two calls."' in html

    def test_alt_drops_the_dangling_separator_when_there_is_no_lede(self, harness: Harness) -> None:
        html = render(make_payload(headline="Big day", lede=""))

        assert 'alt="Big day"' in html

    def test_alt_trims_only_the_separator_never_the_headlines_own_letters(
        self, harness: Harness
    ) -> None:
        html = render(make_payload(headline="Reply to MAX", lede=""))

        assert 'alt="Reply to MAX"' in html

    def test_alt_is_escaped(self, harness: Harness) -> None:
        html = render(make_payload(headline="R&D <b>", lede=""))

        assert 'alt="R&amp;D &lt;b&gt;"' in html


@pytest.mark.unit
class TestTextStrip:
    """The message the model wrote is the email's text, so it reads with images off."""

    def test_strip_markup_is_exactly_this(self, harness: Harness) -> None:
        assert (
            edition_email._text_strip(
                MESSAGE, BRIEF_URL, UNSUBSCRIBE_URL, edition_email._DAILY_WORDING
            )
            == EXPECTED_STRIP
        )

    def test_a_weekly_digest_says_weekly_digests_are_on(self, harness: Harness) -> None:
        html = render(make_payload(template_family=EditionFamily.WEEKLY))

        assert "You get this because weekly digests are on in GAIA. <a" in html
        assert "Open this week&#39;s digest in GAIA</a>" in html
        assert "today&#39;s brief" not in html

    def test_the_message_is_escaped(self, harness: Harness) -> None:
        html = render(make_payload(message="Pay <Acme> & co"))

        assert f"{_PARAGRAPH}Pay &lt;Acme&gt; &amp; co</p>" in html

    def test_blank_lines_split_paragraphs_and_extra_ones_add_nothing(
        self, harness: Harness
    ) -> None:
        html = edition_email._message_html("One.\n\n\n\nTwo.\n\n")

        assert html == f"{_PARAGRAPH}One.</p>{_PARAGRAPH}Two.</p>"

    def test_a_linked_phrase_is_an_anchor_on_the_phrase_not_a_pasted_url(
        self, harness: Harness
    ) -> None:
        html = edition_email._message_html(
            "The [venue <list>](https://heygaia.link/v?a=1&b=2) is up"
        )

        assert html == (
            f'{_PARAGRAPH}The <a href="https://heygaia.link/v?a=1&amp;b=2" '
            'style="color:#00bbff;">venue &lt;list&gt;</a> is up</p>'
        )

    def test_unsubscribe_url_is_escaped(self, harness: Harness) -> None:
        html = render(make_payload(), unsubscribe_url="https://heygaia.io/u?t=a&s=b")

        assert 'href="https://heygaia.io/u?t=a&amp;s=b"' in html


@pytest.mark.unit
class TestEditionNumber:
    def test_editions_count_days_from_the_epoch(self) -> None:
        assert edition_email._edition_no("2026-01-01") == 1
        assert edition_email._edition_no("2026-10-14") == 287
