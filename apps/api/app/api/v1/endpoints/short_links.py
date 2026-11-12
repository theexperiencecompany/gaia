"""Short links: share, change and revoke heygaia.link/<slug>, and open one at its access level.

Opening a link (GET /{slug}) takes an optional session: public and unlisted
links open for anyone, people and owner links only for the signed-in viewers
they name. Every refusal is a typed denial (LinkDenial) the page renders. A slug
is never logged: every route records the route template as the request path and
a keyed hash of the slug as short_link.slug_hash.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_optional_user
from app.api.v1.middleware.rate_limiter import limiter, viewer_ip
from app.config.settings import settings
from app.constants.short_links import (
    CONTENT_URL_RATE_LIMIT,
    MINT_RATE_LIMIT,
    REPORT_RATE_LIMIT,
    RESOLVE_RATE_LIMIT,
)
from app.models.short_link_models import (
    ContentTokenResponse,
    LinkDenial,
    LinkDenialEnvelope,
    LinkEnvelope,
    LinkPreviewMeta,
    LinkReportRequest,
    LinkSettingsUpdate,
    LinkViewer,
    ShareLinkRequest,
    ShortLink,
    ShortLinkResponse,
    ShortLinkShareState,
    ShortLinkTargetRequest,
    ShortLinkTargetType,
    StopSharingResult,
)
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import error_responses
from app.services.links import abuse
from app.services.links.content import (
    active_link_content,
    framed_content,
    issue_content_url,
    read_snapshot,
    servable,
)
from app.services.links.errors import LinkDeniedError
from app.services.links.preview import preview_meta
from app.services.links.service import (
    get_link,
    link_response,
    live_share_link,
    openable_link,
    record_open,
    resolve,
    rotate,
    share,
    stop_sharing,
    update_settings,
)
from app.services.links.serving import download_response
from app.services.openui_artifacts.export import owner_artifact_pdf, pdf_download_headers
from app.services.turnstile_service import verify_turnstile_token
from app.utils.log_identifiers import hash_link_viewer, hash_short_link_slug
from app.utils.loggable_path import (
    SHORT_LINK_ROUTE_PREFIX,
    SHORT_LINK_SHARE_STATE_PATH,
    SHORT_LINK_UNSHARE_PATH,
)
from shared.py.wide_events import log

router = APIRouter(prefix=SHORT_LINK_ROUTE_PREFIX, tags=["Short Links"])

# A link can be revoked or narrowed at any moment, so nothing may keep serving what it showed.
_NO_STORE = "private, no-store"
_META_CACHE = "public, max-age=300"
_DEAD_META_CACHE = "public, max-age=60"
_DENIALS: dict[int | str, dict[str, object]] = {
    status_code: {"model": LinkDenialEnvelope, "description": description}
    for status_code, description in (
        (401, LinkDeniedError.for_denial(LinkDenial.SIGN_IN_REQUIRED).message),
        (403, LinkDeniedError.for_denial(LinkDenial.FORBIDDEN).message),
        (404, LinkDeniedError.for_denial(LinkDenial.NOT_FOUND).message),
        (410, "The link is dead: revoked, expired, removed or its target deleted"),
    )
}


def _user_key(request: Request) -> str:
    """Count the owner routes per signed-in user, not per address."""
    user = getattr(request.state, "user", None)
    return user.user_id if isinstance(user, AuthenticatedUser) else viewer_ip(request)


def _slug_key(request: Request) -> str:
    return f"slug:{hash_short_link_slug(request.path_params.get('slug', ''))}"


def _viewer(request: Request, user: AuthenticatedUser | None) -> LinkViewer:
    return LinkViewer(
        user_id=user.user_id if user else None,
        # A local sign-in's email is whatever was typed at signup, so it grants nothing there.
        email=user.email if user and not settings.deployment.local_auth else None,
        ip=viewer_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )


async def _looked_up(request: Request, slug: str) -> ShortLink | None:
    """Return the link behind slug, counting an unknown one toward the guessing lockout."""
    viewer = viewer_ip(request)
    await abuse.refuse_when_locked_out(viewer)
    link = await get_link(slug)
    if link is None:
        await abuse.record_miss(viewer, slug)
    return link


@router.post("", responses=error_responses({404: "Target not found"}))
@limiter.limit(MINT_RATE_LIMIT, key_func=_user_key)
async def create_short_link_route(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    body: ShareLinkRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ShortLinkResponse:
    """Share an artifact you own: its live link, minted with the given settings when none is live.

    Turns sharing back on for a target its owner had stopped sharing. The
    target's own read under your account is the ownership check.
    """
    log.set(
        user={"id": user.user_id},
        short_link={"operation": "create", "target_type": body.target_type.value},
    )
    link = await share(user.user_id, body.target_type, body.target_id, body.settings)
    return link_response(link)


# Registered before /{slug}, which would otherwise capture "state" as a slug.
@router.get(SHORT_LINK_SHARE_STATE_PATH)
async def get_share_state_route(
    target: Annotated[ShortLinkTargetRequest, Query()],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ShortLinkShareState:
    """Say whether one of your artifacts is shared, with its live link and settings. Never mints one."""
    log.set(
        user={"id": user.user_id},
        short_link={"operation": "share_state", "target_type": target.target_type.value},
    )
    link = await live_share_link(user.user_id, target.target_type, target.target_id)
    log.set(short_link={"shared": link is not None})
    return ShortLinkShareState(link=link_response(link) if link else None)


@router.post(SHORT_LINK_UNSHARE_PATH)
async def stop_sharing_route(
    body: ShortLinkTargetRequest, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> StopSharingResult:
    """Stop sharing one of your artifacts: its link goes dead immediately, and GAIA
    attaches no new one until you share it again. Idempotent; says whether a link died."""
    log.set(
        user={"id": user.user_id},
        short_link={"operation": "stop_sharing", "target_type": body.target_type.value},
    )
    revoked = await stop_sharing(user.user_id, body.target_type, body.target_id)
    log.set(short_link={"revoked": revoked})
    return StopSharingResult(revoked=revoked)


@router.get("/{slug}", responses=_DENIALS)
@limiter.limit(RESOLVE_RATE_LIMIT)
async def resolve_short_link_route(
    request: Request,
    response: Response,
    slug: str,
    user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)],
) -> LinkEnvelope:
    """Open a link: its target's public view and any framed content, or the denial the viewer sees."""
    log.set(short_link={"operation": "resolve", "slug_hash": hash_short_link_slug(slug)})
    response.headers["Cache-Control"] = _NO_STORE  # pragma: no mutate — case-insensitive name
    response.headers["Vary"] = "Cookie"
    envelope = await resolve(await _looked_up(request, slug), _viewer(request, user))
    log.set(short_link={"target_type": envelope.target_type.value, "access": envelope.access.value})
    return envelope


