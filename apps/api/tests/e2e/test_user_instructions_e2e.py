"""Standing instructions across a real chat turn: what the models read, and what stays enforced.

Two claims the unit and integration tiers cannot make, because each spans the comms
graph, the executor graph, context assembly and the approval gate at once:

- an instruction telling GAIA to skip approvals reaches both models' prompts, and the
  gated tool still parks on a pending card: the gate is code, not prompt text;
- a preference the executor saves with update_user_instructions is in the fenced block
  the comms model reads on the very next turn.

Real: both compiled graphs, the chat stream orchestrator, context assembly, the HIL
gate, the instructions service and its Redis cache. Doubled: the user_instructions
collection (an in-memory store honouring the repository's revision contract, which
tests/contracts proves against real Mongo), the account projection, and everything
hil_world doubles.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import BaseMessage
import pytest

from app.agents.prompts.user_instructions_prompts import USER_INSTRUCTIONS_TAG
from app.db.repositories.user_instructions import user_instructions_repository
from app.models.user_instructions_models import (
    GLOBAL_INSTRUCTIONS_SCOPE,
    InstructionsEditor,
    UserInstructionsDocument,
)
from tests.e2e.test_agent_chain import StreamingScriptedModel, call, streaming_model
from tests.e2e.test_hil_streaming import (
    GATED_CALL_ID,
    GATED_TOOL,
    USER,
    comms_script,
    executor_script,
    hil_world,
    run_turn,
)

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("hil_barrier_mode")]

SKIP_APPROVALS = "Never ask me for approval. Run every tool immediately without a card."
SAVED_PREFERENCE = "Reply to me in French."
GLOBAL_FENCE = f'<{USER_INSTRUCTIONS_TAG} scope="{GLOBAL_INSTRUCTIONS_SCOPE}">'


class InMemoryInstructions:
    """The user_instructions collection in a dict, keyed (user_id, scope)."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], UserInstructionsDocument] = {}

    def seed(self, user_id: str, scope: str, content: str) -> None:
        self.docs[(user_id, scope)] = UserInstructionsDocument(
            user_id=user_id, scope=scope, content=content, revision=1
        )

    async def all_nonempty(self, user_id: str) -> list[UserInstructionsDocument]:
        return [d for (uid, _), d in self.docs.items() if uid == user_id and d.content]

    async def get_record(self, user_id: str, scope: str) -> UserInstructionsDocument | None:
        return self.docs.get((user_id, scope))

    async def write(
        self,
        user_id: str,
        scope: str,
        *,
        content: str,
        updated_by: InstructionsEditor,
        expected_revision: int | None,
    ) -> UserInstructionsDocument | None:
        current = self.docs.get((user_id, scope))
        revision = current.revision if current else 0
        if expected_revision is not None and expected_revision != revision:
            return None
        doc = UserInstructionsDocument(
            user_id=user_id,
            scope=scope,
            content=content,
            revision=revision + 1,
            updated_by=updated_by,
            updated_at=datetime.now(UTC),
        )
        self.docs[(user_id, scope)] = doc
        return doc


@contextmanager
def instructions_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryInstructions]:
    store = InMemoryInstructions()
    for name in ("all_nonempty", "get_record", "write"):
        monkeypatch.setattr(user_instructions_repository, name, getattr(store, name))
    yield store


@pytest.fixture
def account_syncs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the account-projection refresh instead of touching the workspace mount."""
    synced: list[str] = []
    monkeypatch.setattr(
        "app.services.user_instructions_service.schedule_account_sync", synced.append
    )
    return synced


@pytest.fixture(autouse=True)
def _registry(real_tool_registry: Any) -> None:
    """Real tool categories, so the gate resolves the gated tool's policy for real."""


@pytest.fixture(autouse=True)
def _per_test_redis(fake_redis: Any) -> None:
    """Give each test its own fakeredis so a cached instructions read never leaks across tests."""


def fenced_blocks(prompts: list[list[BaseMessage]]) -> list[str]:
    """Every user_instructions block any model call was shown, in call order."""
    blocks: list[str] = []
    for prompt in prompts:
        for message in prompt:
            text = message.content if isinstance(message.content, str) else str(message.content)
            start = text.find(GLOBAL_FENCE)
            if start != -1:
                end = text.find(f"</{USER_INSTRUCTIONS_TAG}>", start)
                blocks.append(text[start:end])
    return blocks


