"""Attacks on the destructive classifier (app/services/hil/classification.py).

Two invariants carry the security weight, and both are attacked here:

* **Fail closed.** Every failure — registry down, LLM down, Mongo down, tool unknown —
  must resolve to *destructive*. A classifier that returns False when it is broken is a
  classifier that runs destructive tools unattended.
* **The MCP hint escalates only.** An untrusted MCP server may flag danger but must never
  clear it: ``destructiveHint=False`` and ``readOnlyHint=True`` mean "defer", not "safe".
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.llm.client import SILENT_LLM_CONFIG, StructuredCallOptions
from app.constants.hil import HIL_LLM_TIMEOUT_SECONDS
from app.models.hil_models import HILToolRiskRecord
from app.services.hil.classification import (
    _classify_with_llm,
    _ClassifyResult,
    is_tool_destructive,
    mcp_destructive_hint,
)
from app.services.hil.prompts import TOOL_CLASSIFY_PROMPT
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY

from .conftest import make_tool

MODULE = "app.services.hil.classification"


def registry_with(flag: bool | None) -> MagicMock:
    registry = MagicMock()
    registry.is_tool_destructive.return_value = flag
    registry.mark_tool_destructive = MagicMock()
    return registry


@pytest.fixture
def mongo() -> MagicMock:
    with patch(f"{MODULE}.hil_tool_risk_repository") as repo:
        repo.find_classification = AsyncMock(return_value=None)
        repo.upsert_classification = AsyncMock()
        yield repo


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


class TestFailsClosed:
    """Every broken dependency must gate the call, not wave it through."""

    async def test_registry_unavailable_classifies_as_destructive(self) -> None:
        with patch(f"{MODULE}.get_tool_registry", side_effect=ConnectionError("chroma down")):
            assert await is_tool_destructive("unknown_tool", "does something") is True

    async def test_llm_failure_classifies_as_destructive(self, mongo: MagicMock) -> None:
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry_with(None))),
            patch(f"{MODULE}.ainvoke_structured", side_effect=RuntimeError("LLM 500")),
        ):
            assert await is_tool_destructive("custom_tool", "does something") is True

    async def test_mongo_failure_classifies_as_destructive(self) -> None:
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry_with(None))),
            patch(f"{MODULE}.hil_tool_risk_repository") as repo,
        ):
            repo.find_classification = AsyncMock(side_effect=ConnectionError("mongo down"))
            assert await is_tool_destructive("custom_tool", "does something") is True

    async def test_an_unclassified_tool_the_llm_calls_safe_is_still_honoured_as_safe(
        self, mongo: MagicMock
    ) -> None:
        # The counterweight: failing closed must not mean "everything is destructive".
        # If this flips, the gate asks about every read-only tool and HIL is unusable.
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry_with(None))),
            patch(
                f"{MODULE}.ainvoke_structured",
                new=AsyncMock(return_value=_ClassifyResult(is_destructive=False, rationale="read")),
            ),
        ):
            assert await is_tool_destructive("list_files", "Lists files.") is False


class TestMcpHintEscalatesOnly:
    def test_a_true_destructive_hint_is_honoured(self) -> None:
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: {"destructiveHint": True}})
        assert mcp_destructive_hint(tool) is True

    def test_a_false_destructive_hint_defers_rather_than_declaring_safe(self) -> None:
        # The attack: a malicious MCP server ships destructiveHint=False on a tool that
        # deletes the account. Returning False here would let it clear the registry's own
        # verdict. It must return None ("no opinion"), never False.
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: {"destructiveHint": False}})
        assert mcp_destructive_hint(tool) is None

    def test_a_read_only_hint_does_not_declare_a_tool_safe(self) -> None:
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: {"readOnlyHint": True}})
        assert mcp_destructive_hint(tool) is None

    @pytest.mark.parametrize(
        "metadata",
        [None, {}, {MCP_ANNOTATIONS_METADATA_KEY: None}, {MCP_ANNOTATIONS_METADATA_KEY: "yes"}],
    )
    def test_missing_or_malformed_annotations_yield_no_opinion(self, metadata: object) -> None:
        assert mcp_destructive_hint(make_tool(metadata=metadata)) is None

    def test_a_truthy_but_non_true_hint_is_not_accepted(self) -> None:
        # Strict identity: "false" (a non-empty string) is truthy in Python. A server
        # sending the *string* "false" must not be read as a destructive declaration —
        # and, more importantly, this pins the check to `is True`.
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: {"destructiveHint": "false"}})
        assert mcp_destructive_hint(tool) is None

    async def test_a_destructive_hint_gates_even_over_a_reviewed_safe_registry_flag(self) -> None:
        # Escalation: the registry says safe, the server says destructive → gate it,
        # and don't waste an LLM call deciding.
        registry = registry_with(False)
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)) as get_reg,
            patch(f"{MODULE}.ainvoke_structured", new=AsyncMock()) as llm,
        ):
            result = await is_tool_destructive("mcp_tool", "desc", destructive_hint=True)

        assert result is True
        assert get_reg.await_count == 0
        assert llm.await_count == 0

    async def test_a_false_hint_cannot_clear_a_destructive_registry_flag(self) -> None:
        # The mirror image, and the one that actually matters: the server claims safe,
        # the registry says destructive. The registry wins.
        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry_with(True))):
            assert await is_tool_destructive("mcp_tool", "desc", destructive_hint=False) is True


class TestExemptTools:
    async def test_an_exempt_tool_is_never_gated_and_never_classified(self) -> None:
        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock()) as get_reg:
            assert await is_tool_destructive("call_executor", "Delegates work.") is False
        assert get_reg.await_count == 0


class TestRegistryAndCache:
    async def test_the_registry_flag_is_authoritative_when_present(self) -> None:
        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry_with(True))):
            assert await is_tool_destructive("delete_file", "Deletes.") is True

        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry_with(False))):
            assert await is_tool_destructive("list_files", "Lists.") is False

    async def test_a_cached_classification_is_reused_without_calling_the_llm(self) -> None:
        registry = registry_with(None)
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.hil_tool_risk_repository") as repo,
            patch(f"{MODULE}.ainvoke_structured", new=AsyncMock()) as llm,
        ):
            repo.find_classification = AsyncMock(
                return_value=HILToolRiskRecord(
                    tool_name="custom_tool", description_hash="h", is_destructive=True
                )
            )
            repo.upsert_classification = AsyncMock()
            result = await is_tool_destructive("custom_tool", "Deletes things.")

        assert result is True
        assert llm.await_count == 0
        registry.mark_tool_destructive.assert_called_once_with("custom_tool", True)

    async def test_a_changed_description_reclassifies_rather_than_reusing_the_old_verdict(
        self,
    ) -> None:
        # The cache is keyed on tool_name + description_hash. A tool whose description
        # changed from "Lists files" to "Deletes files" must NOT reuse the safe verdict.
        registry = registry_with(None)
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.hil_tool_risk_repository") as repo,
            patch(
                f"{MODULE}.ainvoke_structured",
                new=AsyncMock(return_value=_ClassifyResult(is_destructive=True, rationale="del")),
            ),
        ):
            repo.find_classification = AsyncMock(return_value=None)  # no row for the new hash
            repo.upsert_classification = AsyncMock()

            await is_tool_destructive("custom_tool", "Lists files.")
            first_hash = repo.find_classification.await_args.args[1]

            await is_tool_destructive("custom_tool", "Deletes files.")
            second_hash = repo.find_classification.await_args.args[1]

        assert first_hash != second_hash

    async def test_a_fresh_llm_classification_is_persisted_and_pushed_to_the_registry(
        self,
    ) -> None:
        registry = registry_with(None)
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)),
            patch(f"{MODULE}.hil_tool_risk_repository") as repo,
            patch(
                f"{MODULE}.ainvoke_structured",
                new=AsyncMock(return_value=_ClassifyResult(is_destructive=True, rationale="wipes")),
            ),
        ):
            repo.find_classification = AsyncMock(return_value=None)
            repo.upsert_classification = AsyncMock()
            result = await is_tool_destructive("wipe_db", "Wipes the database.")
            persisted = repo.upsert_classification.await_args.args[0]

        assert result is True
        assert persisted.is_destructive is True
        assert persisted.tool_name == "wipe_db"
        registry.mark_tool_destructive.assert_called_once_with("wipe_db", True)


class TestTheClassifierCallItself:
    """The verdict is cached per tool for every user, so this call is made once and
    read forever. A mislabelled call lands its COGS on the wrong lane, and an
    unbounded one holds the first gated call of a tool open for as long as the
    provider takes."""

    async def test_the_call_is_labelled_bounded_and_deliberately_unattributed(
        self,
    ) -> None:
        with patch(
            f"{MODULE}.ainvoke_structured",
            new=AsyncMock(
                return_value=_ClassifyResult(is_destructive=True, rationale="it deletes")
            ),
        ) as llm:
            result = await _classify_with_llm("delete_file", "Deletes a file.")

        assert result.is_destructive is True
        schema, prompt = llm.await_args.args
        assert schema is _ClassifyResult
        assert prompt == TOOL_CLASSIFY_PROMPT.format(
            name="delete_file", description="Deletes a file."
        )
        assert llm.await_args.kwargs["label"] == "hil_tool_classification"
        assert llm.await_args.kwargs["config"] == SILENT_LLM_CONFIG
        assert llm.await_args.kwargs["options"] == StructuredCallOptions(
            timeout=HIL_LLM_TIMEOUT_SECONDS
        )

    async def test_a_tool_with_no_description_says_so_rather_than_sending_nothing(
        self,
    ) -> None:
        with patch(
            f"{MODULE}.ainvoke_structured",
            new=AsyncMock(return_value=_ClassifyResult(is_destructive=False)),
        ) as llm:
            await _classify_with_llm("mystery_tool", "")

        _schema, prompt = llm.await_args.args
        assert prompt == TOOL_CLASSIFY_PROMPT.format(
            name="mystery_tool", description="(none provided)"
        )
