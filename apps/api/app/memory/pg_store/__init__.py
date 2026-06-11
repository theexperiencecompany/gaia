"""Postgres storage layer for the memory engine — purely CRUD, no LLM/embeddings.

Importing this package registers the memory SQLAlchemy models on the shared
declarative ``Base``, so ``create_all`` (run when the postgresql_engine
provider initializes) creates the memory tables.
"""

from app.memory.pg_store.documents import get_document, get_documents, upsert_document
from app.memory.pg_store.episodes import (
    EpisodeEntry,
    append_episode_entries,
    get_episode,
    get_episodes_range,
    get_unsummarized_episode_dates,
    set_episode_summary,
)
from app.memory.pg_store.graph import (
    get_entities_for_memories,
    get_graph,
    insert_edges,
    link_entities,
    upsert_entities,
)
from app.memory.pg_store.maintenance import (
    MemoryOverviewCounts,
    delete_all_memories,
    get_overview_counts,
)
from app.memory.pg_store.memories import (
    fts_search,
    get_folder_tree,
    get_memories_by_ids,
    get_memory,
    get_recent_facts,
    insert_memories,
    list_memories,
    mark_forgotten,
    supersede_memory,
)

__all__ = [
    "EpisodeEntry",
    "MemoryOverviewCounts",
    "append_episode_entries",
    "delete_all_memories",
    "fts_search",
    "get_document",
    "get_documents",
    "get_entities_for_memories",
    "get_episode",
    "get_episodes_range",
    "get_folder_tree",
    "get_graph",
    "get_memories_by_ids",
    "get_memory",
    "get_overview_counts",
    "get_recent_facts",
    "get_unsummarized_episode_dates",
    "insert_edges",
    "insert_memories",
    "link_entities",
    "list_memories",
    "mark_forgotten",
    "set_episode_summary",
    "supersede_memory",
    "upsert_document",
    "upsert_entities",
]
