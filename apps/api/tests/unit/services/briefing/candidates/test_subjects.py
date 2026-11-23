"""When several tracked todos are one thing to the user, so the brief says it once."""

from tests.factories import make_todo

from app.models.todo_models import ExternalRef, ExternalRefSource
from app.services.briefing.candidates.subjects import subject_key


class TestSubjectKey:
    def test_todos_titled_alike_but_for_case_and_spacing_are_one_subject(self) -> None:
        """Regression: three approval requests for one Acme MSA renewal became one line with three links."""
        keys = {
            subject_key(make_todo(title))
            for title in ("Approve the Acme MSA renewal", "approve the  Acme MSA renewal ")
        }

        assert len(keys) == 1
        assert subject_key(make_todo("Reply to Daniel")) not in keys

    def test_subtasks_of_one_parent_are_one_subject_whatever_their_titles(self) -> None:
        approve = make_todo("Approve the Acme MSA", parent_todo_id="acme")
        sign = make_todo("Sign the Acme order form", parent_todo_id="acme")

        assert subject_key(approve) == subject_key(sign)
        assert subject_key(make_todo("Approve the Acme MSA")) != subject_key(approve)

    def test_threads_the_inbox_desk_opened_are_one_subject_each_though_they_share_the_desk(
        self,
    ) -> None:
        threads = [
            make_todo(
                title,
                parent_todo_id="desk",
                external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id=f"th{n}"),
            )
            for n, title in enumerate(["Priya · pitch deck", "Priya · pitch deck"])
        ]

        assert subject_key(threads[0]) != subject_key(threads[1])
