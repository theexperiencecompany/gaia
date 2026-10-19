"""get_session_id: which workspace session a coding tool reads and writes.

The parent conversation's session must win over the executor's own thread, or
an executor call's artifacts land in a session dir nothing else reads.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.tools.coding._context import get_session_id

_EVERY_SOURCE: RunnableConfig = {
    "configurable": {
        "vfs_session_id": "vfs",
        "conversation_id": "conv",
        "thread_id": "thread",
    },
    "metadata": {"conversation_id": "meta-conv"},
}


@pytest.mark.parametrize(
    ("config", "session_id"),
    [
        (_EVERY_SOURCE, "vfs"),
        (
            {
                "configurable": {"conversation_id": "conv", "thread_id": "thread"},
                "metadata": {"conversation_id": "meta-conv"},
            },
            "conv",
        ),
        (
            {"configurable": {"thread_id": "thread"}, "metadata": {"conversation_id": "meta-conv"}},
            "meta-conv",
        ),
        ({"configurable": {"thread_id": "thread"}}, "thread"),
        ({"configurable": {}}, None),
    ],
    ids=["vfs-session", "conversation", "metadata-conversation", "thread", "none"],
)
def test_the_session_is_read_in_precedence_order(
    config: RunnableConfig, session_id: str | None
) -> None:
    assert get_session_id(config) == session_id
