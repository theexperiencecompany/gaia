"""Unit tests for app.memory.management — correcting and forgetting memories.

Postgres, Chroma, the embedder and the projection scheduler are mocked; the
id-resolution and lineage logic under test is real.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.constants.memory import MemoryKind, MemoryShelfLife, MemorySourceType
from app.memory import management
from app.memory.management import MemoryNotFoundError, update_memory
from app.models.memory_db_models import MemoryRecord

USER = "user-1"


def make_row(
    *,
    content: str = "sam works at acme",
    is_latest: bool = True,
    is_forgotten: bool = False,
    version: int = 1,
    root_id: uuid.UUID | None = None,
    shelf_life: MemoryShelfLife = MemoryShelfLife.DURABLE,
    forget_after: datetime | None = None,
) -> MemoryRecord:
    row = MemoryRecord(
        user_id=USER,
        kind=MemoryKind.FACT.value,
        shelf_life=shelf_life.value,
        content=content,
        category_path="work",
        source_type=MemorySourceType.CONVERSATION.value,
        importance=0.5,
        forget_after=forget_after,
    )
    row.id = uuid.uuid4()
    row.version = version
    row.is_latest = is_latest
    row.is_forgotten = is_forgotten
    row.root_id = root_id
    row.created_at = datetime.now(UTC)
    return row


@pytest.fixture
def boundaries() -> MagicMock:
    """Patch every I/O edge of management.update_memory."""
    with (
        patch.multiple(
            management.pg_store,
            get_memory=AsyncMock(return_value=None),
            get_chain=AsyncMock(return_value=[]),
            supersede_memory=AsyncMock(return_value=None),
            get_entities_for_memories=AsyncMock(return_value={}),
            link_entities=AsyncMock(return_value=None),
        ),
        patch.multiple(
            management.chroma_store,
            set_memory_flags=AsyncMock(return_value=None),
            upsert_memories=AsyncMock(return_value=None),
        ),
        patch.multiple(
            management,
            embed_query=AsyncMock(return_value=[0.1, 0.2]),
            invalidate_user_memory_caches=AsyncMock(return_value=None),
            schedule_memory_vfs_sync=MagicMock(return_value=None),
        ),
    ):
        yield management.pg_store


@pytest.mark.unit
class TestUpdateMemoryResolvesTheChainHead:
    async def test_a_superseded_id_is_resolved_to_the_live_head(
        self, boundaries: MagicMock
    ) -> None:
        head = make_row(content="sam is a staff engineer at acme", version=2)
        stale = make_row(content="sam works at acme", is_latest=False, root_id=head.id)
        boundaries.get_memory.return_value = stale
        boundaries.get_chain.return_value = [head, stale]
        boundaries.supersede_memory.return_value = make_row(content="corrected", version=3)

        await update_memory(USER, str(stale.id), "corrected")

        assert boundaries.supersede_memory.await_args.args[0] == str(head.id)

    async def test_a_live_head_is_updated_directly(self, boundaries: MagicMock) -> None:
        head = make_row()
        boundaries.get_memory.return_value = head
        boundaries.supersede_memory.return_value = make_row(content="corrected", version=2)

        await update_memory(USER, str(head.id), "corrected")

        assert boundaries.supersede_memory.await_args.args[0] == str(head.id)
        boundaries.get_chain.assert_not_awaited()

    async def test_the_correction_inherits_the_shelf_life_and_expiry(
        self, boundaries: MagicMock
    ) -> None:
        expiry = datetime(2026, 12, 1, tzinfo=UTC)
        head = make_row(shelf_life=MemoryShelfLife.STATE, forget_after=expiry)
        boundaries.get_memory.return_value = head
        boundaries.supersede_memory.return_value = make_row(content="corrected", version=2)

        await update_memory(USER, str(head.id), "corrected")

        record = boundaries.supersede_memory.await_args.args[2]
        assert record.shelf_life == MemoryShelfLife.STATE.value
        assert record.forget_after == expiry

    async def test_the_lookup_is_scoped_to_the_caller(self, boundaries: MagicMock) -> None:
        # A memory id belonging to somebody else must not resolve: the owner is
        # half of the key, not a filter applied afterwards.
        stale = make_row(is_latest=False)
        head = make_row(version=2)
        boundaries.get_memory.return_value = stale
        boundaries.get_chain.return_value = [head]
        boundaries.supersede_memory.return_value = make_row(content="corrected", version=3)

        await update_memory(USER, str(stale.id), "corrected")

        assert boundaries.get_memory.await_args.args == (str(stale.id), USER)
        assert boundaries.get_chain.await_args.args == (str(stale.id), USER)


@pytest.mark.unit
class TestUpdateMemoryFailsLoud:
    async def test_an_unknown_id_raises(self, boundaries: MagicMock) -> None:
        boundaries.get_memory.return_value = None

        with pytest.raises(MemoryNotFoundError):
            await update_memory(USER, str(uuid.uuid4()), "corrected")

    async def test_a_malformed_id_raises_instead_of_leaking_a_value_error(
        self, boundaries: MagicMock
    ) -> None:
        boundaries.get_memory.side_effect = ValueError("badly formed hexadecimal UUID string")

        with pytest.raises(MemoryNotFoundError) as raised:
            await update_memory(USER, "not-a-uuid", "corrected")

        assert raised.value.meta == {"memory_id": "not-a-uuid"}

    async def test_a_forgotten_memory_raises(self, boundaries: MagicMock) -> None:
        memory_id = str(uuid.uuid4())
        boundaries.get_memory.return_value = make_row(is_forgotten=True)

        with pytest.raises(MemoryNotFoundError) as raised:
            await update_memory(USER, memory_id, "corrected")

        assert raised.value.meta == {"memory_id": memory_id}

    async def test_a_chain_with_no_live_head_raises(self, boundaries: MagicMock) -> None:
        stale = make_row(is_latest=False)
        boundaries.get_memory.return_value = stale
        boundaries.get_chain.return_value = [make_row(is_latest=False), stale]

        with pytest.raises(MemoryNotFoundError) as raised:
            await update_memory(USER, str(stale.id), "corrected")

        assert raised.value.meta == {"memory_id": str(stale.id)}

    async def test_a_head_that_vanished_between_resolve_and_write_raises(
        self, boundaries: MagicMock
    ) -> None:
        head = make_row()
        boundaries.get_memory.return_value = head
        boundaries.supersede_memory.return_value = None

        with pytest.raises(MemoryNotFoundError) as raised:
            await update_memory(USER, str(head.id), "corrected")

        assert raised.value.meta == {"memory_id": str(head.id)}


@pytest.mark.unit
class TestMemoryNotFoundError:
    """The error text is the tool result the model reads — it is a contract.

    The tool used to return "Error: ... not found or already superseded" as an
    ordinary result string; the model read it as success and told the user the
    memory was fixed. Every field below exists to stop that.
    """

    def test_it_names_the_id_and_tells_the_model_not_to_claim_success(self) -> None:
        error = MemoryNotFoundError("mem-42")

        assert error.message == "Memory mem-42 does not exist for this user."
        assert error.why == "The id does not name any memory in this user's store."
        assert error.fix == (
            "Call search_memory to get the current id of the fact you mean, "
            "then retry the correction with that id. Do NOT tell the user "
            "the memory was corrected — it was not."
        )
        assert error.status_code == 404
        assert error.meta == {"memory_id": "mem-42"}
