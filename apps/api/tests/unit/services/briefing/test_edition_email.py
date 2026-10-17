"""Unit tests for the edition-as-image briefing email.

The rasterizer and the CDN upload are faked at the boundary this module imports
them from; the edition renderer is faked so the assertions pin *this* module's
contract (options, public id, link resolution, escaping, action strip) rather
than the edition template's markup. The email wraps an already-hosted image, so
its tests also prove it never rasterizes or uploads a second copy.
"""

from typing import Any
from uuid import uuid4

import cloudinary
import pytest

from app.config.settings import settings
from app.constants.briefing import EditionDeliveryFormat
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.models.briefing_models import BriefingPayload
from app.services.briefing import edition_email
from app.services.briefing.edition_email import (
    HostedEditionImage,
    edition_delivery_url,
    host_edition_image,
    is_edition_kind,
    render_edition_email,
)
from app.services.briefing.skim import full_brief_url

USER_ID = "user-abc"
IMAGE_URL = "https://cdn.example.com/edition.png"
BRIEFING_ID = "brief-1"
BRIEF_URL = "https://app.example.com/brief/brief-1"
UNSUBSCRIBE_URL = "https://heygaia.io/unsubscribe?t=abc"
FRONTEND_URL = "https://app.example.com"
CLOUD_NAME = "gaia-test"

# The strip is what an image-blocked inbox actually shows, so its markup is
# pinned verbatim — a dropped tag, a changed colour or a lost HTML entity is a
# regression the reader of the mail would see, and only exact text catches it.
_SANS = "Inter,-apple-system,Helvetica,Arial,sans-serif"
_STRIP_OPEN = (
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
    'style="max-width:600px;margin:0 auto;background:#000000;">'
    '<tr><td align="center" style="padding:24px 24px 8px 24px;">'
    f'<a href="{BRIEF_URL}" style="display:inline-block;background:#00bbff;'
    f"color:#000000;text-decoration:none;font:600 15px/1.2 {_SANS};"
    'padding:13px 30px;border-radius:10px;">'
    "Open today&#39;s brief in GAIA</a></td></tr>"
)
_STRIP_CLOSE = (
    '<tr><td align="center" style="padding:20px 24px 28px 24px;">'
    f'<div style="font:400 11px/1.5 {_SANS};color:#a1a1aa;">'
    "You&#39;re getting this because GAIA works your day. "
    f'<a href="{UNSUBSCRIBE_URL}" style="color:#a1a1aa;">Unsubscribe</a>.'
    "</div></td></tr></table>"
)
_REVIEW_LINK_STYLE = 'style="color:#00bbff;text-decoration:none;font-weight:600;">Review</a></div>'
EXPECTED_STRIP_WITHOUT_ACTIONS = _STRIP_OPEN + _STRIP_CLOSE
EXPECTED_STRIP_WITH_ACTIONS = (
    _STRIP_OPEN
    + '<tr><td style="padding:8px 32px 4px 32px;">'
    + f'<div style="font:600 12px/1.4 {_SANS};color:#a1a1aa;'
    + 'border-top:1px solid #27272a;padding-top:14px;">Waiting on your call</div>'
    + f'<div style="margin:7px 0;font:400 13px/1.5 {_SANS};color:#f4f4f5;">'
    + "Pay &lt;Acme&gt; &amp; co &nbsp;"
    + f'<a href="{FRONTEND_URL}/todos/1" '
    + _REVIEW_LINK_STYLE
    + f'<div style="margin:7px 0;font:400 13px/1.5 {_SANS};color:#f4f4f5;">'
    + " &nbsp;"
    + f'<a href="{FRONTEND_URL}/todos/2" '
    + _REVIEW_LINK_STYLE
    + "</td></tr>"
    + _STRIP_CLOSE
)
EXPECTED_EMAIL_WITHOUT_ACTIONS = (
    '<div style="margin:0;padding:0;background:#000000;">'
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
    'style="background:#000000;">'
    '<tr><td align="center" style="padding:0;">'
    f'<a href="{BRIEF_URL}" style="text-decoration:none;">'
    f'<img src="{IMAGE_URL}" alt="Your Friday — Three things need you." width="600" '
    'style="display:block;width:100%;max-width:600px;height:auto;border:0;" /></a>'
    "</td></tr></table>" + EXPECTED_STRIP_WITHOUT_ACTIONS + "</div>"
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
    }
    payload.update(overrides)
    return BriefingPayload.model_validate(payload)


def make_item(kind: str, text: str = "Send the invoice", link: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "text": text, "link": link}


def make_section(*items: dict[str, Any]) -> dict[str, Any]:
    return {"numeral": "I", "title": "NEEDS YOU", "items": list(items)}