@router.get("/{slug}/meta")
@limiter.limit(RESOLVE_RATE_LIMIT)
async def link_preview_meta_route(
    request: Request, response: Response, slug: str
) -> LinkPreviewMeta:
    """What a chat preview or the page's metadata may show for a link, for anyone. No auth."""
    log.set(short_link={"operation": "meta", "slug_hash": hash_short_link_slug(slug)})
    meta = await preview_meta(await _looked_up(request, slug))
    response.headers["Cache-Control"] = _META_CACHE if meta.live else _DEAD_META_CACHE
    return meta


@router.patch("/{slug}", responses=error_responses({404: "Link not found"}))
@limiter.limit(MINT_RATE_LIMIT, key_func=_user_key)
async def update_link_settings_route(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    slug: str,
    body: LinkSettingsUpdate,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ShortLinkResponse:
    """Change who one of your live links opens for, or when it expires."""
    log.set(user={"id": user.user_id})
    log.set(short_link={"operation": "update_settings", "slug_hash": hash_short_link_slug(slug)})
    return link_response(await update_settings(user.user_id, slug, body))


@router.post("/{slug}/rotate", responses=error_responses({404: "Link not found"}))
@limiter.limit(MINT_RATE_LIMIT, key_func=_user_key)
async def rotate_link_route(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    slug: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ShortLinkResponse:
    """Replace one of your live links with a new URL; the old one stops opening at once."""
    log.set(user={"id": user.user_id})
    log.set(short_link={"operation": "rotate", "slug_hash": hash_short_link_slug(slug)})
    return link_response(await rotate(user.user_id, slug))


@router.post("/{slug}/opened", status_code=status.HTTP_204_NO_CONTENT, responses=_DENIALS)
async def record_open_route(
    request: Request,
    slug: str,
    user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)],
) -> None:
    """Count the link as opened, sent by the viewer's browser once the page shows.

    Not the resolve: public pages resolve during SSR, where neither the viewer's
    session nor their browser is visible, and unfurl bots resolve them too.
    """
    log.set(short_link={"operation": "opened", "slug_hash": hash_short_link_slug(slug)})
    kind = await record_open(await get_link(slug), _viewer(request, user))
    log.set(short_link={"viewer_kind": kind.value})