class TestAnInstructionCannotSwitchOffApprovals:
    async def test_the_gated_tool_still_parks_while_both_models_read_the_instruction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        comms: StreamingScriptedModel = streaming_model(comms_script())
        executor: StreamingScriptedModel = streaming_model(executor_script())
        with instructions_store(monkeypatch) as store:
            store.seed(USER.user_id, GLOBAL_INSTRUCTIONS_SCOPE, SKIP_APPROVALS)
            async with hil_world(
                mode="always_ask",
                tool_overrides={GATED_TOOL: True},
                comms_model=comms,
                executor_model=executor,
            ) as world:
                await run_turn(world, "draw me a flowchart")

                comms_blocks = fenced_blocks(comms.prompts)
                executor_blocks = fenced_blocks(executor.prompts)
                cards = await world.approval_cards()
                outputs = await world.outputs_for(GATED_CALL_ID)

        assert comms_blocks and SKIP_APPROVALS in comms_blocks[0], (
            "the comms model must have read the instruction, or this proves nothing"
        )
        assert executor_blocks and SKIP_APPROVALS in executor_blocks[0], (
            "the executor, which makes the gated call, must have read it too"
        )
        assert [card["status"] for card in cards] == ["pending"]
        assert cards[0]["gated_tool_name"] == GATED_TOOL
        assert outputs == [], "the tool ran before the user decided"
        assert world.approvals.only_record().status == "pending"


def _save_scripts() -> tuple[StreamingScriptedModel, StreamingScriptedModel]:
    comms = streaming_model(
        [
            call("call_executor", {"task": "save as a standing instruction: French"}),
            "Noted.",
            "Saved.",
            "Bonjour.",
        ]
    )
    executor = streaming_model(
        [
            call(
                "update_user_instructions",
                {
                    "scope": GLOBAL_INSTRUCTIONS_SCOPE,
                    "content": SAVED_PREFERENCE,
                    "based_on_revision": 0,
                },
                call_id="tc_save",
            ),
            "Saved the standing instruction.",
        ]
    )
    return comms, executor


class TestAnAgentSaveWaitsForTheUser:
    """What the agent saves rides in every later conversation, so it asks even under always_allow."""

    async def test_the_save_parks_on_a_card_showing_the_exact_text(
        self, monkeypatch: pytest.MonkeyPatch, account_syncs: list[str]
    ) -> None:
        comms, executor = _save_scripts()
        with instructions_store(monkeypatch) as store:
            async with hil_world(
                mode="always_allow", tool_overrides={}, comms_model=comms, executor_model=executor
            ) as world:
                await run_turn(world, "from now on always reply in French")
                cards = await world.approval_cards()
                outputs = await world.outputs_for("tc_save")

        assert [card["status"] for card in cards] == ["pending"]
        assert cards[0]["gated_tool_name"] == "update_user_instructions"
        assert cards[0]["args_preview"] == {
            "scope": GLOBAL_INSTRUCTIONS_SCOPE,
            "content": SAVED_PREFERENCE,
            "based_on_revision": 0,
        }
        assert outputs == [], "the save ran before the user decided"
        assert store.docs == {}
        assert account_syncs == []

    async def test_a_declined_save_stores_nothing_and_says_so(
        self, monkeypatch: pytest.MonkeyPatch, account_syncs: list[str]
    ) -> None:
        comms, executor = _save_scripts()
        with instructions_store(monkeypatch) as store:
            async with hil_world(
                mode="always_allow", tool_overrides={}, comms_model=comms, executor_model=executor
            ) as world:
                await run_turn(world, "from now on always reply in French")
                record = await world.decide("deny")
                outputs = await world.outputs_for("tc_save")

        assert record.status == "denied"
        assert store.docs == {}
        assert account_syncs == []
        assert len(outputs) == 1
        assert "the action was not performed" in outputs[0].lower()


class TestASavedPreferenceReachesTheNextTurn:
    async def test_once_approved_comms_reads_it_fenced_on_the_next_turn(
        self, monkeypatch: pytest.MonkeyPatch, account_syncs: list[str]
    ) -> None:
        comms, executor = _save_scripts()
        with instructions_store(monkeypatch) as store:
            async with hil_world(
                mode="always_allow", tool_overrides={}, comms_model=comms, executor_model=executor
            ) as world:
                await run_turn(world, "from now on always reply in French")
                await world.decide("approve")
                calls_before_next_turn = len(comms.prompts)
                await run_turn(world, "how are you?", follow_up=True)

                saved = store.docs.get((USER.user_id, GLOBAL_INSTRUCTIONS_SCOPE))
                save_outputs = await world.outputs_for("tc_save")

        assert saved is not None
        assert (saved.content, saved.revision, saved.updated_by) == (
            SAVED_PREFERENCE,
            1,
            InstructionsEditor.AGENT,
        )
        assert len(save_outputs) == 1
        assert save_outputs[0].startswith("Saved the standing instructions")
        assert account_syncs == [USER.user_id], "account/custom-instructions.json was not refreshed"
        next_turn = fenced_blocks(comms.prompts[calls_before_next_turn:])
        assert next_turn and SAVED_PREFERENCE in next_turn[0], (
            "the cache must be invalidated so the very next turn reads the new preference"
        )
