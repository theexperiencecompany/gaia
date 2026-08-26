"""
GAIA API v1 package.

This package contains the API routes and dependencies for version 1 of the GAIA API.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    approvals,
    auth_local,
    blog,
    bot,
    calendar,
    chat,
    conversations,
    desktop,
    device,
    device_ws,
    feedback,
    file,
    image,
    mail,
    mcp,
    mcp_proxy,
    memory,
    models,
    notes,
    notification,
    oauth,
    onboarding,
    payments,
    platform_auth,
    platform_links,
    reminders,
    search,
    sessions,
    setup,
    skills,
    support,
    todos,
    tools,
    triggers,
    usage,
    user,
    voice,
    webhook_composio,
    websocket,
    workflows,
)
from app.api.v1.endpoints.integrations import router as integrations_router
from app.config.settings import settings

router = APIRouter()

router.include_router(voice.router, tags=["Voice"])
router.include_router(chat.router, tags=["Chat"])
router.include_router(desktop.router)
router.include_router(device.router)
router.include_router(device_ws.router)
router.include_router(approvals.router, tags=["Approvals"])
router.include_router(conversations.router, tags=["Conversations"])
router.include_router(sessions.router)
router.include_router(feedback.router, tags=["Feedback"])
router.include_router(image.router, tags=["Image"])
router.include_router(search.router, tags=["Search"])
router.include_router(calendar.router, tags=["Calendar"])
router.include_router(notes.router, tags=["Notes/Memories"])
router.include_router(memory.router, tags=["Memory"], prefix="/memory")
router.include_router(oauth.router, prefix="/oauth", tags=["OAuth"])
# Self-host-only surfaces (see _raise_if_selfhost_feature_in_production):
# under AUTH_MODE=workos these routers are not mounted at all, so hosted
# deployments expose no password-registration endpoint and no unauthenticated
# instance-posture probe. The in-module 404 guards in setup.py are a second
# layer on top of this mount gate.
#
# /setup/status is not unconditionally public: the middleware's conditional
# exclude block appends "/api/v1/setup/status" to exclude_paths only when
# settings.AUTH_MODE == "local", never in workos mode.
if settings.AUTH_MODE == "local":
    router.include_router(auth_local.router, prefix="/auth", tags=["Auth"])
if settings.AUTH_MODE == "local" or settings.ENV == "selfhost":
    router.include_router(setup.router, prefix="/setup", tags=["Setup"])
router.include_router(integrations_router, prefix="/integrations", tags=["Integrations"])
router.include_router(mcp.router, prefix="/mcp", tags=["MCP"])
router.include_router(mcp_proxy.router, prefix="/mcp", tags=["MCP"])
router.include_router(onboarding.router, prefix="/onboarding", tags=["Onboarding"])
router.include_router(user.router, prefix="/user", tags=["User"])
router.include_router(mail.router, tags=["Mail"])
router.include_router(blog.router, tags=["Blog"])
router.include_router(file.router, tags=["File"])
router.include_router(notification.router, tags=["Notification"])
router.include_router(websocket.router, tags=["WebSocket"])
router.include_router(webhook_composio.router, tags=["Composio Webhook"])
router.include_router(todos.router, tags=["Todos"])
router.include_router(workflows.router, tags=["Workflows"])
router.include_router(triggers.router, tags=["Triggers"])
router.include_router(reminders.router, tags=["Reminders"])
router.include_router(skills.router, tags=["Skills"])
router.include_router(support.router, tags=["Support"])
router.include_router(payments.router, prefix="/payments", tags=["Payments"])
router.include_router(usage.router, tags=["Usage"])
router.include_router(tools.router, tags=["Tools"])
router.include_router(models.router, tags=["Models"])
router.include_router(bot.router, prefix="/bot", tags=["Bot"])
router.include_router(platform_auth.router, prefix="/platform-auth", tags=["Platform Auth"])
router.include_router(platform_links.router, prefix="/platform-links", tags=["Platform Links"])