@router.post("/{slug}/content-token", responses=_DENIALS)
@limiter.limit(CONTENT_URL_RATE_LIMIT, key_func=_slug_key)
async def content_token_route(
    request: Request,
    slug: str,
    user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)],
) -> ContentTokenResponse:
    """Sign a short-lived URL that loads the link's file from the content origin, after the link's access check."""
    log.set(short_link={"operation": "content_token", "slug_hash": hash_short_link_slug(slug)})
    link = await openable_link(await get_link(slug), _viewer(request, user))
    content = framed_content(link.snapshot, link.access) if active_link_content() else None
    if content is None:
        raise LinkDeniedError.for_denial(LinkDenial.NOT_FOUND)
    url, expires_at = issue_content_url(link, content.content_id, datetime.now(UTC))
    return ContentTokenResponse(content_url=url, expires_at=expires_at)


@router.get(
    "/{slug}/download",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}, **_DENIALS},
)
async def download_link_file_route(
    request: Request,
    slug: str,
    user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)],
) -> Response:
    """Save the file behind a link: always an attachment, so it never renders on this origin."""
    log.set(short_link={"operation": "download", "slug_hash": hash_short_link_slug(slug)})
    link = await openable_link(await get_link(slug), _viewer(request, user))
    snapshot = link.snapshot
    if snapshot is None or snapshot.content_id is None or not servable(snapshot, link.access):
        raise LinkDeniedError.for_denial(LinkDenial.NOT_FOUND)
    return download_response(await read_snapshot(link.user_id, snapshot.content_id), snapshot)


@router.post("/{slug}/report", status_code=status.HTTP_204_NO_CONTENT, responses=_DENIALS)
@limiter.limit(REPORT_RATE_LIMIT)
async def report_link_route(
    request: Request,
    slug: str,
    body: LinkReportRequest,
    user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)],
) -> None:
    """Report a link that breaks GAIA's terms; enough distinct reporters suspend it."""
    log.set(short_link={"operation": "report", "slug_hash": hash_short_link_slug(slug)})
    viewer = _viewer(request, user)
    # A signed-out reporter proves they are human on GAIA Cloud; a signed-in one is their account.
    if viewer.user_id is None and settings.deployment.gaia_support:
        await verify_turnstile_token(body.turnstile_token or "", viewer.ip)
    link = await openable_link(await get_link(slug), viewer)
    # One report per account, or per address for a signed-out reporter, however their browser varies.
    reporter_key = viewer.user_id or hash_link_viewer(viewer.ip, "")
    await abuse.report(link, body.reason, reporter_key, signed_in=viewer.user_id is not None)


@router.get(
    "/{slug}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, **_DENIALS},
)
async def get_short_link_pdf_route(
    request: Request,
    slug: str,
    user: Annotated[AuthenticatedUser | None, Depends(get_optional_user)],
) -> Response:
    """The artifact behind a link as an A4 PDF, for whoever the link opens for."""
    log.set(operation="pdf", short_link={"slug_hash": hash_short_link_slug(slug)})
    link = await openable_link(
        await get_link(slug), _viewer(request, user), ShortLinkTargetType.OPENUI_ARTIFACT
    )
    artifact, pdf = await owner_artifact_pdf(link.user_id, link.target_id)
    log.set(artifact={"kind": artifact.kind.value, "pdf_bytes": len(pdf)})
    return Response(pdf, media_type="application/pdf", headers=pdf_download_headers(artifact))
