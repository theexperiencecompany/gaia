"""What each tracked item's deliverable tells the voice: a header-free summary, its size, whether it waits."""

import pytest

from app.models.todo_models import TodoDocument
from app.services.briefing.artifacts import ArtifactFact, gather_artifacts
from app.services.briefing.context import TrackedWork

pytestmark = pytest.mark.unit

_USER = "64f1c0ffee0000000000abcd"


def _todo(todo_id: str, canvas: str | None = None) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=_USER, title=todo_id, canvas_content=canvas)


class TestGatherArtifacts:
    def test_a_summary_keeps_the_prose_and_drops_headings_comments_tables_and_rules(self) -> None:
        canvas = (
            "# Title\n<!-- note -->\n| a | b |\n---\nTen slides.\n\n  Covers the Q3 numbers.  \n"
        )

        facts = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)]))

        assert facts["t1"].snippet == "Ten slides. Covers the Q3 numbers."

    def test_an_indented_heading_is_dropped_from_the_summary_too(self) -> None:
        canvas = "   # Indented heading\nThe point.\n"

        facts = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)]))

        assert facts["t1"].snippet == "The point."

    def test_an_item_seen_twice_does_not_hide_the_ones_after_it(self) -> None:
        work = TrackedWork(completed=[_todo("t1"), _todo("t1")], running=[_todo("t2")])

        assert list(gather_artifacts(work)) == ["t1", "t2"]

    def test_a_summary_is_cut_at_the_preview_length_without_trailing_space(self) -> None:
        canvas = ("word " * 100).strip()

        [fact] = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)])).values()

        assert fact.snippet == ("word " * 48).rstrip()
        assert len(fact.snippet) == 239

    def test_an_item_without_a_canvas_has_an_empty_summary_and_no_size(self) -> None:
        facts = gather_artifacts(TrackedWork(running=[_todo("t1")]))

        assert facts == {"t1": ArtifactFact(snippet="", chars=0, action=False)}

    def test_only_what_waits_on_the_user_is_marked_as_an_action(self) -> None:
        work = TrackedWork(
            completed=[_todo("done")],
            running=[_todo("running")],
            blocked=[_todo("blocked")],
            failed=[_todo("failed")],
        )

        facts = gather_artifacts(work)

        assert {todo_id: fact.action for todo_id, fact in facts.items()} == {
            "done": False,
            "running": False,
            "blocked": True,
            "failed": False,
        }

    def test_an_item_in_two_states_is_counted_once_as_its_first(self) -> None:
        first = _todo("t1", "First text.")
        again = _todo("t1", "Second text.")

        facts = gather_artifacts(TrackedWork(completed=[first], blocked=[again]))

        assert facts == {"t1": ArtifactFact(snippet="First text.", chars=11, action=True)}

    def test_the_size_counts_the_deliverable_text_without_its_headings(self) -> None:
        facts = gather_artifacts(TrackedWork(completed=[_todo("t1", "# Heading\nfive.\nmore.")]))

        assert facts["t1"].chars == len("five. more.")
