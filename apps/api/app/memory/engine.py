"""The memory engine facade — the single entry point callers import.

All heavy lifting lives in the focused modules; the facade only binds them
into one object so call sites read ``memory_engine.<operation>(...)``:

- ``ingestion``     — write path: retain / retain_single / summarize_episode
- ``consolidation`` — background: debounced core-document rewrites
- ``retrieval``     — read path: recall / recall_episodes (hybrid, zero-LLM)
- ``context``       — hot path: get_core_context (Redis-cached, every turn)
- ``management``    — tree / graph / journal / documents / CRUD / wipe
"""

from app.memory import consolidation, context, ingestion, management, retrieval
from app.memory.ingestion import RetainedMemory, RetainResult

__all__ = ["MemoryEngine", "RetainResult", "RetainedMemory", "memory_engine"]


class MemoryEngine:
    """Facade over the memory engine. Use the module-level ``memory_engine``."""

    # --- write path (plan F2) ------------------------------------------------
    retain = staticmethod(ingestion.retain)
    retain_single = staticmethod(ingestion.retain_single)
    summarize_episode = staticmethod(ingestion.summarize_episode)
    consolidate = staticmethod(consolidation.consolidate)

    # --- read path (plan F1/F3) ----------------------------------------------
    recall = staticmethod(retrieval.recall)
    recall_episodes = staticmethod(retrieval.recall_episodes)
    get_core_context = staticmethod(context.get_core_context)
    invalidate_core_context = staticmethod(context.invalidate_core_context)

    # --- management: settings UI + tools (plan F4/F6) ------------------------
    get_tree = staticmethod(management.get_tree)
    get_graph = staticmethod(management.get_graph)
    get_episodes = staticmethod(management.get_episodes)
    get_documents = staticmethod(management.get_documents)
    get_document = staticmethod(management.get_document)
    update_document = staticmethod(management.update_document)
    list_memories = staticmethod(management.list_memories)
    update_memory = staticmethod(management.update_memory)
    forget_memory = staticmethod(management.forget_memory)
    delete_all = staticmethod(management.delete_all)
    get_overview = staticmethod(management.get_overview)


memory_engine = MemoryEngine()
