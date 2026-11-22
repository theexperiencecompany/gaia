"""Journey: GAIA works on the user's tasks as files under /workspace/tasks/.

GAIA's notes on its own task are a file it rewrites during a run, and the task's notes
tab shows what it wrote. The index lists GAIA's tasks and the user's to-dos; a to-do's
file is GAIA's to read, never to write, and notes that repeat a section are refused.
"""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import RewritesNotes

pytestmark = pytest.mark.e2e

TITLE = "Book the visa appointment"
TO_DO = "Buy milk"
CURRENT_STATE = "Slots are open on 3 and 5 December; the user has not picked one."
NOTES = f"""# {TITLE}

## Standing rules

## Done when
- An appointment is booked and the confirmation is in the user's inbox.

## Evidence
- The consulate's confirmation email.

## Key Details
- Portal: https://visa.example.org/appointments

## Current State
{CURRENT_STATE}

## Context

## Learnings
"""
REPORT = "Two slots opened; I noted them on the task."


class TestGaiasNotesAreAFile:
    async def test_a_run_rewrites_the_notes_with_a_file_write_and_the_task_shows_them(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.hand_to_gaia(TITLE)

        await tasks.run_due(task.id, RewritesNotes(NOTES, REPORT))

        assert CURRENT_STATE in await tasks.notes_of(task.id)
        assert CURRENT_STATE in await tasks.gaia_reads_file(f"/workspace/tasks/{task.id}/notes.md")

    async def test_notes_that_repeat_a_section_are_refused(self, tasks: TasksDriver) -> None:
        task = await tasks.hand_to_gaia(TITLE)
        before = await tasks.notes_of(task.id)

        said = await tasks.gaia_writes_file(
            f"/workspace/tasks/{task.id}/notes.md",
            f"{NOTES}\n## Current State\nBooked nothing yet.\n",
        )

        assert said.startswith("Error")
        assert await tasks.notes_of(task.id) == before


class TestTheTasksFolder:
    async def test_the_index_lists_gaias_tasks_and_the_users_to_dos(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.create_todo(TO_DO)
        await tasks.hand_to_gaia(TITLE)

        index = await tasks.gaia_reads_file("/workspace/tasks/index.md")

        assert TITLE in index and TO_DO in index

    async def test_a_users_to_do_is_read_and_never_written(self, tasks: TasksDriver) -> None:
        todo = await tasks.create_todo(TO_DO)
        meta = f"/workspace/tasks/{todo.id}/meta.json"

        said = await tasks.gaia_writes_file(meta, '{"title": "Buy oat milk"}')
        notes_said = await tasks.gaia_writes_file(f"/workspace/tasks/{todo.id}/notes.md", NOTES)

        assert "own to-do" in said and "own to-do" in notes_said
        assert TO_DO in await tasks.gaia_reads_file(meta)
        after = await tasks.get(todo.id)
        assert after is not None and after.title == TO_DO