class Harness:
    def __init__(self) -> None:
        self.image = b"edition-png-bytes"
        self.image_url = IMAGE_URL
        self.render_calls: list[dict[str, Any]] = []
        self.image_calls: list[dict[str, Any]] = []
        self.upload_calls: list[dict[str, Any]] = []
        self.family_renderers: dict[str | None, Any] = {}
        self.render_error: Exception | None = None
        self.upload_error: Exception | None = None


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    h = Harness()

    def fake_render_edition(payload: BriefingPayload, **kwargs: Any) -> str:
        h.render_calls.append({"renderer": "classic", "payload": payload, **kwargs})
        return "<edition>classic</edition>"

    def fake_renderer_for(family: str | None) -> Any:
        return h.family_renderers.get(family)

    async def fake_render_html_to_image(html: str, options: Any) -> bytes:
        h.image_calls.append({"html": html, "options": options})
        if h.render_error is not None:
            raise h.render_error
        return h.image

    def fake_upload(public_id: str, file_data: bytes | None = None, **kwargs: Any) -> str:
        h.upload_calls.append({"public_id": public_id, "file_data": file_data})
        if h.upload_error is not None:
            raise h.upload_error
        return h.image_url

    monkeypatch.setattr(edition_email, "render_edition", fake_render_edition)
    monkeypatch.setattr(edition_email, "renderer_for", fake_renderer_for)
    monkeypatch.setattr(edition_email, "render_html_to_image", fake_render_html_to_image)
    monkeypatch.setattr(edition_email, "upload_file_to_cloudinary", fake_upload)
    monkeypatch.setattr(settings, "FRONTEND_URL", FRONTEND_URL)
    monkeypatch.setattr(cloudinary.config(), "cloud_name", CLOUD_NAME)
    return h


def render(payload: BriefingPayload, **overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "image_url": IMAGE_URL,
        "briefing_id": BRIEFING_ID,
        "unsubscribe_url": UNSUBSCRIBE_URL,
    }
    kwargs.update(overrides)
    return render_edition_email(payload, **kwargs)


RENDER_KEY = uuid4().hex


async def host(payload: BriefingPayload) -> HostedEditionImage:
    return await host_edition_image(payload, render_key=RENDER_KEY)


@pytest.mark.unit
class TestEditionRendering:
    async def test_classic_renderer_receives_the_edition_number_and_no_generation_time(
        self, harness: Harness
    ) -> None:
        await host(make_payload(date="2026-01-10"))

        assert harness.render_calls == [
            {
                "renderer": "classic",
                "payload": make_payload(date="2026-01-10"),
                "edition_no": 10,
                "generated_local": "",
            }
        ]

    async def test_family_renderer_is_used_when_the_rotation_assigns_one(
        self, harness: Harness
    ) -> None:
        seen: list[dict[str, Any]] = []

        def family(payload: BriefingPayload, **kwargs: Any) -> str:
            seen.append({"payload": payload, **kwargs})
            return "<edition>family</edition>"

        harness.family_renderers["dispatch"] = family

        await host(make_payload(template_family="dispatch"))

        assert harness.render_calls == []
        assert len(seen) == 1
        assert seen[0]["edition_no"] == 10
        assert harness.image_calls[0]["html"] == "<edition>family</edition>"

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

        assert harness.upload_calls == []


@pytest.mark.unit
class TestImageAndUpload:
    async def test_the_classic_edition_is_its_1180px_page_at_retina_scale(
        self, harness: Harness
    ) -> None:
        await host(make_payload())

        options = harness.image_calls[0]["options"]
        assert (options.width, options.device_scale_factor) == (1180, 2)
        assert (options.clip_selector, options.trim_margin_px) == (".brief", None)
        assert options.image_format == "png"

    async def test_a_paper_on_a_desk_is_trimmed_to_an_even_margin(self, harness: Harness) -> None:
        await host(make_payload(template_family="memo"))

        options = harness.image_calls[0]["options"]
        assert (options.width, options.device_scale_factor) == (540, 3)
        assert (options.clip_selector, options.trim_margin_px) == ("#root > article", 16)

    async def test_a_full_bleed_family_is_its_whole_page(self, harness: Harness) -> None:
        await host(make_payload(template_family="swiss"))

        options = harness.image_calls[0]["options"]
        assert (options.width, options.device_scale_factor) == (540, 3)
        assert (options.clip_selector, options.trim_margin_px) == ("#root > article", None)

    async def test_the_hosted_path_is_the_opaque_render_key_alone(self, harness: Harness) -> None:
        """The URL goes out in emails and on public brief links: no user id, kind or date."""
        await host(make_payload(date="2026-02-03"))

        assert harness.upload_calls == [
            {"public_id": f"briefing/editions/{RENDER_KEY}", "file_data": b"edition-png-bytes"},
        ]

    async def test_hosting_returns_capped_delivery_urls_for_the_uploaded_original(
        self, harness: Harness
    ) -> None:
        base = f"https://res.cloudinary.com/{CLOUD_NAME}/image/upload"

        assert await host(make_payload()) == HostedEditionImage(
            display_url=f"{base}/c_limit,f_auto,q_auto,w_1080/v1/briefing/editions/{RENDER_KEY}",
            chat_url=f"{base}/c_limit,f_jpg,q_auto,w_1080/v1/briefing/editions/{RENDER_KEY}",
        )

    async def test_render_failure_propagates_and_nothing_is_uploaded(
        self, harness: Harness
    ) -> None:
        harness.render_error = RuntimeError("chromium died")

        with pytest.raises(RuntimeError, match="chromium died"):
            await host(make_payload())

        assert harness.upload_calls == []

    async def test_upload_failure_propagates(self, harness: Harness) -> None:
        harness.upload_error = RuntimeError("cloudinary 500")

        with pytest.raises(RuntimeError, match="cloudinary 500"):
            await host(make_payload())


