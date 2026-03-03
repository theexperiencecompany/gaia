import pytest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.core.nodes.manage_system_prompts import (
    _is_memory_system_message,
    manage_system_prompts_node,
)


def _sys(content, memory=False):
    kwargs = {"memory_message": True} if memory else {}
    return SystemMessage(content=content, additional_kwargs=kwargs)


def _config():
    return {"configurable": {"user_id": "u1", "thread_id": "t1"}}


def _store():
    return MagicMock()


@pytest.mark.unit
class TestIsMemorySystemMessage:
    def test_memory_flag_in_additional_kwargs(self):
        msg = SystemMessage(
            content="memory", additional_kwargs={"memory_message": True}
        )
        assert _is_memory_system_message(msg) is True

    def test_memory_flag_in_model_extra(self):
        class FakeMsg:
            additional_kwargs = {}
            model_extra = {"memory_message": True}

        assert _is_memory_system_message(FakeMsg()) is True

    def test_no_memory_flag(self):
        msg = SystemMessage(content="regular")
        assert _is_memory_system_message(msg) is False


@pytest.mark.unit
class TestManageSystemPrompts:
    def test_keeps_latest_non_memory_system_prompt(self):
        msgs = [
            _sys("old prompt"),
            HumanMessage(content="hi"),
            _sys("latest prompt"),
        ]
        state = {"messages": msgs}

        result = manage_system_prompts_node(state, _config(), _store())

        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "latest prompt"

    def test_preserves_all_memory_messages(self):
        msgs = [
            _sys("mem1", memory=True),
            _sys("mem2", memory=True),
            HumanMessage(content="hi"),
        ]
        state = {"messages": msgs}

        result = manage_system_prompts_node(state, _config(), _store())

        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 2

    def test_removes_older_non_memory_prompts(self):
        msgs = [
            _sys("oldest"),
            _sys("middle"),
            HumanMessage(content="hi"),
            _sys("newest"),
        ]
        state = {"messages": msgs}

        result = manage_system_prompts_node(state, _config(), _store())

        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "newest"

    def test_empty_messages(self):
        state = {"messages": []}

        result = manage_system_prompts_node(state, _config(), _store())

        assert result.get("messages", []) == []

    def test_only_memory_messages(self):
        msgs = [
            _sys("mem1", memory=True),
            _sys("mem2", memory=True),
            _sys("mem3", memory=True),
        ]
        state = {"messages": msgs}

        result = manage_system_prompts_node(state, _config(), _store())

        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 3

    def test_non_system_messages_preserved(self):
        msgs = [
            _sys("prompt"),
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
            ToolMessage(content="result", tool_call_id="tc1"),
        ]
        state = {"messages": msgs}

        result = manage_system_prompts_node(state, _config(), _store())

        types = [m.type for m in result["messages"]]
        assert "human" in types
        assert "ai" in types
        assert "tool" in types

    def test_mixed_memory_and_non_memory(self):
        msgs = [
            _sys("old non-mem"),
            _sys("mem1", memory=True),
            HumanMessage(content="q"),
            _sys("mem2", memory=True),
            AIMessage(content="a"),
            _sys("latest non-mem"),
        ]
        state = {"messages": msgs}

        result = manage_system_prompts_node(state, _config(), _store())

        system_msgs = [m for m in result["messages"] if m.type == "system"]
        contents = [m.content for m in system_msgs]
        assert "old non-mem" not in contents
        assert "mem1" in contents
        assert "mem2" in contents
        assert "latest non-mem" in contents
        assert len(system_msgs) == 3
