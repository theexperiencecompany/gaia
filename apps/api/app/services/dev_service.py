"""Dev-only identity + seeding service.

Bootstraps users and sample data for agent-driven end-to-end testing. Every
write reuses the real production path (``store_user_info``, ``create_todo``,
``create_conversation_service``, ``PlatformLinkService.link_account``) so seeded
shapes can never drift from what the app actually produces. Mounted only in
development behind the auth bypass — see ``create_app``.
"""

import asyncio

from app.constants.auth import DEV_USER_MISSING_HINT
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationModel, ConversationSource
from app.models.todo_models import TodoModel
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    UserDocument,
)
from app.services.conversation_service import create_conversation_service
from app.services.oauth.oauth_service import store_user_info
from app.services.platform_link_service import Platform, PlatformLinkService
from app.services.todos.todo_service import create_todo
from app.utils.errors import create_error
from shared.py.wide_events import log


async def require_dev_user(email: str) -> UserDocument:
    """Load a user by email or raise a 404 that points at the mint endpoint."""
    user = await user_repository.get_by_email(email)
    if user is None:
        raise create_error(
            message=f"No dev user exists for {email!r}",
            why="the user has not been minted yet",
            fix=DEV_USER_MISSING_HINT,
            status_code=404,
        )
    return user


async def mint_dev_user(email: str, name: str | None = None) -> dict:
    """Idempotently find-or-create a dev user via the real signup path."""
    resolved_name = name or email.split("@", 1)[0]
    user_id, is_new = await store_user_info(
        name=resolved_name,
        email=email,
        picture_url=None,
        # Same stored shape as real signup, but a minted dev user must never
        # send a welcome email, join the marketing audience, or hit PostHog.
        external_side_effects=False,
    )
    log.info(f"{LogTag.DEV} minted dev user", email=email, user_id=str(user_id), is_new=is_new)
    user_doc = await user_repository.get(str(user_id))
    if user_doc is None:
        raise create_error(
            message="Dev user creation did not persist",
            why="store_user_info returned an id with no matching document",
            status_code=500,
        )
    return user_doc.model_dump(mode="json")


async def seed_dev_data(
    email: str,
    todos: int,
    conversations: int,
    platform_links: list[str],
) -> dict:
    """Create deterministic sample data for an existing dev user via real services."""
    for platform in platform_links:
        if not Platform.is_valid(platform):
            raise create_error(
                message=f"Unknown platform {platform!r}",
                why="not one of the supported bot platforms",
                fix=f"use one of: {', '.join(Platform.values())}",
                status_code=400,
            )

    user = await require_dev_user(email)
    user_id = user.id

    # A seeded account must be ready to use: mark onboarding complete the same
    # way complete_onboarding() does (same atomic $exists gate, terminal phase,
    # NO_GMAIL bio placeholder), minus its background personalization jobs —
    # seeding must not depend on Redis workers. Never clobbers real onboarding.
    await user_repository.complete_onboarding(
        user_id,
        phase=OnboardingPhase.COMPLETED,
        bio_status=BioStatus.NO_GMAIL,
        pipeline_mode="full",
        preferences=OnboardingPreferences(
            profession="Developer",
            response_style="casual",
            custom_instructions=None,
        ).model_dump(),
    )

    # The seeded platform_user_id is part of the seed CONTRACT (harness clients
    # inject messages as it) — it is returned in the response, never re-derived
    # by consumers.
    platform_user_ids = {platform: f"dev-{platform}-{user_id}" for platform in platform_links}

    await asyncio.gather(
        *(create_todo(TodoModel(title=f"Sample todo {i + 1}"), user_id) for i in range(todos)),
        *(
            create_conversation_service(
                ConversationModel(
                    conversation_id=f"dev-seed-{user_id}-{i + 1}",
                    description=f"Sample conversation {i + 1}",
                    source=ConversationSource.WEB,
                ),
                {"user_id": user_id},
            )
            for i in range(conversations)
        ),
        *(
            PlatformLinkService.link_account(
                user_id=user_id,
                platform=platform,
                platform_user_id=platform_user_id,
                profile={
                    "username": f"dev_{platform}",
                    "display_name": user.name or email,
                },
            )
            for platform, platform_user_id in platform_user_ids.items()
        ),
    )

    log.info(
        f"{LogTag.DEV} seeded dev data",
        email=email,
        user_id=user_id,
        todos=todos,
        conversations=conversations,
        platforms=platform_links,
    )
    return {
        "email": email,
        "user_id": user_id,
        "todos_created": todos,
        "conversations_created": conversations,
        "platforms_linked": platform_links,
        "platform_user_ids": platform_user_ids,
    }


async def delete_dev_user(email: str) -> dict:
    """Remove a dev user and the todos/conversations/projects it owns."""
    user = await require_dev_user(email)
    user_id = user.id

    todos_deleted = await todo_repository.delete_all_for_user(user_id)
    conversations_deleted = len(await conversation_repository.delete_all_for_user(user_id))
    projects_deleted = await project_repository.delete_all_for_user(user_id)
    user_deleted = int(await user_repository.delete(user_id))

    log.info(
        f"{LogTag.DEV} deleted dev user",
        email=email,
        user_id=user_id,
        todos=todos_deleted,
        conversations=conversations_deleted,
        projects=projects_deleted,
    )
    return {
        "email": email,
        "user_id": user_id,
        "deleted": {
            "todos": todos_deleted,
            "conversations": conversations_deleted,
            "projects": projects_deleted,
            "user": user_deleted,
        },
    }
