"""Read-back verification middleware: re-read after a write to confirm the effect."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
import pytest

from app.agents.middleware.read_back import ReadBackContract, ReadBackMiddleware

# A tiny scripted "mailbox" the fake tools operate on.
_INBOX = {"e1", "e2", "e3"}


@tool
def archive(email_id: str) -> str:
    """Archive an email."""
    _INBOX.discard(email_id)
    return f"archived {email_id}"


@tool
def list_inbox() -> str:
    """List remaining inbox ids."""
    return " ".join(sorted(_INBOX))


async def _archive_verifier(write_args, write_result, tools_by_name):
    """Confirm the archived id is no longer in the inbox (the read-back oracle)."""
    remaining = await tools_by_name["list_inbox"].ainvoke({})
    eid = write_args.get("email_id", "")
    if eid and eid not in remaining.split():
        return f"confirmed {eid} is no longer in the inbox"
    return f"WARNING: {eid} still present after archive — the write did not take effect"


def _request(name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": name, "args": args, "id": f"c_{name}"})


def _handler_running(tools_by_name):
    async def handler(request):
        t = tools_by_name[request.tool_call["name"]]
        out = await t.ainvoke(request.tool_call["args"])
        return ToolMessage(
            content=out, tool_call_id=request.tool_call["id"], name=request.tool_call["name"]
        )

    return handler


class TestReadBack:
    def setup_method(self):
        _INBOX.clear()
        _INBOX.update({"e1", "e2", "e3"})

    async def test_successful_write_gets_verified(self):
        mw = ReadBackMiddleware({"archive": ReadBackContract(_archive_verifier)})
        mw.set_tools([archive, list_inbox])
        handler = _handler_running({"archive": archive, "list_inbox": list_inbox})

        result = await mw.awrap_tool_call(_request("archive", {"email_id": "e1"}), handler)

        assert "[Read-back verification]" in result.content
        assert "confirmed e1 is no longer in the inbox" in result.content
        assert result.additional_kwargs.get("read_back_verified") is True

    async def test_uncontracted_tool_is_untouched(self):
        mw = ReadBackMiddleware({"archive": ReadBackContract(_archive_verifier)})
        mw.set_tools([archive, list_inbox])
        handler = _handler_running({"archive": archive, "list_inbox": list_inbox})

        result = await mw.awrap_tool_call(_request("list_inbox", {}), handler)
        assert "[Read-back verification]" not in result.content

    async def test_verifier_exception_never_breaks_the_run(self):
        async def boom(write_args, write_result, tools_by_name):
            raise RuntimeError("read-back exploded")

        mw = ReadBackMiddleware({"archive": ReadBackContract(boom)})
        mw.set_tools([archive, list_inbox])
        handler = _handler_running({"archive": archive, "list_inbox": list_inbox})

        # Must return the original write result, not raise.
        result = await mw.awrap_tool_call(_request("archive", {"email_id": "e1"}), handler)
        assert result.content == "archived e1"
        assert "[Read-back verification]" not in result.content

    async def test_failed_write_is_not_verified(self):
        async def err_handler(request):
            return ToolMessage(
                content="permission denied",
                tool_call_id=request.tool_call["id"],
                name=request.tool_call["name"],
                status="error",
            )

        mw = ReadBackMiddleware({"archive": ReadBackContract(_archive_verifier)})
        mw.set_tools([archive, list_inbox])
        result = await mw.awrap_tool_call(_request("archive", {"email_id": "e1"}), err_handler)
        assert "[Read-back verification]" not in result.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
