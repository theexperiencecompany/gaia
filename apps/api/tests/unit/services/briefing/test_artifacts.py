"""What each tracked item's deliverable tells the voice: a header-free summary, its size, whether it waits."""

import pytest

from app.models.todo_models import TodoDocument
from app.services.briefing.artifacts import ArtifactFact, gather_artifacts
from app.services.briefing.work import TrackedWork

pytestmark = pytest.mark.unit

_USER = "64f1c0ffee0000000000abcd"


def _todo(todo_id: str, canvas: str | None = None) -> TodoDocument:
    return TodoDocument(id=todo_id, user_id=_USER, title=todo_id, canvas_content=canvas)


class TestGatherArtifacts:
    def test_open_works_canvas_never_reaches_the_voice(self) -> None:
        """Replay of Dhruv's set: "their notes say not to resume the OAuth test" voiced a canvas."""
        canvas = (
            "## Standing rules\n- Do not resume the OAuth test.\n\n## Current State\n- Paused.\n"
        )
        work = TrackedWork(
            running=[_todo("running", canvas)],
            blocked=[_todo("blocked", canvas)],
            failed=[_todo("failed", canvas)],
        )

        assert {fact.snippet for fact in gather_artifacts(work).values()} == {""}

    def test_finished_works_summary_is_its_deliverable_without_gaias_working_notes(
        self,
    ) -> None:
        canvas = (
            "# Investors\n## Standing rules\n- Never email them.\n\n## Key Details\n- Thread 1a2b.\n"
            "\n## Current State\n- Vetted twelve investors.\n"
        )

        facts = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)]))

        assert facts["t1"].snippet == "- Vetted twelve investors."

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

    def test_a_summary_ends_on_a_whole_sentence_never_mid_figure(self) -> None:
        """Replay of Dhruv's Nov 4 brief: a summary cut at 240 chars ended "Friday, Nov 6, 2026, 1"."""
        sent = (
            "- Dhruv sent the confirmation reply on Nov 4, 2026 local time (Gmail message ID "
            "1a1a2be682c927b4); the earlier draft r3126082176426667195 was sent."
        )
        booked = (
            "- Boardy replied in the same thread that the intro call is booked for Friday, "
            "Nov 6, 2026, 10:00-10:30 AM ET / 8:30-9:00 PM IST."
        )
        canvas = f"## Key Details\n- Thread 1a1a.\n\n## Current State\n{sent}\n{booked}\n"

        [fact] = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)])).values()

        assert fact.snippet == sent

    def test_whole_sentences_are_kept_while_they_fit(self) -> None:
        exactly_full = "Ten slides. " + "Long. " * 37 + "x" * 5 + "."
        canvas = exactly_full + " The next sentence."

        [fact] = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)])).values()

        assert len(exactly_full) == 240
        assert fact.snippet == exactly_full

    def test_a_finished_item_with_no_deliverable_has_an_empty_summary(self) -> None:
        canvas = "## Standing rules\n- Never email them.\n"

        [fact] = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)])).values()

        assert fact.snippet == ""

    def test_a_sub_heading_or_an_unclosed_comment_in_a_deliverable_is_dropped(self) -> None:
        canvas = "## Current State\n  ### Sources\n<!-- draft notes\n- Vetted twelve investors.\n"

        [fact] = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)])).values()

        assert fact.snippet == "- Vetted twelve investors."

    def test_a_first_sentence_past_the_preview_length_is_cut_at_a_word_and_marked(
        self,
    ) -> None:
        canvas = ("word " * 100).strip()

        [fact] = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)])).values()

        assert fact.snippet == ("word " * 48).rstrip() + "\u2026"
        assert len(fact.snippet) == 240

    def test_a_word_that_would_leave_no_room_for_the_mark_is_dropped(self) -> None:
        canvas = "x" * 235 + " yyyy" + " z" * 10

        [fact] = gather_artifacts(TrackedWork(completed=[_todo("t1", canvas)])).values()

        assert fact.snippet == "x" * 235 + "\u2026"

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
