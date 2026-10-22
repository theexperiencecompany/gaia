"""Reading a replayed result into signals by the learned paths, and refusing a moved shape."""

from datetime import UTC, datetime

import pytest

from app.constants.scouts import SCOUT_SIGNAL_CEILING
from app.models.scout_models import SignalFields, SignalImportance, SignalSource
from app.services.briefing.scouts.extract import extract_signals
from app.services.briefing.scouts.tools import ScoutIntegration
from app.services.workflow.playbook.evaluator import PlaceholderError

GITHUB = ScoutIntegration(integration_id="github", name="GitHub")
NOW = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)
SOURCE = SignalSource(
    step_id="reviews",
    kind="pull request waiting on your review",
    items_path="items",
    fields=SignalFields(
        external_id="number",
        title="title",
        url="html_url",
        due_at="due",
        state="state",
        people="author",
    ),
)


def _pr(number: int, **extra: object) -> dict[str, object]:
    return {"number": number, "title": f"PR {number}", "html_url": f"https://gh/{number}", **extra}


class TestReadingItems:
    def test_each_item_becomes_a_signal_with_its_learned_fields(self) -> None:
        values = {"reviews": {"items": [_pr(7, state="open", author="ana", due="2026-10-30")]}}

        [signal] = extract_signals(GITHUB, [SOURCE], values, NOW)

        assert signal.model_dump(exclude={"due_at"}) == {
            "integration_id": "github",
            "app": "GitHub",
            "external_id": "7",
            "kind": "pull request waiting on your review",
            "title": "PR 7",
            "why": None,
            "importance": SignalImportance.NORMAL,
            "people": ["ana"],
            "url": "https://gh/7",
            "state": "open",
        }
        assert signal.due_at == datetime(2026, 10, 30, tzinfo=UTC)

    def test_an_item_due_within_a_day_or_overdue_is_important(self) -> None:
        values = {
            "reviews": {
                "items": [
                    _pr(1, due="2026-10-22T20:00:00Z"),
                    _pr(2, due="2026-10-20"),
                    _pr(3, due="2026-10-25"),
                    _pr(4),
                ]
            }
        }

        signals = extract_signals(GITHUB, [SOURCE], values, NOW)

        assert [s.importance for s in signals] == [
            SignalImportance.HIGH,
            SignalImportance.HIGH,
            SignalImportance.NORMAL,
            SignalImportance.NORMAL,
        ]

    def test_optional_fields_left_empty_read_as_absent(self) -> None:
        values = {"reviews": {"items": [_pr(7, due="", author=["ana", "bo"])]}}

        [signal] = extract_signals(GITHUB, [SOURCE], values, NOW)

        assert (signal.due_at, signal.people, signal.state) == (None, ["ana", "bo"], None)

    def test_an_item_due_exactly_a_day_out_is_important(self) -> None:
        values = {"reviews": {"items": [_pr(1, due="2026-10-23T06:00:00Z")]}}

        [signal] = extract_signals(GITHUB, [SOURCE], values, NOW)

        assert signal.importance is SignalImportance.HIGH

    def test_an_empty_list_is_a_quiet_day(self) -> None:
        assert extract_signals(GITHUB, [SOURCE], {"reviews": {"items": []}}, NOW) == []

    def test_a_runaway_list_stops_at_the_safety_ceiling(self) -> None:
        values = {"reviews": {"items": [_pr(n) for n in range(SCOUT_SIGNAL_CEILING + 5)]}}

        assert len(extract_signals(GITHUB, [SOURCE], values, NOW)) == SCOUT_SIGNAL_CEILING


class TestAMovedShape:
    @pytest.mark.parametrize(
        ("values", "message"),
        [
            (
                {"reviews": {"results": []}},
                "$steps.reviews.items is not in step 'reviews''s result",
            ),
            (
                {"reviews": {"items": {"number": 1}}},
                "reviews's items is a dict, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [{"title": "no id"}]}},
                "$steps.reviews is not in the current for_each element",
            ),
            (
                {"reviews": {"items": [{"number": 1}]}},
                "$steps.reviews is not in the current for_each element",
            ),
            (
                {"reviews": {"items": [{**_pr(1), "number": True}]}},
                "external_id is a bool, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, title={"text": "x"})]}},
                "title is a dict, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, author={"login": "ana"})]}},
                "people is a dict, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, author=["ana", 3])]}},
                "people is a list, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, due="next week-ish")]}},
                "due_at is a str, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, html_url={"href": "x"})]}},
                "url is a dict, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, state=["open"])]}},
                "state is a list, not the value the scout learned",
            ),
        ],
        ids=[
            "no list",
            "not a list",
            "no id",
            "no title",
            "id not text",
            "title not text",
            "people not names",
            "people not all names",
            "due not a date",
            "url not text",
            "state not text",
        ],
    )
    def test_a_result_the_paths_no_longer_fit_raises(
        self, values: dict[str, object], message: str
    ) -> None:
        with pytest.raises(PlaceholderError) as raised:
            extract_signals(GITHUB, [SOURCE], values, NOW)

        assert raised.value.message == message

    def test_a_moved_shape_says_why_and_how_to_recover(self) -> None:
        with pytest.raises(PlaceholderError) as raised:
            extract_signals(GITHUB, [SOURCE], {"reviews": {"items": "x"}}, NOW)

        assert (raised.value.why, raised.value.fix) == (
            "the app's result no longer has the shape the scout froze",
            "relearn the scout against the app's current results",
        )