@pytest.mark.unit
class TestDeliveryUrl:
    """The 2-6 MB original must never be what a surface downloads."""

    @pytest.mark.parametrize(
        ("fetch_format", "transformation"),
        [
            (EditionDeliveryFormat.AUTO, "c_limit,f_auto,q_auto,w_1080"),
            (EditionDeliveryFormat.JPG, "c_limit,f_jpg,q_auto,w_1080"),
        ],
    )
    def test_the_url_caps_width_and_compresses_without_upscaling(
        self, harness: Harness, fetch_format: EditionDeliveryFormat, transformation: str
    ) -> None:
        url = edition_delivery_url("briefing/editions/k1", fetch_format)

        assert url == (
            f"https://res.cloudinary.com/{CLOUD_NAME}/image/upload/"
            f"{transformation}/v1/briefing/editions/k1"
        )


@pytest.mark.unit
class TestEmailBody:
    def test_email_body_markup_is_exactly_this(self, harness: Harness) -> None:
        assert render(make_payload()) == EXPECTED_EMAIL_WITHOUT_ACTIONS

    def test_the_email_wraps_the_stored_image_without_rendering_a_second_copy(
        self, harness: Harness
    ) -> None:
        html = render(make_payload(), image_url="https://cdn.example.com/stored.png")

        assert 'src="https://cdn.example.com/stored.png"' in html
        assert harness.render_calls == []
        assert harness.image_calls == []
        assert harness.upload_calls == []

    def test_the_image_links_to_the_briefs_own_page(self, harness: Harness) -> None:
        html = render(make_payload(), briefing_id="b-9")

        assert (
            '<a href="https://app.example.com/brief/b-9" style="text-decoration:none;"><img' in html
        )

    def test_image_url_is_html_escaped(self, harness: Harness) -> None:
        html = render(make_payload(), image_url="https://cdn.example.com/a.png?x=1&y=2")

        assert 'src="https://cdn.example.com/a.png?x=1&amp;y=2"' in html

    def test_preheader_is_hidden_ahead_of_the_image_and_escaped(self, harness: Harness) -> None:
        html = render(make_payload(), preheader="Pick <a> slot")

        assert (
            '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
            "Pick &lt;a&gt; slot</div><table"
        ) in html


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
class TestActionStrip:
    def test_strip_markup_without_actions_is_exactly_this(self, harness: Harness) -> None:
        assert edition_email._action_strip(make_payload(), BRIEF_URL, UNSUBSCRIBE_URL) == (
            EXPECTED_STRIP_WITHOUT_ACTIONS
        )

    def test_strip_markup_with_actions_is_exactly_this(self, harness: Harness) -> None:
        payload = make_payload(
            sections=[
                make_section(make_item("you", "  Pay <Acme> & co  ", "todos/1")),
                make_section(make_item("note", "FYI"), make_item("you", "", "/todos/2")),
            ]
        )

        assert edition_email._action_strip(payload, BRIEF_URL, UNSUBSCRIBE_URL) == (
            EXPECTED_STRIP_WITH_ACTIONS
        )

    def test_no_action_items_means_no_waiting_block(self, harness: Harness) -> None:
        html = render(make_payload(sections=[make_section(make_item("note", "FYI only"))]))

        assert "Waiting on your call" not in html
        assert "FYI only" not in html

    def test_items_waiting_on_the_user_get_review_links(self, harness: Harness) -> None:
        html = render(
            make_payload(
                sections=[
                    make_section(
                        make_item("you", "Send the invoice", "todos/1"),
                        make_item("note", "Nothing to do"),
                        make_item("you", "Answer Sam", "/todos/2"),
                    )
                ]
            )
        )

        assert "Waiting on your call" in html
        assert "Send the invoice" in html
        assert "Answer Sam" in html
        assert "Nothing to do" not in html
        assert f'href="{FRONTEND_URL}/todos/1"' in html
        assert f'href="{FRONTEND_URL}/todos/2"' in html
        assert html.count("Review</a>") == 2

    def test_items_are_collected_across_every_section(self, harness: Harness) -> None:
        html = render(
            make_payload(
                sections=[
                    make_section(make_item("you", "First", "a")),
                    make_section(make_item("you", "Second", "b")),
                ]
            )
        )

        assert "First" in html
        assert "Second" in html
        assert html.count("Review</a>") == 2

    def test_item_without_a_link_falls_back_to_the_app_home(self, harness: Harness) -> None:
        html = render(make_payload(sections=[make_section(make_item("you", "Approve it", None))]))

        assert f'href="{FRONTEND_URL}" style="color:#00bbff' in html

    def test_item_text_is_escaped_and_trimmed(self, harness: Harness) -> None:
        html = render(
            make_payload(
                sections=[make_section(make_item("you", "  Pay <Acme> & co  ", "todos/9"))]
            )
        )

        assert "Pay &lt;Acme&gt; &amp; co &nbsp;" in html

    def test_item_with_empty_text_renders_an_empty_label(self, harness: Harness) -> None:
        html = render(make_payload(sections=[make_section(make_item("you", "", "todos/9"))]))

        assert "Waiting on your call" in html
        assert html.count("Review</a>") == 1

    def test_sections_without_items_are_tolerated(self, harness: Harness) -> None:
        html = render(make_payload(sections=[make_section()]))

        assert "Waiting on your call" not in html

    def test_unsubscribe_url_is_escaped(self, harness: Harness) -> None:
        html = render(make_payload(), unsubscribe_url="https://heygaia.io/u?t=a&s=b")

        assert 'href="https://heygaia.io/u?t=a&amp;s=b"' in html


