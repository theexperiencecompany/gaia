"""The knowledge seeder boots the process before it builds Chroma, and stops before writing on a missing file."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.populate_gaia_knowledge import populate_knowledge

MODULE = "scripts.populate_gaia_knowledge"


async def test_it_boots_as_the_app_before_building_chroma_and_writes_nothing_without_content(
    tmp_path: Path,
) -> None:
    order = MagicMock()
    order.aget = AsyncMock()
    with (
        patch(f"{MODULE}.boot_process", order.boot_process),
        patch(f"{MODULE}.providers.aget", order.aget),
        patch(f"{MODULE}.gaia_knowledge_service") as service,
    ):
        await populate_knowledge(content_path=str(tmp_path / "missing.md"), clear_first=True)

    assert [call[0] for call in order.mock_calls] == ["boot_process", "aget"]
    order.boot_process.assert_called_once_with("main_app")
    order.aget.assert_awaited_once_with("chromadb_constructor")
    assert service.mock_calls == []
