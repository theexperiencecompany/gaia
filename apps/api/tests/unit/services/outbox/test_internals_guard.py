"""Internals guard: GAIA machinery is flagged, the user's own data never is."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.outbox.internals_guard import leaked_internals

pytestmark = pytest.mark.unit

MODULE = "app.services.outbox.internals_guard"
USER = "6812f0b3c9a14e2b7d5a91cc"
TODO_ID = "6812f0b3c9a14e2b7d5a91d0"
RUN_ID = "3f2b8c1e-5a4d-4e7f-9b0a-1c2d3e4f5a6b"
ORDER_NUMBER = "6812f0b3c9a14e2b7d5a91ee"
COMMIT = "9fceb02d0ae598e95dc970b74767f19372d61af8"


async def _leaks(*texts: str, todo: bool = False, run: bool = False) -> list[str]:
    registry = SimpleNamespace(get_tool_names=lambda: ["GMAIL_SEND_EMAIL", "execute"])
    with (
        patch(f"{MODULE}.get_tool_registry", AsyncMock(return_value=registry)),
        patch(
            f"{MODULE}.todo_repository.get",
            AsyncMock(
                side_effect=lambda doc_id, **_: object() if todo and doc_id == TODO_ID else None
            ),
        ),
        patch(f"{MODULE}.workflow_repository.get_for_user", AsyncMock(return_value=None)),
        patch(
            f"{MODULE}.run_repository.get",
            AsyncMock(
                side_effect=lambda run_id, **_: object() if run and run_id == RUN_ID else None
            ),
        ),
    ):
        return await leaked_internals(USER, list(texts))


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("approved ap_0123456789ab for you", ["ap_0123456789ab"]),
        ("I used GMAIL_SEND_EMAIL to send it", ["GMAIL_SEND_EMAIL"]),
        ("<executor_result>done</executor_result>", ["<executor_result", "</executor_result"]),
        ("the executor finished", ["executor"]),
        ("a subagent made a tool call", ["subagent", "tool call"]),
        ("cancel task_id 12", ["task_id"]),
    ],
)
async def test_machinery_is_flagged(text: str, leaked: list[str]) -> None:
    assert await _leaks(text) == leaked


async def test_an_id_is_flagged_only_when_it_is_this_users_gaia_id() -> None:
    text = f"todo {TODO_ID}, run {RUN_ID}, order {ORDER_NUMBER}, commit {COMMIT}"

    assert await _leaks(text, todo=True, run=True) == [TODO_ID, RUN_ID]
    assert await _leaks(text) == []


async def test_product_words_and_ordinary_underscores_are_not_internals() -> None:
    assert (
        await _leaks("your workflow ran, the todo is done, a trigger fired, see my_file_name") == []
    )
