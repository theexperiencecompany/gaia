"""Browser mid-run handoff + live-view token endpoints (authenticated, same-origin).

Handoff: when the agent hands off a sensitive step to the user, the card's
Continue/Cancel buttons POST here; the decision is written to Redis, unblocking
the browser tool that is polling for it (the tool may run in a different worker
process — Redis is the bridge).

Live-view token: the live view itself is served at the root ``/live/{id}`` route
(``endpoints/browser_live_view.py``), fronted by a friendly public vhost the
host-only session cookie is never sent to. The chat card therefore fetches a
short-lived ``?t=`` takeover token here (cookie auth works same-origin to the
API) and opens the cross-origin live-view socket with it.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from playwright.sync_api import StorageState

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.config.settings import settings
from app.constants.browser import BROWSER_IMPORT_TOKEN_TTL_SECONDS
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserForgetAllResponse,
    BrowserImportRequest,
    BrowserImportResponse,
    BrowserLoginResponse,
    BrowserTaskResponse,
    HandoffDecisionRequest,
    HandoffDecisionResponse,
    ImportTokenResponse,
    LiveViewTokenResponse,
)
from app.services.browser import registry
from app.services.browser.exceptions import BrowserHandoffNotOwned
from app.services.browser.handoff import get_handoff, resolve_handoff
from app.services.browser.import_token import consume_import_token, mint_import_token
from app.services.browser.profiles import forget_saved_login, list_saved_logins
from app.services.browser.storage_persistence import import_browser_profile
from app.services.browser.takeover_token import (
    create_takeover_token,
    takeover_token_ttl_seconds,
    verify_takeover_token,
)
from app.services.browser.tasks import delete_browser_task, list_browser_tasks
from shared.py.wide_events import log

router = APIRouter(prefix="/browser", tags=["Browser"])


@router.get("/handoffs/{handoff_id}")
async def get_browser_handoff(
    handoff_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> HandoffDecisionResponse:
    """Current status of a browser handoff — the card polls this so a reload or a
    resolution made elsewhere (chat, another device) is reflected reliably."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    log.set(user={"id": user_id}, browser={"handoff_id": handoff_id})
    record = await get_handoff(handoff_id)
    if record is None or record.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found")
    return HandoffDecisionResponse(handoff_id=handoff_id, status=record.status)


@router.post("/handoffs/{handoff_id}/decision")
async def decide_browser_handoff(
    handoff_id: str,
    payload: HandoffDecisionRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> HandoffDecisionResponse:
    """Continue (user finished the step in live-view) or cancel a browser handoff."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    log.set(
        user={"id": user_id}, browser={"handoff_id": handoff_id, "decision": payload.decision.value}
    )

    try:
        resolved = await resolve_handoff(handoff_id, payload.decision, user_id, payload.message)
    except BrowserHandoffNotOwned as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to resolve this handoff"
        ) from exc

    if resolved is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Handoff not found or expired")

    log.info(
        f"{LogTag.BROWSER} Browser handoff decided", handoff_id=handoff_id, status=resolved.value
    )
    return HandoffDecisionResponse(handoff_id=handoff_id, status=resolved)


@router.get("/sessions/{session_id}/live-view-token", response_model=LiveViewTokenResponse)
async def get_live_view_token(
    session_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> LiveViewTokenResponse:
    """Mint a short-lived takeover token so the web card can open the cross-origin
    live view (the host-only session cookie is not sent to the live-view vhost)."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    log.set(
        user={"id": user_id}, browser={"session_id": session_id, "operation": "live_view_token"}
    )

    owner = await registry.session_owner(session_id)
    if owner is None or owner != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this session"
        )

    token = create_takeover_token(session_id, str(user_id))
    log.info(f"{LogTag.BROWSER} browser live view token issued")
    claims = verify_takeover_token(token)
    return LiveViewTokenResponse(
        token=token, expires_in=max(int(takeover_token_ttl_seconds(claims)), 0)
    )


