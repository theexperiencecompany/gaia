"""The round trip a blocked run makes to the agent that started it.

The run pauses on an AGENT-kind handoff in the worker; the joined executor is
one process away, so the request it has to read lives under a job-scoped Redis
key rather than on the job's card feed: the feed is relayed to the user's
stream, and a feed is replayed from the start, which would fire the same
request at every later join. The key exists exactly while the run is waiting.
"""

from app.constants.browser import (
    BROWSER_GUIDANCE_ANSWER,
    BROWSER_GUIDANCE_CHANGED_INSTRUCTION,
    BROWSER_GUIDANCE_HEADER,
    BROWSER_JOB_GUIDANCE_PREFIX,
)
from app.db.redis import redis_cache
from app.schemas.browser import AgentGuidanceRequest, PendingAgentGuidance
from app.services.browser.job_lifetime import browser_job_ttl_seconds


def _key(job_id: str) -> str:
    return f"{BROWSER_JOB_GUIDANCE_PREFIX}{job_id}"


async def put_guidance_request(job_id: str, pending: PendingAgentGuidance) -> None:
    """Publish the request a joined agent may answer, for as long as the run waits on it."""
    await redis_cache.set(_key(job_id), pending, ttl=browser_job_ttl_seconds())


async def get_guidance_request(job_id: str) -> PendingAgentGuidance | None:
    """Return what this job is waiting to be told, or None when it is not waiting."""
    return await redis_cache.get(_key(job_id), model=PendingAgentGuidance)


async def clear_guidance_request(job_id: str) -> None:
    """Withdraw the request once the run stopped waiting, however it stopped."""
    await redis_cache.delete(_key(job_id))


def guidance_message(request: AgentGuidanceRequest) -> str:
    """Return what the joined agent reads: why the browser is stuck, what it can see, and the one call that answers."""
    sections = [
        BROWSER_GUIDANCE_HEADER,
        f"Why it is stuck: {request.reason}",
        _changed_instruction(request),
        f"Task it is working on: {request.task}",
        f"Page it is on: {request.title or 'untitled'} ({request.url or 'no url'})",
        _recent_actions(request),
        _elements(request),
        _page_text(request),
        BROWSER_GUIDANCE_ANSWER,
    ]
    return "\n\n".join(section for section in sections if section)


def _changed_instruction(request: AgentGuidanceRequest) -> str:
    """State the instruction the user replaced the task with, above the task it overrides."""
    if not request.user_notes:
        return ""
    changed = ", then ".join(f'"{note}"' for note in request.user_notes)
    return BROWSER_GUIDANCE_CHANGED_INSTRUCTION.format(changed=changed)


def _recent_actions(request: AgentGuidanceRequest) -> str:
    if not request.recent_actions:
        return ""
    lines = "\n".join(
        f"  - {action.action}{_changed(action.page_changed)}" for action in request.recent_actions
    )
    return f"What it already tried, oldest first:\n{lines}"


def _changed(page_changed: bool | None) -> str:
    if page_changed is None:
        return ""
    return " (the page changed)" if page_changed else " (the page did not change)"


def _elements(request: AgentGuidanceRequest) -> str:
    if not request.elements:
        return ""
    lines = "\n".join(
        f"  [{element.index}] {element.label} ({element.role})" for element in request.elements
    )
    return f"Controls it can see on this screen:\n{lines}"


def _page_text(request: AgentGuidanceRequest) -> str:
    return f"Text on this screen:\n{request.page_text}" if request.page_text else ""
