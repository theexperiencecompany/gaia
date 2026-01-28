"""
ChromaDB Storage Backend for Skills.

Provides async CRUD operations for skill storage with semantic search.
Skills are isolated per agent_id (e.g., twitter_agent, github_agent).

Uses ChromaDB for vector storage and semantic similarity search.
"""

from datetime import datetime
from typing import Any, List, Optional
from uuid import uuid4

from langchain_core.documents import Document

from app.agents.memory.skill_learning.models import Skill, SkillSearchResult, SkillType
from app.config.loggers import llm_logger as logger
from app.db.chroma.chromadb import ChromaClient

# Collection name for skills in ChromaDB
SKILLS_COLLECTION = "agent_skills"


def _skill_to_document(skill: Skill) -> Document:
    """Convert a Skill model to a LangChain Document for ChromaDB.

    The page_content contains the searchable text (trigger + procedure).
    Metadata contains all other fields for filtering and retrieval.
    """
    # Combine trigger and procedure for semantic search
    page_content = f"{skill.trigger}\n\n{skill.procedure}"

    if skill.tools_used:
        page_content += f"\n\nTools: {', '.join(skill.tools_used)}"

    metadata = {
        "agent_id": skill.agent_id,
        "skill_type": skill.skill_type.value,
        "trigger": skill.trigger,
        "tools_used": ",".join(skill.tools_used) if skill.tools_used else "",
        "unnecessary_tools": ",".join(skill.unnecessary_tools)
        if skill.unnecessary_tools
        else "",
        "success_criteria": skill.success_criteria or "",
        "improvements": skill.improvements or "",
        "optimal_approach": skill.optimal_approach or "",
        "what_worked": skill.what_worked or "",
        "what_didnt_work": skill.what_didnt_work or "",
        "gotchas": skill.gotchas or "",
        "session_id": skill.session_id or "",
        "created_at": skill.created_at.isoformat(),
        "usage_count": skill.usage_count,
    }

    return Document(page_content=page_content, metadata=metadata)


def _document_to_skill(doc: Document, doc_id: str) -> Skill:
    """Convert a ChromaDB Document back to a Skill model."""
    metadata = doc.metadata

    # Parse tools_used back to list
    tools_used = []
    if metadata.get("tools_used"):
        tools_used = [t.strip() for t in metadata["tools_used"].split(",") if t.strip()]

    # Parse unnecessary_tools back to list
    unnecessary_tools = []
    if metadata.get("unnecessary_tools"):
        unnecessary_tools = [
            t.strip() for t in metadata["unnecessary_tools"].split(",") if t.strip()
        ]

    # Parse created_at back to datetime
    created_at = datetime.fromisoformat(
        metadata.get("created_at", datetime.utcnow().isoformat())
    )

    return Skill(
        id=doc_id,
        agent_id=metadata.get("agent_id", ""),
        skill_type=SkillType(metadata.get("skill_type", "extracted")),
        trigger=metadata.get("trigger", ""),
        procedure=doc.page_content.split("\n\n")[1]
        if "\n\n" in doc.page_content
        else doc.page_content,
        tools_used=tools_used,
        unnecessary_tools=unnecessary_tools,
        success_criteria=metadata.get("success_criteria") or None,
        improvements=metadata.get("improvements") or None,
        optimal_approach=metadata.get("optimal_approach") or None,
        what_worked=metadata.get("what_worked") or None,
        what_didnt_work=metadata.get("what_didnt_work") or None,
        gotchas=metadata.get("gotchas") or None,
        session_id=metadata.get("session_id") or None,
        created_at=created_at,
        usage_count=metadata.get("usage_count", 0),
    )


async def _get_skills_collection():
    """Get the skills ChromaDB collection."""
    return await ChromaClient.get_langchain_client(
        collection_name=SKILLS_COLLECTION,
        create_if_not_exists=True,
    )


async def store_skill(skill: Skill) -> Optional[str]:
    """Store a skill in ChromaDB.

    Args:
        skill: The skill to store

    Returns:
        The document ID, or None if failed
    """
    try:
        collection = await _get_skills_collection()
        doc = _skill_to_document(skill)

        # Generate a unique ID
        skill_id = str(uuid4())

        # Add to ChromaDB
        await collection.aadd_documents(
            documents=[doc],
            ids=[skill_id],
        )

        logger.debug(f"[{skill.agent_id}] Stored skill: {skill.trigger[:50]}...")
        return skill_id

    except Exception as e:
        logger.error(f"[{skill.agent_id}] Failed to store skill: {e}")
        return None


async def store_skills_batch(skills: List[Skill]) -> int:
    """Store multiple skills in ChromaDB.

    Args:
        skills: List of skills to store

    Returns:
        Number of skills successfully stored
    """
    if not skills:
        return 0

    try:
        collection = await _get_skills_collection()

        documents = []
        ids = []

        for skill in skills:
            doc = _skill_to_document(skill)
            skill_id = str(uuid4())
            documents.append(doc)
            ids.append(skill_id)

        # Batch add to ChromaDB
        await collection.aadd_documents(
            documents=documents,
            ids=ids,
        )

        agent_id = skills[0].agent_id if skills else "unknown"
        logger.debug(f"[{agent_id}] Stored {len(skills)} skills")
        return len(skills)

    except Exception as e:
        agent_id = skills[0].agent_id if skills else "unknown"
        logger.error(f"[{agent_id}] Failed to store skills batch: {e}")
        return 0