@pytest.mark.unit
class TestActionItems:
    def test_a_payload_with_no_sections_yields_no_actions(self) -> None:
        assert edition_email._action_items(make_payload()) == []

    def test_only_items_waiting_on_the_user_are_actions(self) -> None:
        payload = make_payload(
            sections=[
                make_section(make_item("you", "Send it", "todos/1"), make_item("gaia", "Drafting")),
                make_section(
                    make_item("lookback", "Shipped"),
                    make_item("failed", "Sync broke"),
                    make_item("note", "Nice"),
                    make_item("you", "Answer Sam", "todos/2"),
                ),
            ]
        )

        assert [item.text for item in edition_email._action_items(payload)] == [
            "Send it",
            "Answer Sam",
        ]


@pytest.mark.unit
class TestResolveLink:
    @pytest.mark.parametrize(
        ("link", "expected"),
        [
            (None, None),
            ("", None),
            ("https://notion.so/page", "https://notion.so/page"),
            # Absolute is a scheme check, not a "starts with https" one — a
            # plain-http deep link must not be pasted onto the app origin.
            ("http://notion.so/page", "http://notion.so/page"),
            ("todos/1", f"{FRONTEND_URL}/todos/1"),
            ("/todos/1", f"{FRONTEND_URL}/todos/1"),
            ("//todos/1", f"{FRONTEND_URL}/todos/1"),
            # lstrip takes a character SET: only slashes may be removed, never
            # the first letters of the path itself.
            ("Xero/invoices", f"{FRONTEND_URL}/Xero/invoices"),
        ],
    )
    def test_links_resolve_against_the_app_origin(
        self, harness: Harness, link: str | None, expected: str | None
    ) -> None:
        assert edition_email._resolve_link(link) == expected


@pytest.mark.unit
class TestBriefLink:
    def test_the_email_links_the_same_brief_url_as_the_skim(self, harness: Harness) -> None:
        """One builder for the brief's URL: the configured public app URL, never a fallback."""
        html = render(make_payload())

        assert f'href="{full_brief_url(BRIEFING_ID)}"' in html
        assert full_brief_url(BRIEFING_ID) == BRIEF_URL


@pytest.mark.unit
class TestEditionNumber:
    def test_editions_count_days_from_the_epoch(self) -> None:
        assert edition_email._edition_no("2026-01-01") == 1
        assert edition_email._edition_no("2026-10-14") == 287


@pytest.mark.unit
class TestIsEditionKind:
    @pytest.mark.parametrize(
        "kind", [NOTIFICATION_KIND_BRIEFING_DAILY, NOTIFICATION_KIND_BRIEFING_WEEKLY]
    )
    def test_briefing_kinds_render_as_editions(self, kind: str) -> None:
        assert is_edition_kind(kind) is True

    @pytest.mark.parametrize("kind", [None, "", "reminder", "briefing", "briefing_monthly"])
    def test_everything_else_does_not(self, kind: str | None) -> None:
        assert is_edition_kind(kind) is False
