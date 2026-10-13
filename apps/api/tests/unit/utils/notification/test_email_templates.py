"""Unit tests for the briefing and notification email renderings.

The templates are rendered for real through Jinja; assertions read the HTML the
user's mail client would receive (links, escaping, which variant) rather than
re-deriving the markup from the module's own constants.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError
import pytest

from app.config.settings import settings
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.utils.notification.email_templates import (
    render_briefing_email,
    render_notification_email,
)

_APP = "https://app.example.test"
_UNSUB = "https://api.example.test/unsub?token=t0k&x=1"


@pytest.fixture(autouse=True)
def _urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FRONTEND_URL", _APP)
    monkeypatch.setattr(settings, "HOST", "https://api.example.test")


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kicker": "THE MORNING BRIEF",
        "date": "2026-10-13",
        "headline": "Two replies need you",
        "lede": "I drafted both.",
        "stats": [{"value": "4", "label": "done since yesterday"}],
        "sections": [
            {
                "numeral": "I",
                "title": "NEEDS YOU",
                "items": [
                    {"text": "Approve the Priya reply", "todo_id": "todo-1", "kind": "you"},
                    {"text": "Read the memo", "kind": "note", "link": "https://heygaia.link/m"},
                    {"text": "Inbox triage", "kind": "gaia"},
                ],
            },
            {"numeral": "II", "title": "EMPTY", "items": []},
        ],
        "mood": "packed",
        "caption": "Coffee first.",
        "hue": 0,
    }
    payload.update(overrides)
    return payload


def _item_hrefs(html: str) -> list[str]:
    return re.findall(r'class="item-link" href="([^"]+)"', html)


class TestRenderBriefingEmail:
    def test_every_item_is_a_link_to_where_it_lives(self) -> None:
        _, html = render_briefing_email(_payload(), NOTIFICATION_KIND_BRIEFING_DAILY, _UNSUB)

        assert _item_hrefs(html) == [
            f"{_APP}/todos?todoId=todo-1",
            "https://heygaia.link/m",
            f"{_APP}/briefings",
        ]

    def test_subject_is_the_headline_and_body_carries_the_brief(self) -> None:
        subject, html = render_briefing_email(_payload(), NOTIFICATION_KIND_BRIEFING_DAILY, _UNSUB)

        assert subject == "Two replies need you"
        assert "Tuesday, October 13" in html
        assert "Waiting on you" in html
        assert "Open today&#39;s brief" in html
        assert "GAIA sends this brief every morning." in html

    def test_a_section_with_no_items_is_left_out(self) -> None:
        _, html = render_briefing_email(_payload(), NOTIFICATION_KIND_BRIEFING_DAILY, _UNSUB)

        assert "NEEDS YOU" in html
        assert "EMPTY" not in html

    def test_payload_text_is_escaped(self) -> None:
        _, html = render_briefing_email(
            _payload(headline="<script>x</script> & co"), NOTIFICATION_KIND_BRIEFING_DAILY, _UNSUB
        )

        assert "<script>x</script>" not in html
        assert "&lt;script&gt;x&lt;/script&gt; &amp; co" in html

    def test_unsubscribe_link_is_escaped_into_the_footer(self) -> None:
        _, html = render_briefing_email(_payload(), NOTIFICATION_KIND_BRIEFING_DAILY, _UNSUB)

        assert 'href="https://api.example.test/unsub?token=t0k&amp;x=1"' in html

    def test_dark_mode_is_declared_for_clients_that_honour_it(self) -> None:
        _, html = render_briefing_email(_payload(), NOTIFICATION_KIND_BRIEFING_DAILY, _UNSUB)

        assert '<meta name="color-scheme" content="light dark" />' in html
        assert "@media (prefers-color-scheme: dark)" in html

    def test_weekly_recap_leads_with_a_hero_stat(self) -> None:
        payload = _payload(
            kicker="THE WEEK IN REVIEW",
            stats=[
                {"value": "3 hrs", "label": "saved this week"},
                {"value": "9", "label": "finished by GAIA"},
            ],
            mood="weekly",
        )
        _, html = render_briefing_email(payload, NOTIFICATION_KIND_BRIEFING_WEEKLY, _UNSUB)

        assert 'class="stat-panel"' in html
        assert "See your week in GAIA" in html
        assert "every Sunday evening" in html

    def test_a_malformed_payload_fails_instead_of_mailing_a_blank(self) -> None:
        with pytest.raises(ValidationError):
            render_briefing_email({"headline": "only"}, NOTIFICATION_KIND_BRIEFING_DAILY, _UNSUB)


class TestRenderNotificationEmail:
    def test_title_body_and_unsubscribe(self) -> None:
        html = render_notification_email("Reminder <b>", "Stand-up in 10", _UNSUB)

        assert "Reminder &lt;b&gt;" in html
        assert "Stand-up in 10" in html
        assert f'href="{_APP}"' in html
        assert 'href="https://api.example.test/unsub?token=t0k&amp;x=1"' in html