@router.get("/tasks", response_model=list[BrowserTaskResponse])
async def list_browser_tasks_endpoint(
    user_id: Annotated[str, Depends(get_user_id)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[BrowserTaskResponse]:
    """The user's browser task history (settings), newest first, with recap URLs."""
    log.set(user={"id": user_id}, browser={"operation": "list_tasks"})
    tasks = await list_browser_tasks(user_id, limit=limit)
    log.set(browser={"result_count": len(tasks)})
    return tasks


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_browser_task_endpoint(
    task_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> None:
    """Remove one task from the user's browser history."""
    log.set(user={"id": user_id}, browser={"operation": "delete_task", "task_id": task_id})
    await delete_browser_task(user_id, task_id)


@router.get("/logins", response_model=list[BrowserLoginResponse])
async def list_browser_logins_endpoint(
    user_id: Annotated[str, Depends(get_user_id)],
) -> list[BrowserLoginResponse]:
    """Domains the user has a saved browser login for (never the encrypted state)."""
    log.set(user={"id": user_id}, browser={"operation": "list_logins"})
    logins = await list_saved_logins(user_id)
    log.audit(
        "browser logins listed",
        actor=user_id,
        resource="browser/logins",
        count=len(logins),
    )
    return logins


@router.delete("/logins", response_model=BrowserForgetAllResponse)
async def forget_all_browser_logins_endpoint(
    user_id: Annotated[str, Depends(get_user_id)],
) -> BrowserForgetAllResponse:
    """Forget every saved login for the user — the settings 'Clear all'."""
    log.set(user={"id": user_id}, browser={"operation": "forget_all_logins"})
    count = await forget_saved_login(user_id, None)
    log.audit("all browser logins forgotten", actor=user_id, resource="browser/logins", count=count)
    return BrowserForgetAllResponse(forgotten=count)


@router.delete("/logins/{domain}", status_code=204)
async def forget_browser_login_endpoint(
    domain: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> None:
    """Forget the saved login for one domain."""
    log.set(user={"id": user_id}, browser={"operation": "forget_login", "domain": domain})
    await forget_saved_login(user_id, domain)
    log.audit(
        "browser login forgotten",
        actor=user_id,
        resource=domain,
    )


@router.delete("/logins", status_code=204)
async def clear_browser_logins_endpoint(
    user_id: Annotated[str, Depends(get_user_id)],
) -> None:
    """Forget every saved browser login for the user."""
    log.set(user={"id": user_id}, browser={"operation": "clear_logins"})
    await forget_saved_login(user_id, None)
    log.audit(
        "browser logins cleared",
        actor=user_id,
        resource="browser/logins",
    )


@router.post("/import/token", response_model=ImportTokenResponse)
async def mint_browser_import_token(
    user: Annotated[dict, Depends(get_current_user)],
) -> ImportTokenResponse:
    """Mint the short-lived, single-use code the local ``gaia connect`` CLI
    presents to upload this user's browser profile. Authorised by the web
    session; the CLI, which has no cookie, authenticates with the returned code."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id required")
    token = await mint_import_token(str(user_id))
    log.info(f"{LogTag.BROWSER} Minted browser import token", user={"id": user_id})
    return ImportTokenResponse(token=token, expires_in_seconds=BROWSER_IMPORT_TOKEN_TTL_SECONDS)


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP: the first hop of ``X-Forwarded-For`` when set by the
    proxy, else the direct peer. None when neither is available."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


@router.post("/import", response_model=BrowserImportResponse)
async def import_browser_sessions(
    payload: BrowserImportRequest, request: Request
) -> BrowserImportResponse:
    """Receive a browser profile from the local CLI and store it as saved logins.

    Authenticated by the single-use import code, not a session cookie — the CLI
    runs outside the browser. The uploaded storage_state is split per host and
    encrypted at rest by the same store that seeds every future task."""
    user_id = await consume_import_token(payload.token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Import code invalid, expired, or already used",
        )
    if not settings.BROWSER_PERSIST_LOGINS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Browser login persistence is disabled",
        )
    log.set(user={"id": user_id})
    state = cast(
        StorageState,
        {
            "cookies": [c.model_dump(by_alias=True) for c in payload.cookies],
            "origins": [o.model_dump(by_alias=True) for o in payload.origins],
        },
    )
    imported = await import_browser_profile(
        user_id,
        state,
        source_browser=payload.source_browser,
        source_ip=_client_ip(request),
    )
    return BrowserImportResponse(
        imported=[BrowserLoginResponse(domain=host, updated_at=None) for host, _ in imported],
        host_count=len(imported),
        cookie_count=len(payload.cookies),
    )
