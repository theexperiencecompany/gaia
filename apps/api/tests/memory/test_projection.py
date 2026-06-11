"""Workspace projection tests — /workspace/memory materialized to a tmp root.

``sync_user_memory_fs`` is exercised end-to-end (fetch from real Postgres,
hash gate, materialize) with the JuiceFS mount redirected into ``tmp_path``
via the two seams the scheduler module already owns (``_is_mounted`` and
``user_workspace_path``). The fire-and-forget schedulers inside management/
ingestion are silenced so every write in these tests is an explicit,
awaited sync — no background tasks racing the assertions.
"""

from datetime import UTC, datetime
from pathlib import Path
import stat

import pytest

from app.constants.memory import MemoryDocType
from app.memory import pg_store
from app.memory.engine import memory_engine
from app.models.memory_db_models import MemoryRecord
from app.services import _vfs_scheduler
from app.services.memory_fs import sync_user_memory_fs
from tests.memory.store import seed_memories

pytestmark = pytest.mark.memory


@pytest.fixture
def workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the VFS mount into tmp_path and disable background syncs."""
    monkeypatch.setattr(_vfs_scheduler, "_is_mounted", lambda: True)
    monkeypatch.setattr(
        _vfs_scheduler, "user_workspace_path", lambda user_id: tmp_path / "users" / user_id
    )
    monkeypatch.setattr("app.memory.ingestion.schedule_memory_vfs_sync", lambda user_id: None)
    monkeypatch.setattr("app.memory.management.schedule_memory_vfs_sync", lambda user_id: None)
    return tmp_path


def _memory_dir(workspace_root: Path, user_id: str) -> Path:
    return workspace_root / "users" / user_id / "memory"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def _seed_standard_projection(user_id: str) -> list[MemoryRecord]:
    await pg_store.upsert_document(user_id, MemoryDocType.USER_MD, "# Aryan\nEngineer.")
    records = await seed_memories(
        user_id,
        [
            {
                "content": "Aryan's partner is Nadia.",
                "category": "relationships/partner",
                "importance": 0.9,
            },
            {"content": "Aryan is vegetarian.", "category": "food-preferences"},
        ],
    )
    await pg_store.append_episode_entries(
        user_id,
        datetime.now(UTC).date(),
        [{"time": "09:00", "text": "Asked GAIA to plan groceries", "source": "conversation"}],
    )
    return records


async def test_materialize_writes_docs_journal_and_fact_pages(
    memory_user: str, workspace_root: Path
) -> None:
    records = await _seed_standard_projection(memory_user)
    written = await sync_user_memory_fs(memory_user)
    assert written >= 4, f"expected doc+journal+2 fact pages written, got {written}"

    memory_dir = _memory_dir(workspace_root, memory_user)
    today = datetime.now(UTC).date().isoformat()

    user_md = memory_dir / "user.md"
    assert user_md.read_text(encoding="utf-8") == "# Aryan\nEngineer.\n"
    assert _mode(user_md) == 0o444, "projected bodies must be read-only"

    guide = memory_dir / "GUIDE.md"
    assert guide.is_file()
    assert _mode(guide) == 0o644, "GUIDE.md must stay author-writable"

    journal = memory_dir / "journal" / f"{today}.md"
    journal_text = journal.read_text(encoding="utf-8")
    assert f"# {today}" in journal_text
    assert "- 09:00 Asked GAIA to plan groceries" in journal_text
    assert _mode(journal) == 0o444

    partner_page = memory_dir / "facts" / "relationships" / "partner.md"
    partner_text = partner_page.read_text(encoding="utf-8")
    assert "# relationships/partner" in partner_text
    partner_record = next(r for r in records if r.category_path == "relationships/partner")
    assert f"- Aryan's partner is Nadia.  <!-- id:{partner_record.id} importance:0.9 -->" in (
        partner_text
    )
    assert (memory_dir / "facts" / "food-preferences.md").is_file()


async def test_resync_is_a_hash_gated_noop(memory_user: str, workspace_root: Path) -> None:
    await _seed_standard_projection(memory_user)
    first = await sync_user_memory_fs(memory_user)
    assert first > 0
    second = await sync_user_memory_fs(memory_user)
    assert second == 0, "unchanged state must short-circuit on the catalog signature"


async def test_stale_fact_page_pruned_when_folder_empties(
    memory_user: str, workspace_root: Path
) -> None:
    records = await _seed_standard_projection(memory_user)
    await sync_user_memory_fs(memory_user)
    memory_dir = _memory_dir(workspace_root, memory_user)
    partner_page = memory_dir / "facts" / "relationships" / "partner.md"
    assert partner_page.is_file()

    partner_record = next(r for r in records if r.category_path == "relationships/partner")
    assert await memory_engine.forget_memory(memory_user, str(partner_record.id), "stale")

    written = await sync_user_memory_fs(memory_user)
    assert written == 0, "pruning a page rewrites nothing"
    assert not partner_page.exists(), "fact page for an emptied folder must be removed"
    assert not partner_page.parent.exists(), "emptied category directory must be pruned"
    assert (memory_dir / "facts" / "food-preferences.md").is_file(), "other pages must survive"


async def test_journal_page_renders_summary_section_after_rollover(
    memory_user: str, workspace_root: Path
) -> None:
    await _seed_standard_projection(memory_user)
    await sync_user_memory_fs(memory_user)

    today = datetime.now(UTC).date()
    await pg_store.set_episode_summary(memory_user, today, "Planned groceries with GAIA.")
    written = await sync_user_memory_fs(memory_user)
    assert written == 1, "summary change must rewrite exactly the journal page"

    journal_text = (
        _memory_dir(workspace_root, memory_user) / "journal" / f"{today.isoformat()}.md"
    ).read_text(encoding="utf-8")
    assert "## Summary" in journal_text
    assert "Planned groceries with GAIA." in journal_text