async def search_skills(
    query: str,
    agent_id: str,
    limit: int = 5,
    skill_type: Optional[SkillType] = None,
) -> SkillSearchResult:
    """Search for relevant skills using semantic similarity.

    Args:
        query: Search query (what the user is trying to do)
        agent_id: Agent to search skills for (required for isolation)
        limit: Maximum number of results
        skill_type: Optional filter by skill type

    Returns:
        SkillSearchResult with matching skills
    """
    if not agent_id:
        return SkillSearchResult(skills=[], query=query, agent_id="")

    try:
        collection = await _get_skills_collection()

        # Build filter for agent_id (and optionally skill_type)
        where_filter: dict[str, Any] = {"agent_id": agent_id}
        if skill_type:
            where_filter = {
                "$and": [
                    {"agent_id": agent_id},
                    {"skill_type": skill_type.value},
                ]
            }

        # Semantic similarity search
        results = await collection.asimilarity_search_with_score(
            query=query,
            k=limit,
            filter=where_filter,
        )

        # Convert to Skill objects
        skills = []
        for doc, score in results:
            # Extract ID from metadata or generate one
            doc_id = doc.metadata.get("id", str(uuid4()))
            skill = _document_to_skill(doc, doc_id)
            skills.append(skill)

        if skills:
            logger.debug(
                f"[{agent_id}] Found {len(skills)} skills for query: {query[:50]}..."
            )

        return SkillSearchResult(skills=skills, query=query, agent_id=agent_id)

    except Exception as e:
        logger.error(f"[{agent_id}] Failed to search skills: {e}")
        return SkillSearchResult(skills=[], query=query, agent_id=agent_id)


async def get_skills_by_agent(
    agent_id: str,
    limit: int = 50,
    skill_type: Optional[SkillType] = None,
) -> List[Skill]:
    """Get all skills for an agent.

    Note: This uses a broad search query to retrieve skills.
    For large collections, consider pagination.

    Args:
        agent_id: Agent to get skills for
        limit: Maximum number of skills to return
        skill_type: Optional filter by skill type

    Returns:
        List of skills
    """
    try:
        collection = await _get_skills_collection()

        # Build filter
        where_filter: dict[str, Any] = {"agent_id": agent_id}
        if skill_type:
            where_filter = {
                "$and": [
                    {"agent_id": agent_id},
                    {"skill_type": skill_type.value},
                ]
            }

        # Use a generic query to get all skills for this agent
        results = await collection.asimilarity_search_with_score(
            query="skill procedure workflow",  # Generic query
            k=limit,
            filter=where_filter,
        )

        skills = []
        for doc, score in results:
            doc_id = doc.metadata.get("id", str(uuid4()))
            skill = _document_to_skill(doc, doc_id)
            skills.append(skill)

        return skills

    except Exception as e:
        logger.error(f"[{agent_id}] Failed to get skills: {e}")
        return []


async def increment_usage(skill_id: str) -> bool:
    """Increment the usage count for a skill.

    Note: ChromaDB doesn't support in-place updates well.
    For now, this is a no-op. Consider tracking usage separately.

    Args:
        skill_id: The skill document ID

    Returns:
        True (always, as this is currently a no-op)
    """
    # ChromaDB doesn't support easy metadata updates
    # Usage tracking could be done via a separate MongoDB collection
    # or by re-adding the document with updated metadata
    logger.debug(f"Usage tracking for skill {skill_id} (no-op in ChromaDB)")
    return True


async def delete_skill(skill_id: str) -> bool:
    """Delete a skill by ID.

    Args:
        skill_id: The skill document ID

    Returns:
        True if deleted
    """
    try:
        collection = await _get_skills_collection()

        # Get the underlying ChromaDB collection for deletion
        # LangChain Chroma wrapper doesn't expose delete directly
        await collection.adelete(ids=[skill_id])
        return True

    except Exception as e:
        logger.error(f"Failed to delete skill: {e}")
        return False


async def delete_skills_by_agent(agent_id: str) -> int:
    """Delete all skills for an agent.

    Note: This requires fetching all skills first, then deleting.

    Args:
        agent_id: Agent to delete skills for

    Returns:
        Number of skills deleted
    """
    try:
        # First, get all skills for this agent
        skills = await get_skills_by_agent(agent_id, limit=1000)

        if not skills:
            return 0

        collection = await _get_skills_collection()

        # Collect IDs to delete
        ids_to_delete = [s.id for s in skills if s.id]

        if ids_to_delete:
            await collection.adelete(ids=ids_to_delete)

        return len(ids_to_delete)

    except Exception as e:
        logger.error(f"[{agent_id}] Failed to delete skills: {e}")
        return 0
