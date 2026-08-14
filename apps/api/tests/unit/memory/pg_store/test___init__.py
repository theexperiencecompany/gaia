"""The memory pg_store package surface — every name the package re-exports."""

from app.memory import pg_store


def test_package_exports_the_episode_api() -> None:
    """The episode CRUD entry points and the EpisodeEntry shape are part of
    the package's public surface (consumers import them from the package)."""
    assert callable(pg_store.append_episode_entries)
    assert callable(pg_store.get_episode)
    assert callable(pg_store.get_episodes_range)
    assert callable(pg_store.search_episode_entries)


def test_episode_entry_is_the_typed_dict() -> None:
    """EpisodeEntry moved from the episodes module to models/memory_db_models
    — the package must keep exporting it under the same name."""
    from app.memory.pg_store import EpisodeEntry
    from app.models.memory_db_models import EpisodeEntry as ModelEpisodeEntry

    assert EpisodeEntry is ModelEpisodeEntry
