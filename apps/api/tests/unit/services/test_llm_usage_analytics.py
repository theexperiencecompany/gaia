"""Unit tests for app/services/llm_usage_analytics.py.

The PostHog client is mocked, never capture_event itself: a wrong distinct_id
is the failure mode that matters, and mocking the helper would hide it.
"""

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.constants.llm import DEFAULT_MODEL_NAME
from app.services.analytics_service import AIFeature, AnalyticsEvents
from app.services.llm_metering import TokenUsage
from app.services.llm_usage_analytics import (
    _MEMORY_LABEL_PREFIX,
    capture_auxiliary_llm_call,
    feature_for_label,
    graph_call_properties,
    llm_feature,
)


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
    assert llm_feature("executor_agent", "wf-1") is AIFeature.WORKFLOW


def test_a_graph_tier_without_a_workflow_is_chat() -> None:
    assert llm_feature("comms_agent", None) is AIFeature.CHAT
    assert llm_feature("executor_agent", None) is AIFeature.CHAT


def test_a_subagent_is_integration_spend() -> None:
    assert llm_feature("gmail_agent", None) is AIFeature.INTEGRATION


def test_a_subagent_inside_a_workflow_is_still_workflow_spend() -> None:
    """agent_name still records which subagent ran, so nothing is lost."""
    assert llm_feature("gmail_agent", "wf-9") is AIFeature.WORKFLOW


# --- graph_call_properties ---------------------------------------------------- #


def test_graph_properties_carry_feature_and_surface() -> None:
    props = graph_call_properties("comms_agent", "web", None)
    assert props == {"feature": "chat", "surface": "ui"}


def test_graph_properties_carry_the_workflow_when_there_is_one() -> None:
    props = graph_call_properties("executor_agent", None, "wf-7")
    assert props["feature"] == "workflow"
    assert props["workflow_id"] == "wf-7"


def test_a_bot_turn_reports_the_bot_surface() -> None:
    assert graph_call_properties("comms_agent", "discord", None)["surface"] == "bot"


def test_an_unset_source_reports_background() -> None:
    """Only the silent background paths leave the source blank."""
    assert graph_call_properties("executor_agent", None, None)["surface"] == "bg"


# --- feature_for_label -------------------------------------------------------- #


def test_a_mapped_label_resolves_to_its_feature() -> None:
    assert feature_for_label("onboarding_inbox_triage") is AIFeature.ONBOARDING
    assert feature_for_label("workflow_prompt") is AIFeature.WORKFLOW_GENERATION


def test_the_runtime_built_memory_label_resolves_by_prefix() -> None:
    """Built at runtime, so it is matched by prefix rather than exact key."""
    assert feature_for_label("memory:extract") is AIFeature.MEMORY
    assert feature_for_label("memory:consolidate") is AIFeature.MEMORY


def test_the_browser_handoff_resolver_is_browser_spend() -> None:
    assert feature_for_label("browser_handoff_conversational_resolve") is AIFeature.BROWSER


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


# --- capture_auxiliary_llm_call ----------------------------------------------- #


def _capture(user_id: str | None = "user-1", **overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "label": "memory:extract",
        "model_name": DEFAULT_MODEL_NAME,
        "usage": TokenUsage(
            input_tokens=3000, output_tokens=150, cached_tokens=400, reasoning_tokens=20
        ),
        "cost_usd": 0.00036,
    }
    capture_auxiliary_llm_call(**{**kwargs, **overrides})


def test_the_event_is_attributed_to_the_gaia_user_id(posthog: Any) -> None:
    _capture(user_id="mongo-user-42")
    call = _captured(posthog)
    assert call["distinct_id"] == "mongo-user-42"
    assert call["event"] == AnalyticsEvents.AI_LLM_CALL_COMPLETED


def test_the_event_carries_the_tokens_cost_and_attribution(posthog: Any) -> None:
    _capture()
    props = _captured(posthog)["properties"]
    assert props["feature"] == "memory"
    assert props["label"] == "memory:extract"
    assert props["input_tokens"] == 3000
    assert props["output_tokens"] == 150
    assert props["cached_tokens"] == 400
    assert props["reasoning_tokens"] == 20
    assert props["total_tokens"] == 3150
    assert props["cost_usd"] == 0.00036


def test_background_spend_is_never_marked_charged(posthog: Any) -> None:
    """Auxiliary work is not billed to the user's budget."""
    _capture()
    props = _captured(posthog)["properties"]
    assert props["charged"] is False
    assert props["surface"] == "bg"


def test_a_call_with_no_user_is_skipped_not_left_anonymous(posthog: Any) -> None:
    _capture(user_id=None)
    posthog.capture.assert_not_called()


def test_the_skip_says_which_call_it_dropped(posthog: Any) -> None:
    """The warning is the only trace a skipped call leaves."""
    with patch("app.services.llm_usage_analytics.log") as mock_log:
        _capture(user_id=None, label="memory:extract", model_name=DEFAULT_MODEL_NAME)

    mock_log.warning.assert_called_once_with(
        "llm_call_unattributed", label="memory:extract", model=DEFAULT_MODEL_NAME
    )


def test_an_unmapped_label_raises_an_error_line_naming_itself(posthog: Any) -> None:
    """The error line is what makes a label no member claims greppable."""
    with patch("app.services.llm_usage_analytics.log") as mock_log:
        _capture(label="helper_added_without_a_table_entry")

    mock_log.error.assert_called_once_with(
        "llm_call_unmapped_label",
        label="helper_added_without_a_table_entry",
        model=DEFAULT_MODEL_NAME,
    )
    assert _captured(posthog)["properties"]["feature"] == "unattributed"


def test_a_mapped_label_logs_no_error(posthog: Any) -> None:
    with patch("app.services.llm_usage_analytics.log") as mock_log:
        _capture(label="memory:extract")

    mock_log.error.assert_not_called()


def test_a_priced_model_is_not_flagged_as_estimated(posthog: Any) -> None:
    _capture(model_name=DEFAULT_MODEL_NAME)
    assert _captured(posthog)["properties"]["cost_estimated"] is False


def test_a_model_missing_from_the_rate_card_is_flagged(posthog: Any) -> None:
    """An unpriced model falls back to DEFAULT_PRICING, so the figure is plausible and wrong."""
    _capture(model_name="some/model-nobody-priced")
    assert _captured(posthog)["properties"]["cost_estimated"] is True


def test_the_event_is_not_deduped(posthog: Any) -> None:
    """A retry is a second real charge; collapsing them under-reports spend."""
    _capture()
    assert "uuid" not in _captured(posthog)


def test_the_event_carries_no_message_content(posthog: Any) -> None:
    _capture()
    assert set(_captured(posthog)["properties"]) == {
        "feature",
        "surface",
        "label",
        "model",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "total_tokens",
        "cost_usd",
        "charged",
        "cost_estimated",
        "timestamp",
    }


def test_every_feature_is_reachable() -> None:
    """A member reached by no label and no graph rule charts as zero spend, not as a bug."""
    graph_reachable = {
        llm_feature("comms_agent", None),
        llm_feature("gmail_agent", None),
        llm_feature("comms_agent", "wf-1"),
    }
    reachable = (
        {f for f in AIFeature if f.labels}
        | graph_reachable
        | {feature_for_label(f"{_MEMORY_LABEL_PREFIX}store")}
        | {AIFeature.UNATTRIBUTED}
    )

    assert set(AIFeature) - reachable == set()
