"""Internals guard: finds GAIA machinery in text about to be told to a user.

What it flags: ids GAIA issued that belong to this user (run, todo, workflow, approval), tool
names from the registry, agent payload tags and the executor's own vocabulary. What it never
flags is the user's data: a hex string that is not one of this user's GAIA ids is an order
number or a commit, and the words workflow, todo and trigger are product words.
"""

import asyncio
import re

from app.agents.tools.core.registry import get_tool_registry
from app.constants.agents import AgentTag
from app.db.repositories.run_traces import run_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository

#: Ids with a format only GAIA mints: an approval is ap_ and twelve hex digits.
_APPROVAL_ID_RE = re.compile(r"\bap_[0-9a-f]{12}\b")
#: Ids that look like any other 24-hex or UUID string, so each is looked up before it counts.
_OBJECT_ID_RE = re.compile(r"\b[0-9a-f]{24}\b")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_TOOL_NAME_CANDIDATE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_AGENT_TAG_RE = re.compile(r"</?(?:" + "|".join(tag.value for tag in AgentTag) + r")\b")
_VOCABULARY_RE = re.compile(r"\b(?:executor|subagents?|tool calls?|task_ids?)\b", re.IGNORECASE)


async def _is_users_object_id(user_id: str, candidate: str) -> bool:
    todo, workflow = await asyncio.gather(
        todo_repository.get(candidate, user_id=user_id),
        workflow_repository.get_for_user(candidate, user_id),
    )
    return todo is not None or workflow is not None


async def _is_users_run_id(user_id: str, candidate: str) -> bool:
    return await run_repository.get(candidate, user_id=user_id) is not None


async def leaked_internals(user_id: str, texts: list[str]) -> list[str]:
    """Return what in texts exposes GAIA internals, each once and never the user's own data; empty when clean."""
    text = "\n".join(texts)
    registry = await get_tool_registry()
    tool_names = {name.lower() for name in registry.get_tool_names()}
    leaks: list[str] = []
    leaks += _APPROVAL_ID_RE.findall(text)
    leaks += [
        name
        for name in dict.fromkeys(_TOOL_NAME_CANDIDATE_RE.findall(text))
        if name.lower() in tool_names
    ]
    leaks += [match.group(0) for match in _AGENT_TAG_RE.finditer(text)]
    leaks += [match.group(0) for match in _VOCABULARY_RE.finditer(text)]
    object_ids = list(dict.fromkeys(_OBJECT_ID_RE.findall(text)))
    object_hits = await asyncio.gather(*(_is_users_object_id(user_id, c) for c in object_ids))
    leaks += [c for c, hit in zip(object_ids, object_hits, strict=True) if hit]
    run_ids = list(dict.fromkeys(_UUID_RE.findall(text)))
    run_hits = await asyncio.gather(*(_is_users_run_id(user_id, c) for c in run_ids))
    leaks += [c for c, hit in zip(run_ids, run_hits, strict=True) if hit]
    return list(dict.fromkeys(leaks))
