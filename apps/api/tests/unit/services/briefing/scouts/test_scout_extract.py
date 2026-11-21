"""Reading a replayed result into signals by the learned paths, and refusing a moved shape."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from tests.helpers import captured_wide_event

from app.constants.scouts import SCOUT_SIGNAL_CEILING
from app.models.scout_models import PeopleRole, SignalFields, SignalImportance, SignalSource
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
            "people_role": None,
            "people_you": [],
            "url": "https://gh/7",
            "state": "open",
            "amount": None,
            "amount_unit": None,
            "text": None,
            "author": None,
            "created_at": None,
            "updated_at": None,
        }
        assert signal.due_at == datetime(2026, 10, 30, tzinfo=UTC)

    def test_the_user_is_told_apart_from_a_teammate_by_their_own_handle(self) -> None:
        """Aryan's brief said "Aryan is waiting on your review" about Aryan himself."""
        source = SOURCE.model_copy(
            update={"fields": SOURCE.fields.model_copy(update={"people": "assignees"})}
        )
        pr = _pr(7, state="open", author="ana", due="2026-10-30")
        pr["assignees"] = [
            {"name": "Aryan Randeriya", "login": "Aryan-Randeriya"},
            {"name": "Sam Lee", "login": "samlee"},
            "ARYAN@HEYGAIA.IO",
        ]
        mine = replace(GITHUB, handles=frozenset({"aryan-randeriya", "aryan@heygaia.io"}))

        [signal] = extract_signals(mine, [source], {"reviews": {"items": [pr]}})

        assert signal.people == ["Aryan Randeriya", "Sam Lee", "ARYAN@HEYGAIA.IO"]
        assert signal.people_you == ["Aryan Randeriya", "ARYAN@HEYGAIA.IO"]

    @pytest.mark.regression
    def test_a_teammate_named_after_the_users_handle_is_not_the_user(self) -> None:
        """A display name is free text anyone can set; only an account's own id field is the user."""
        source = SOURCE.model_copy(
            update={"fields": SOURCE.fields.model_copy(update={"people": "assignees"})}
        )
        pr = _pr(7, state="open")
        pr["assignees"] = [
            {"name": "aryan-randeriya", "login": "mallory"},
            {"display_name": "ARYAN@HEYGAIA.IO", "id": "u-9"},
        ]
        mine = replace(GITHUB, handles=frozenset({"aryan-randeriya", "aryan@heygaia.io"}))

        [signal] = extract_signals(mine, [source], {"reviews": {"items": [pr]}})

        assert signal.people_you == []

    def test_an_app_with_no_known_handle_marks_nobody_as_the_user(self) -> None:
        source = SOURCE.model_copy(
            update={"fields": SOURCE.fields.model_copy(update={"people": "assignees"})}
        )
        pr = _pr(7, state="open", author="ana", due="2026-10-30")
        pr["assignees"] = [{"name": "Aryan Randeriya", "login": "Aryan-Randeriya"}, 7]

        [signal] = extract_signals(GITHUB, [source], {"reviews": {"items": [pr]}})

        assert (signal.people, signal.people_you) == (["Aryan Randeriya"], [])

    def test_the_peoples_part_and_the_texts_author_are_read_as_the_scout_learned_them(
        self,
    ) -> None:
        """Audit: people carried no role, and a quote's author was whoever came first."""
        source = SOURCE.model_copy(
            update={
                "fields": SOURCE.fields.model_copy(
                    update={
                        "people": "reviewers",
                        "people_role": PeopleRole.REVIEWER,
                        "text": "last_comment.body",
                        "author": "last_comment.user",
                    }
                )
            }
        )
        item = _pr(
            7,
            reviewers=[{"login": "sam"}],
            last_comment={"body": "Can you rebase?", "user": {"login": "ana"}},
        )

        [signal] = extract_signals(GITHUB, [source], {"reviews": {"items": [item]}})

        assert (signal.people, signal.people_role, signal.text, signal.author) == (
            ["sam"],
            PeopleRole.REVIEWER,
            "Can you rebase?",
            "ana",
        )

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

    @pytest.mark.regression
    def test_an_item_in_an_archived_repository_is_left_out(self) -> None:
        """The founder's brief listed unstarted issues from a repo archived as an old snapshot."""
        values = {
            "reviews": {
                "items": [
                    _pr(110, repository={"full_name": "acme/backend", "archived": True}),
                    _pr(111, archived=True),
                    _pr(7, repository={"full_name": "acme/www", "archived": False}),
                ]
            }
        }

        assert [s.external_id for s in extract_signals(GITHUB, [SOURCE], values)] == ["7"]

    def test_a_result_of_only_archived_items_is_a_quiet_day(self) -> None:
        values = {"reviews": {"items": [_pr(110, repository={"archived": True})]}}

        assert extract_signals(GITHUB, [SOURCE], values) == []

    def test_an_empty_list_is_a_quiet_day(self) -> None:
        assert extract_signals(GITHUB, [SOURCE], {"reviews": {"items": []}}) == []

    def test_a_runaway_list_stops_at_the_safety_ceiling(self) -> None:
        values = {"reviews": {"items": [_pr(n) for n in range(SCOUT_SIGNAL_CEILING + 5)]}}

        assert len(extract_signals(GITHUB, [SOURCE], values)) == SCOUT_SIGNAL_CEILING


