"""Recording a workflow run's tool calls, and rendering the previous run.

The trace is what replaces the checkpoint threads a workflow run now drops: if
it loses the order, the arguments, or the subagent that actually made a call,
the next run is told nothing useful about the last one.
"""

from datetime import UTC, datetime

from app.models.chat_models import ToolDataEntry
from app.models.workflow_execution_models import (
    RESULT_DIGEST_MAX_CHARS,
    RecordedCall,
    WorkflowExecution,
)
from app.services.workflow.run_trace import (
    LAST_RUN_MAX_CALLS,
    build_trace,
    render_last_run,
)


def _call_entry(
    tool_name: str,
    inputs: dict[str, object],
    output: str = "",
    subagent_id: str | None = None,
) -> ToolDataEntry:
    """A ``tool_calls_data`` entry as ``drain_executor_tool_data`` reconstructs it."""
    entry: ToolDataEntry = {
        "tool_name": "tool_calls_data",
        "data": {
            "tool_name": tool_name,
            "tool_category": "mail",
            "tool_call_id": f"call_{tool_name}",
            "inputs": inputs,
            "output": output,
        },
    }
    if subagent_id:
        entry["subagent_id"] = subagent_id
    return entry


def _execution(trace: list[RecordedCall], summary: str | None = None) -> WorkflowExecution:
    return WorkflowExecution(
        execution_id="exec_1",
        workflow_id="wf_1",
        user_id="u_1",
        status="success",
        started_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
        completed_at=datetime(2026, 8, 27, 9, 5, tzinfo=UTC),
        summary=summary,
        trace=trace,
    )


class TestBuildTrace:
    def test_it_keeps_the_order_the_calls_were_emitted_in(self) -> None:
        trace = build_trace(
            [
                _call_entry("GMAIL_FETCH", {"q": "is:unread"}),
                _call_entry("GMAIL_ARCHIVE", {"id": "m1"}),
                _call_entry("SEND_NOTIFICATION", {"body": "done"}),
            ]
        )

        assert [c.tool_name for c in trace] == ["GMAIL_FETCH", "GMAIL_ARCHIVE", "SEND_NOTIFICATION"]
        assert trace[0].args == {"q": "is:unread"}
        assert trace[0].tool_category == "mail"

    def test_it_keeps_a_delegated_subagents_calls_and_who_made_them(self) -> None:
        # reconstruct_subagent_groups folds a subagent's calls out of the flat
        # list and into its group; a top-level-only read would see none of them.
        group: ToolDataEntry = {
            "tool_name": "subagent_group",
            "data": {
                "subagent_id": "sa_gmail",
                "subagent_name": "gmail",
                "tool_calls": [
                    {"tool_name": "GMAIL_LIST", "inputs": {"page": 1}, "output": "3 threads"},
                ],
                "nested_subagents": [
                    {
                        "subagent_id": "sa_notion",
                        "tool_calls": [{"tool_name": "NOTION_APPEND", "inputs": {"block": "b1"}}],
                        "nested_subagents": [],
                    }
                ],
            },
        }

        trace = build_trace([_call_entry("HANDOFF", {"to": "gmail"}), group])

        assert [(c.tool_name, c.subagent_id) for c in trace] == [
            ("HANDOFF", None),
            ("GMAIL_LIST", "sa_gmail"),
            ("NOTION_APPEND", "sa_notion"),
        ]

    def test_it_tags_a_flat_entry_with_its_own_subagent_id(self) -> None:
        trace = build_trace([_call_entry("GMAIL_LIST", {}, subagent_id="sa_gmail")])

        assert trace[0].subagent_id == "sa_gmail"

    def test_it_truncates_a_result_digest_at_the_cap(self) -> None:
        trace = build_trace([_call_entry("GMAIL_FETCH", {}, output="x" * 5000)])

        assert len(trace[0].result_digest) == RESULT_DIGEST_MAX_CHARS

    def test_it_ignores_entries_that_are_not_tool_calls(self) -> None:
        card: ToolDataEntry = {"tool_name": "email_fetch_data", "data": [{"subject": "hi"}]}
        malformed: ToolDataEntry = {"tool_name": "tool_calls_data", "data": "not-a-dict"}
        unnamed: ToolDataEntry = {"tool_name": "tool_calls_data", "data": {"inputs": {}}}

        assert build_trace([card, malformed, unnamed]) == []


class TestRenderLastRun:
    def test_it_states_when_the_run_happened_and_what_each_call_did(self) -> None:
        rendered = render_last_run(
            _execution(
                [
                    RecordedCall(
                        tool_name="GMAIL_FETCH",
                        args={"query": "is:unread", "cursor": "abc123"},
                        result_digest="12 messages",
                    )
                ],
                summary="Archived 12 promos",
            )
        )

        assert "<last_run>" in rendered and "</last_run>" in rendered
        assert "status: success" in rendered
        assert "2026-08-27T09:05:00+00:00" in rendered
        # The args are the point: they are the cursor the next run picks up from.
        assert '"cursor": "abc123"' in rendered
        assert "-> 12 messages" in rendered
        assert "summary: Archived 12 promos" in rendered

    def test_it_stays_bounded_when_the_run_made_hundreds_of_calls(self) -> None:
        calls = [
            RecordedCall(
                tool_name=f"TOOL_{i}",
                args={"blob": "y" * 2000},
                result_digest="z" * RESULT_DIGEST_MAX_CHARS,
            )
            for i in range(300)
        ]

        rendered = render_last_run(_execution(calls, summary="s" * 5000))

        assert f"... and {300 - LAST_RUN_MAX_CALLS} more calls" in rendered
        assert "TOOL_0" in rendered
        assert f"TOOL_{LAST_RUN_MAX_CALLS}" not in rendered
        # Whatever the run did, one previous run costs a bounded slice of context.
        assert len(rendered) < 40_000
