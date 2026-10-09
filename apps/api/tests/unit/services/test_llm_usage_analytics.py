"""Unit tests for app/services/llm_usage_analytics.py.

The PostHog client is mocked, never capture itself: a wrong distinct_id
is the failure mode that matters, and mocking the helper would hide it.
"""

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.constants.llm import DEFAULT_MODEL_NAME
from app.db.repositories.llm_calls import LLMCallDocument
from app.services.analytics_service import AIFeature
from app.services.llm_usage_analytics import (
    _MEMORY_LABEL_PREFIX,
    capture_llm_call,
    feature_for_label,
    llm_feature,
)
from shared.py.analytics.catalog.agents import AiLlmCallCompleted

USER = "6a40d2f0c1b2a3d4e5f60718"


@pytest.fixture
def posthog() -> Any:
    client = MagicMock()
    with patch(
        "app.services.analytics_service._get_posthog_client",
        return_value=client,
    ):
        yield client


def _captured(posthog: Any) -> dict[str, Any]:
    return dict(posthog.capture.call_args.kwargs)


# --- llm_feature -------------------------------------------------------------- #


def test_a_workflow_run_is_workflow_spend() -> None:
    assert llm_feature("executor_agent", "wf-1", background=False) is AIFeature.WORKFLOW


def test_a_graph_tier_without_a_workflow_is_chat() -> None:
    assert llm_feature("comms_agent", None, background=False) is AIFeature.CHAT
    assert llm_feature("executor_agent", None, background=False) is AIFeature.CHAT


def test_a_subagent_is_integration_spend() -> None:
    assert llm_feature("gmail_agent", None, background=False) is AIFeature.INTEGRATION


def test_a_subagent_inside_a_workflow_is_still_workflow_spend() -> None:
    """agent_name still records which subagent ran, so nothing is lost."""
    assert llm_feature("gmail_agent", "wf-9", background=False) is AIFeature.WORKFLOW


def test_a_browser_run_is_browser_spend_not_an_integration() -> None:
    assert llm_feature("browser_task", None, background=False) is AIFeature.BROWSER


def test_a_background_call_is_attributed_by_its_label() -> None:
    """A one-shot inside a workflow run is still the memory or follow-up work it did."""
    assert llm_feature("memory:extract", "wf-1", background=True) is AIFeature.MEMORY


# --- feature_for_label -------------------------------------------------------- #


def test_a_mapped_label_resolves_to_its_feature() -> None:
    assert feature_for_label("onboarding_inbox_triage") is AIFeature.ONBOARDING
    assert feature_for_label("workflow_prompt") is AIFeature.WORKFLOW_GENERATION


def test_the_runtime_built_memory_label_resolves_by_prefix() -> None:
    """Built at runtime, so it is matched by prefix rather than exact key."""
    assert feature_for_label("memory:extract") is AIFeature.MEMORY
    assert feature_for_label("memory:consolidate") is AIFeature.MEMORY


def test_an_unmapped_label_is_unattributed_rather_than_guessed() -> None:
    assert feature_for_label("some_helper_added_next_year") is AIFeature.UNATTRIBUTED


_METERED_CALLS = {"ainvoke_llm", "ainvoke_structured", "ainvoke_structured_gemini"}


def _label_taking_functions(trees: dict[Path, ast.Module]) -> set[str]:
    """Find the functions that forward their own label argument into a metered call.

    Three call sites pass a variable or an f-string rather than a literal, so
    scanning only literal label= at the metered call would skip whatever their
    callers pass - exactly where a new unmapped label would hide.
    """
    forwarding: set[str] = set()
    for tree in trees.values():
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
            if "label" not in params:
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                if getattr(node.func, "id", "") not in _METERED_CALLS:
                    continue
                for kw in node.keywords:
                    if kw.arg == "label" and isinstance(kw.value, ast.Name):
                        forwarding.add(fn.name)
    return forwarding


def test_every_label_the_codebase_passes_has_a_feature() -> None:
    """Walk the real call sites, forwarding helpers included, so an unmapped label fails here."""
    app = Path(__file__).resolve().parents[3] / "app"
    trees: dict[Path, ast.Module] = {}
    for path in app.rglob("*.py"):
        try:
            trees[path] = ast.parse(path.read_text())
        except SyntaxError:
            continue

    targets = _METERED_CALLS | _label_taking_functions(trees)
    unmapped: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if name not in targets:
                continue
            for kw in node.keywords:
                if kw.arg == "label" and isinstance(kw.value, ast.Constant):
                    if feature_for_label(kw.value.value) is AIFeature.UNATTRIBUTED:
                        unmapped.add(kw.value.value)

    assert not unmapped, f"labels no AIFeature member claims: {sorted(unmapped)}"


def test_no_member_claims_a_label_nothing_passes() -> None:
    """A stale label makes the taxonomy claim a capability the code no longer has."""
    app = Path(__file__).resolve().parents[3] / "app"
    used: set[str] = set()
    for path in app.rglob("*.py"):
        # Skip the enum's own module, or every label would count as used.
        if path.name == "analytics_service.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                used.add(node.value)

    claimed = {label for feature in AIFeature for label in feature.labels}
    assert not (claimed - used), f"labels no call site passes: {sorted(claimed - used)}"


# --- capture_llm_call ---------------------------------------------------------- #