class TestOneMalformedItem:
    async def test_an_item_missing_its_required_fields_is_skipped_and_logged(self) -> None:
        """One untitled task raised, the replay relearned, and the relearn failed on it too."""
        values = {"reviews": {"items": [_pr(1), _pr(2, title=""), {"title": "no id"}, _pr(3)]}}

        async with captured_wide_event() as event:
            signals = extract_signals(GITHUB, [SOURCE], values)

        assert [s.external_id for s in signals] == ["1", "3"]
        assert event["warnings"] == [
            {
                "msg": "briefing.scout_items_unread",
                "integration_id": "github",
                "step_id": "reviews",
                "items": 4,
                "skipped": 2,
                "skip_reason": "title is a str, not the value the scout learned",
                "unread_fields": [],
            }
        ]

    @pytest.mark.parametrize(
        ("extra", "field", "empty"),
        [
            ({"author": {"id": 4}}, "people", []),
            ({"author": [{"id": 4}, "ana", ""]}, "people", ["ana"]),
            ({"due": "next week-ish"}, "due_at", None),
            ({"created": "a while back"}, "created_at", None),
            ({"updated": "lately"}, "updated_at", None),
            ({"html_url": {"href": "x"}}, "url", None),
            ({"html_url": "https://api.github.com/repos/o/r/pulls/1813"}, "url", None),
            ({"state": ["open"]}, "state", None),
        ],
        ids=[
            "person with no name",
            "people not all names",
            "due not a date",
            "created not a date",
            "updated not a date",
            "url not text",
            "url an API endpoint, not a page (GitHub notifications, 2026-11-22)",
            "state not text",
        ],
    )
    async def test_an_optional_field_that_cannot_be_read_is_left_empty(
        self, extra: dict[str, object], field: str, empty: object
    ) -> None:
        values = {"reviews": {"items": [_pr(1, **extra)]}}

        async with captured_wide_event() as event:
            [signal] = extract_signals(GITHUB, [SOURCE], values)

        assert (signal.external_id, signal.title, getattr(signal, field)) == ("1", "PR 1", empty)
        [warning] = event["warnings"]
        assert (warning["skipped"], warning["unread_fields"]) == (0, [field])

    @pytest.mark.parametrize(
        ("extra", "field"),
        [
            ({"total": True}, "amount"),
            ({"total": "a lot"}, "amount"),
            ({"total": {"value": 3}}, "amount"),
            ({"body": {"x": 1}}, "text"),
        ],
        ids=["figure a flag", "figure not numeric", "figure an object", "text not text"],
    )
    async def test_a_figure_or_text_that_cannot_be_read_is_left_empty(
        self, extra: dict[str, object], field: str
    ) -> None:
        source = SOURCE.model_copy(
            update={
                "fields": SOURCE.fields.model_copy(update={"amount": "total", "text": "body"}),
                "amount_unit": "USD",
            }
        )

        async with captured_wide_event() as event:
            [signal] = extract_signals(GITHUB, [source], {"reviews": {"items": [_pr(1, **extra)]}})

        assert (signal.external_id, getattr(signal, field), signal.amount_unit) == ("1", None, None)
        [warning] = event["warnings"]
        assert (warning["skipped"], warning["unread_fields"]) == (0, [field])

    async def test_a_cleanly_read_result_logs_nothing(self) -> None:
        async with captured_wide_event() as event:
            extract_signals(GITHUB, [SOURCE], {"reviews": {"items": [_pr(1, author="ana")]}})

        assert "warnings" not in event


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
                {"reviews": {"items": [{"title": "no id"}, {"title": "nor here"}]}},
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
        ],
        ids=[
            "no list",
            "not a list",
            "no item has an id",
            "no title",
            "id not text",
            "title not text",
        ],
    )
    def test_a_result_where_no_item_reads_raises(
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
