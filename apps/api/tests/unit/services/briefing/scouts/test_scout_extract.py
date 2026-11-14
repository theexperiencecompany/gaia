"""Reading a replayed result into signals by the learned paths, and refusing a moved shape."""

from datetime import UTC, datetime

import pytest

from app.constants.scouts import SCOUT_SIGNAL_CEILING
from app.models.scout_models import SignalFields, SignalImportance, SignalSource
from app.services.briefing.scouts.extract import extract_signals
from app.services.briefing.scouts.tools import ScoutIntegration
from app.services.workflow.playbook.evaluator import PlaceholderError

GITHUB = ScoutIntegration(integration_id="github", name="GitHub")
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
        created_at="created",
        updated_at="updated",
    ),
)


def _pr(number: int, **extra: object) -> dict[str, object]:
    return {"number": number, "title": f"PR {number}", "html_url": f"https://gh/{number}", **extra}


class TestReadingItems:
    def test_each_item_becomes_a_signal_with_its_learned_fields(self) -> None:
        values = {"reviews": {"items": [_pr(7, state="open", author="ana", due="2026-10-30")]}}

        [signal] = extract_signals(GITHUB, [SOURCE], values)

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
            "amount": None,
            "amount_unit": None,
            "text": None,
            "created_at": None,
            "updated_at": None,
        }
        assert signal.due_at == datetime(2026, 10, 30, tzinfo=UTC)

    @pytest.mark.parametrize(("raw", "read"), [(1250, 1250.0), (99.5, 99.5), ("42.10", 42.1)])
    def test_an_items_figure_reads_as_a_number_in_its_sources_unit(
        self, raw: object, read: float
    ) -> None:
        source = SOURCE.model_copy(
            update={
                "fields": SOURCE.fields.model_copy(update={"amount": "total", "text": "body"}),
                "amount_unit": "USD",
            }
        )
        values = {"reviews": {"items": [_pr(1, total=raw, body="Can you look today?")]}}

        [signal] = extract_signals(GITHUB, [source], values)

        assert (signal.amount, signal.amount_unit, signal.text) == (
            read,
            "USD",
            "Can you look today?",
        )

    def test_an_item_without_a_figure_carries_no_unit(self) -> None:
        source = SOURCE.model_copy(
            update={
                "fields": SOURCE.fields.model_copy(update={"amount": "total"}),
                "amount_unit": "USD",
            }
        )

        [signal] = extract_signals(GITHUB, [source], {"reviews": {"items": [_pr(1)]}})

        assert (signal.amount, signal.amount_unit) == (None, None)

    @pytest.mark.parametrize(
        ("raw", "kind"), [(True, "bool"), ("a lot", "str"), ({"value": 3}, "dict")]
    )
    def test_a_figure_that_is_not_a_number_is_a_moved_shape(self, raw: object, kind: str) -> None:
        source = SOURCE.model_copy(
            update={"fields": SOURCE.fields.model_copy(update={"amount": "total"})}
        )

        with pytest.raises(PlaceholderError) as raised:
            extract_signals(GITHUB, [source], {"reviews": {"items": [_pr(1, total=raw)]}})

        assert raised.value.message == f"amount is a {kind}, not the value the scout learned"

    def test_text_that_is_not_text_is_a_moved_shape(self) -> None:
        source = SOURCE.model_copy(
            update={"fields": SOURCE.fields.model_copy(update={"text": "body"})}
        )

        with pytest.raises(PlaceholderError) as raised:
            extract_signals(GITHUB, [source], {"reviews": {"items": [_pr(1, body={"x": 1})]}})

        assert raised.value.message == "text is a dict, not the value the scout learned"

    def test_an_empty_figure_and_empty_text_read_as_absent(self) -> None:
        source = SOURCE.model_copy(
            update={
                "fields": SOURCE.fields.model_copy(update={"amount": "total", "text": "body"}),
                "amount_unit": "USD",
            }
        )

        [signal] = extract_signals(
            GITHUB, [source], {"reviews": {"items": [_pr(1, total="", body="")]}}
        )

        assert (signal.amount, signal.amount_unit, signal.text) == (None, None, None)

    def test_the_items_own_creation_and_update_times_are_carried(self) -> None:
        dated = SOURCE.model_copy(
            update={
                "fields": SOURCE.fields.model_copy(
                    update={"created_at": "created_at", "updated_at": "updated_at"}
                )
            }
        )
        values = {
            "reviews": {
                "items": [
                    _pr(110, created_at="2025-06-18T09:00:00Z", updated_at="2025-06-19T10:30:00")
                ]
            }
        }

        [signal] = extract_signals(GITHUB, [dated], values)

        assert (signal.created_at, signal.updated_at) == (
            datetime(2025, 6, 18, 9, 0, tzinfo=UTC),
            datetime(2025, 6, 19, 10, 30, tzinfo=UTC),
        )

    def test_an_undated_source_carries_no_creation_time(self) -> None:
        [signal] = extract_signals(GITHUB, [SOURCE], {"reviews": {"items": [_pr(1)]}})

        assert (signal.created_at, signal.updated_at) == (None, None)

    def test_every_replayed_item_starts_normal_whatever_its_due_date(self) -> None:
        """Replay reset importance to due-date; the judge decides it now."""
        values = {"reviews": {"items": [_pr(1, due="2026-10-20"), _pr(2, due="2026-10-30")]}}

        signals = extract_signals(GITHUB, [SOURCE], values)

        assert [s.importance for s in signals] == [SignalImportance.NORMAL] * 2

    def test_a_flag_state_reads_as_its_field_and_value(self) -> None:
        """Todoist's checked: false was refused as "state is a bool" and the scout never froze."""
        source = SOURCE.model_copy(
            update={"fields": SOURCE.fields.model_copy(update={"state": "flags.checked"})}
        )
        values = {"reviews": {"items": [_pr(1, flags={"checked": False})]}}

        [signal] = extract_signals(GITHUB, [source], values)

        assert signal.state == "checked: false"

    def test_a_true_flag_reads_as_its_innermost_field_and_true(self) -> None:
        source = SOURCE.model_copy(
            update={"fields": SOURCE.fields.model_copy(update={"state": "a.flags.checked"})}
        )
        values = {"reviews": {"items": [_pr(1, a={"flags": {"checked": True}})]}}

        [signal] = extract_signals(GITHUB, [source], values)

        assert signal.state == "checked: true"

    def test_a_person_object_skips_an_empty_or_non_text_name_for_the_next_key(self) -> None:
        values = {
            "reviews": {
                "items": [
                    _pr(1, author={"name": "", "displayName": "Bo"}),
                    _pr(2, author={"name": 5, "displayName": "Cy"}),
                ]
            }
        }

        first, second = extract_signals(GITHUB, [SOURCE], values)

        assert (first.people, second.people) == (["Bo"], ["Cy"])

    def test_people_given_as_person_objects_read_as_their_names(self) -> None:
        """Google Docs owners [{displayName}] were refused as "people is a list"."""
        values = {
            "reviews": {
                "items": [
                    _pr(1, author=[{"displayName": "Sankalp"}, {"login": "ana", "id": 4}]),
                    _pr(2, author={"name": "Bo", "displayName": "Bo D."}),
                ]
            }
        }

        first, second = extract_signals(GITHUB, [SOURCE], values)

        assert (first.people, second.people) == (["Sankalp", "ana"], ["Bo"])

    def test_optional_fields_left_empty_read_as_absent(self) -> None:
        values = {"reviews": {"items": [_pr(7, due="", author=["ana", "bo"])]}}

        [signal] = extract_signals(GITHUB, [SOURCE], values)

        assert (signal.due_at, signal.people, signal.state) == (None, ["ana", "bo"], None)

    def test_an_empty_list_is_a_quiet_day(self) -> None:
        assert extract_signals(GITHUB, [SOURCE], {"reviews": {"items": []}}) == []

    def test_a_runaway_list_stops_at_the_safety_ceiling(self) -> None:
        values = {"reviews": {"items": [_pr(n) for n in range(SCOUT_SIGNAL_CEILING + 5)]}}

        assert len(extract_signals(GITHUB, [SOURCE], values)) == SCOUT_SIGNAL_CEILING


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
                {"reviews": {"items": [_pr(1, author={"id": 4})]}},
                "a person in people is a dict, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, author=["ana", 3])]}},
                "a person in people is a int, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, due="next week-ish")]}},
                "due_at is a str, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, created="a while back")]}},
                "created_at is a str, not the value the scout learned",
            ),
            (
                {"reviews": {"items": [_pr(1, updated="lately")]}},
                "updated_at is a str, not the value the scout learned",
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
            "person with no name",
            "people not all names",
            "due not a date",
            "created not a date",
            "updated not a date",
            "url not text",
            "state not text",
        ],
    )
    def test_a_result_the_paths_no_longer_fit_raises(
        self, values: dict[str, object], message: str
    ) -> None:
        with pytest.raises(PlaceholderError) as raised:
            extract_signals(GITHUB, [SOURCE], values)

        assert raised.value.message == message

    def test_a_moved_shape_says_why_and_how_to_recover(self) -> None:
        with pytest.raises(PlaceholderError) as raised:
            extract_signals(GITHUB, [SOURCE], {"reviews": {"items": "x"}})

        assert (raised.value.why, raised.value.fix) == (
            "the app's result no longer has the shape the scout froze",
            "relearn the scout against the app's current results",
        )
