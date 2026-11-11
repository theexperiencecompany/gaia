"""A user's standing instructions, global and per integration — the one read/write path.

Reads are Redis-cached per user and invalidated on every write. The user (REST) and
the agent (update_user_instructions) both write through write_instructions, so the
cache, the account projection and the integrations/<id>/agent/instructions.md
projection all derive from the same record.
"""

from __future__ import annotations

import hashlib

from app.constants.cache import USER_INSTRUCTIONS_CACHE_KEY, USER_INSTRUCTIONS_CACHE_TTL
from app.constants.error_codes import INSTRUCTIONS_CONFLICT
from app.db.repositories.user_instructions import user_instructions_repository
from app.decorators.caching import Cacheable, CacheInvalidator
from app.models.user_instructions_models import (
    GLOBAL_INSTRUCTIONS_SCOPE,
    MAX_INSTRUCTIONS_CHARS,
    InstructionsEditor,
    InstructionsResponse,
)
from app.services.account_fs import schedule_account_sync
from app.services.analytics_service import capture
from app.services.integrations.user_integrations import check_user_has_integration
from app.services.integrations_fs import schedule_user_integrations_sync
from app.services.storage.juicefs import ensure_safe_path_id
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import (
    InstructionsConflict,
    InstructionsScopeKind,
    InstructionsUpdated,
)
from shared.py.wide_events import log


@Cacheable(key_pattern=USER_INSTRUCTIONS_CACHE_KEY, ttl=USER_INSTRUCTIONS_CACHE_TTL)
async def get_all_instructions(user_id: str) -> dict[str, str]:
    """Return {scope: content} for every non-empty scope; one cached read per turn."""
    docs = await user_instructions_repository.all_nonempty(user_id)
    return {d.scope: d.content for d in docs if d.content}


async def get_instructions(user_id: str, scope: str) -> str | None:
    """Return one scope's instructions, or None when unset."""
    instructions: dict[str, str] = await get_all_instructions(user_id)
    return instructions.get(scope)


async def get_instructions_record(user_id: str, scope: str) -> InstructionsResponse:
    """Uncached read with the revision an editor must send back on save."""
    doc = await user_instructions_repository.get_record(user_id, scope)
    if doc is None:
        return InstructionsResponse(scope=scope)
    return InstructionsResponse(
        scope=scope,
        content=doc.content,
        revision=doc.revision,
        updated_by=doc.updated_by,
        updated_at=doc.updated_at,
    )


async def validate_scope(user_id: str, scope: str) -> None:
    """Accept the global scope or one of the user's connected integrations; raise otherwise."""
    if scope == GLOBAL_INSTRUCTIONS_SCOPE:
        return
    try:
        ensure_safe_path_id(scope, label="scope")
    except ValueError as e:
        raise AppError(
            message=f"Invalid instructions scope '{scope}'",
            fix=f"Use '{GLOBAL_INSTRUCTIONS_SCOPE}' or a connected integration's id",
            status_code=400,
        ) from e
    if not await check_user_has_integration(user_id, scope):
        raise AppError(
            message=f"'{scope}' is not one of this user's connected integrations",
            fix="Connect the integration first, or set global instructions instead",
            status_code=404,
        )


@CacheInvalidator(key_patterns=[USER_INSTRUCTIONS_CACHE_KEY])
async def write_instructions(
    user_id: str,
    scope: str,
    content: str,
    *,
    updated_by: InstructionsEditor,
    base_revision: int | None = None,
) -> InstructionsResponse:
    """Replace one scope's instructions; base_revision None (agent writes) skips the conflict check.

    Raises AppError 409 when base_revision is stale, carrying the current revision.
    """
    log.set(instructions={"scope_kind": _scope_kind(scope), "updated_by": updated_by.value})
    await validate_scope(user_id, scope)
    if len(content) > MAX_INSTRUCTIONS_CHARS:
        raise AppError(
            message=f"Instructions must be {MAX_INSTRUCTIONS_CHARS} characters or less",
            fix="Shorten the instructions and try again",
            status_code=400,
        )
    stored = content if content.strip() else ""
    doc = await user_instructions_repository.write(
        user_id,
        scope,
        content=stored,
        updated_by=updated_by,
        expected_revision=base_revision,
    )
    if doc is None:
        current = await get_instructions_record(user_id, scope)
        capture(UserId(user_id), InstructionsConflict(scope_kind=_scope_kind(scope)))
        raise AppError(
            message="These instructions were changed somewhere else since you opened them",
            fix="Load the latest version, or save again to overwrite it",
            status_code=409,
            code=INSTRUCTIONS_CONFLICT,
            public={"current_revision": current.revision},
        )
    log.set_ns("instructions", revision=doc.revision, chars=len(stored))
    if scope == GLOBAL_INSTRUCTIONS_SCOPE:
        schedule_account_sync(user_id)
    else:
        schedule_user_integrations_sync(user_id)
    capture(
        UserId(user_id),
        InstructionsUpdated(
            scope_kind=_scope_kind(scope), updated_by=updated_by, cleared=not stored
        ),
    )
    return InstructionsResponse(
        scope=scope,
        content=doc.content,
        revision=doc.revision,
        updated_by=doc.updated_by,
        updated_at=doc.updated_at,
    )


def integration_instructions(instructions: dict[str, str]) -> dict[str, str]:
    """Drop the global scope, which is projected to account/ instead of integrations/."""
    return {
        scope: body for scope, body in instructions.items() if scope != GLOBAL_INSTRUCTIONS_SCOPE
    }


def instructions_signature(instructions: dict[str, str]) -> str:
    """Stable hash the session bootstrap compares to decide whether to rewrite the projection."""
    digest = hashlib.sha256()
    for scope in sorted(instructions):
        digest.update(scope.encode())
        digest.update(b"\0")
        digest.update(instructions[scope].encode())
        digest.update(b"\0")
    return digest.hexdigest()[:32]


def _scope_kind(scope: str) -> InstructionsScopeKind:
    return "global" if scope == GLOBAL_INSTRUCTIONS_SCOPE else "integration"