def _row(**overrides: Any) -> LLMCallDocument:
    fields: dict[str, Any] = {
        "id": "row-1",
        "created_at": datetime.now(UTC),
        "user_id": USER,
        "agent_name": "memory:extract",
        "background": True,
        "charge_to_budget": False,
        "model_requested": DEFAULT_MODEL_NAME,
        "model_served": DEFAULT_MODEL_NAME,
        "input_tokens": 3000,
        "output_tokens": 150,
        "cached_tokens": 400,
        "reasoning_tokens": 20,
        "cost_usd": 0.00036,
        "cost_source": "provider",
        "generation_id": "gen-1",
        "channel": "web",
    }
    return LLMCallDocument(**{**fields, **overrides})


def test_the_event_is_attributed_to_the_rows_user(posthog: Any) -> None:
    capture_llm_call(_row())
    call = _captured(posthog)
    assert call["distinct_id"] == USER
    assert call["event"] == AiLlmCallCompleted.event


def test_the_event_carries_the_rows_tokens_cost_and_attribution(posthog: Any) -> None:
    capture_llm_call(_row())
    props = _captured(posthog)["properties"]
    assert props["feature"] == "memory"
    assert props["agent_name"] == "memory:extract"
    assert (props["input_tokens"], props["output_tokens"]) == (3000, 150)
    assert (props["cached_tokens"], props["reasoning_tokens"]) == (400, 20)
    assert props["total_tokens"] == 3150
    assert props["cost_usd"] == 0.00036
    assert props["cost_source"] == "provider"
    assert props["background"] is True
    assert props["charge_to_budget"] is False


def test_the_channel_is_the_surface_the_call_came_from(posthog: Any) -> None:
    capture_llm_call(_row(channel="discord"))
    assert _captured(posthog)["properties"]["channel"] == "discord"


def test_a_call_with_no_channel_sends_no_channel(posthog: Any) -> None:
    capture_llm_call(_row(channel=None))
    assert "channel" not in _captured(posthog)["properties"]


def test_a_graph_row_is_charged_chat_spend(posthog: Any) -> None:
    capture_llm_call(_row(agent_name="comms_agent", background=False, charge_to_budget=True))
    props = _captured(posthog)["properties"]
    assert props["feature"] == "chat"
    assert props["charge_to_budget"] is True


def test_a_row_inside_a_workflow_is_charged_workflow_spend(posthog: Any) -> None:
    capture_llm_call(_row(agent_name="comms_agent", background=False, workflow_id="wf-1"))

    assert _captured(posthog)["properties"]["feature"] == "workflow"


def test_an_error_row_says_it_failed_and_why(posthog: Any) -> None:
    """The ledger keeps failures so an outage reads as errors, not a dip in traffic; the event must too."""
    capture_llm_call(
        _row(
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            reasoning_tokens=0,
            cost_usd=0.0,
            status="error",
            error_family="timeout",
        )
    )
    props = _captured(posthog)["properties"]
    assert (props["status"], props["error_family"]) == ("error", "timeout")


def test_the_event_is_keyed_by_the_ledger_row(posthog: Any) -> None:
    """One row is one event: a replayed emit collapses, two real calls (two rows) never do."""
    capture_llm_call(_row(id="row-42"))
    expected = uuid5(NAMESPACE_URL, f"{AiLlmCallCompleted.event}:{USER}:row-42")
    assert _captured(posthog)["uuid"] == str(expected)


@pytest.mark.parametrize("user_id", [None, "system", "u-not-an-object-id"])
def test_a_row_with_no_real_user_is_logged_not_sent(posthog: Any, user_id: str | None) -> None:
    with patch("app.services.llm_usage_analytics.log") as mock_log:
        capture_llm_call(_row(user_id=user_id))

    posthog.capture.assert_not_called()
    mock_log.warning.assert_called_once_with(
        "llm_call_unattributed",
        user_id=user_id,
        agent_name="memory:extract",
        model=DEFAULT_MODEL_NAME,
    )


def test_an_unmapped_label_raises_an_error_line_naming_itself(posthog: Any) -> None:
    """The error line is what makes a label no member claims greppable."""
    with patch("app.services.llm_usage_analytics.log") as mock_log:
        capture_llm_call(_row(agent_name="helper_added_without_a_table_entry"))

    mock_log.error.assert_called_once_with(
        "llm_call_unmapped_label",
        label="helper_added_without_a_table_entry",
        model=DEFAULT_MODEL_NAME,
    )
    assert _captured(posthog)["properties"]["feature"] == "unattributed"


def test_a_mapped_label_logs_no_error(posthog: Any) -> None:
    with patch("app.services.llm_usage_analytics.log") as mock_log:
        capture_llm_call(_row())

    mock_log.error.assert_not_called()


def test_the_event_carries_no_message_content(posthog: Any) -> None:
    """Counts, flags and ids only, and a None field is left out rather than sent as null."""
    capture_llm_call(_row())
    assert set(_captured(posthog)["properties"]) == {
        "feature",
        "surface",
        "agent_name",
        "background",
        "charge_to_budget",
        "model",
        "model_served",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "total_tokens",
        "cost_usd",
        "actor",
        "trigger",
        "cost_source",
        "status",
        "channel",
        "generation_id",
        "llm_call_id",
        "$ignore_sent_at",
    }


def test_every_feature_is_reachable() -> None:
    """A member reached by no label and no graph rule charts as zero spend, not as a bug."""
    graph_reachable = {
        llm_feature("comms_agent", None, background=False),
        llm_feature("gmail_agent", None, background=False),
        llm_feature("comms_agent", "wf-1", background=False),
    }
    reachable = (
        {f for f in AIFeature if f.labels}
        | graph_reachable
        | {feature_for_label(f"{_MEMORY_LABEL_PREFIX}store")}
        | {AIFeature.UNATTRIBUTED}
    )

    assert set(AIFeature) - reachable == set()
