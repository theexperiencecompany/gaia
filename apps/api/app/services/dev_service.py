"""Dev-only identity + seeding service.

Bootstraps users and sample data for agent-driven end-to-end testing. Every
write reuses the real production path (``store_user_info``, ``create_todo``,
``create_conversation_service``, ``PlatformLinkService.link_account``) so seeded
shapes can never drift from what the app actually produces. Mounted only in
development behind the auth bypass — see ``create_app``.
"""

import asyncio
from typing import cast

from fastapi import UploadFile

from app.constants.auth import DEV_USER_MISSING_HINT
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationModel, ConversationSource
from app.models.files_models import FileDocument
from app.models.todo_models import TodoModel
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    UserDocument,
)
from app.schemas.dev_schemas import (
    DeleteDevUserResponse,
    DevDeletedCounts,
    SeedDevDataResponse,
)
from app.services.conversation_service import create_conversation_service
from app.services.files import FileService
from app.services.oauth.oauth_service import store_user_info
from app.services.platform_link_service import Platform, PlatformLinkService
from app.services.todos.todo_service import create_todo
from app.services.triggers.subscription_service import teardown_subscriptions
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


async def mint_dev_user(email: str, name: str | None = None) -> UserDocument:
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
    return user_doc


async def attach_dev_file(
    email: str,
    conversation_id: str,
    file: UploadFile,
    content_length: int | None,
) -> FileDocument:
    """Ingest a file for a dev user's conversation through the real upload path.

    Calls the same ``FileService.upload`` the production ``POST /api/v1/upload``
    handler calls, so extraction (anydoc/pdf_inspector/vision), summarization,
    Mongo metadata and the ChromaDB index are the shipped ones, not a copy. The
    only production step skipped is the conversation-ownership check, which
    guards against one user polluting another's session tree — meaningless here,
    where the caller names the user and the router 404s outside development.

    Pass the ``conversation_id`` that the subsequent ``POST /api/v1/dev/executor``
    run uses: ``prepare_executor_execution`` reconstructs the conversation's
    uploads from that id alone.
    """
    user = await require_dev_user(email)
    # CacheInvalidator erases the wrapped function's return type; FileService.upload
    # is declared -> FileDocument, so this is correct by construction.
    document = cast(
        FileDocument,
        await FileService.upload(
            file=file,
            user_id=user.id,
            conversation_id=conversation_id,
            content_length=content_length,
        ),
    )
    log.info(
        f"{LogTag.DEV} attached file to dev conversation",
        email=email,
        user_id=user.id,
        conversation_id=conversation_id,
        file_id=document.file_id,
        content_type=document.type,
        extracted=document.page_wise_summary is not None,
    )
    return document


async def seed_dev_data(
    email: str,
    todos: int,
    conversations: int,
    platform_links: list[str],
) -> SeedDevDataResponse:
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
        ),
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
    return SeedDevDataResponse(
        email=email,
        user_id=user_id,
        todos_created=todos,
        conversations_created=conversations,
        platforms_linked=platform_links,
        platform_user_ids=platform_user_ids,
    )


async def delete_dev_user(email: str) -> DeleteDevUserResponse:
    """Remove a dev user and the todos/conversations/projects it owns."""
    user = await require_dev_user(email)
    user_id = user.id

    # Same rule as every other delete path: unregister while the documents still
    # name their Composio triggers. Dev accounts are exactly where orphaned
    # triggers accumulate unnoticed, because nobody is watching that Composio org.
    for todo in await todo_repository.list_for_user(user_id):
        if todo.trigger_subscriptions and todo.id:
            await teardown_subscriptions(todo.id, user_id, reason="user_deleted")

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
    return DeleteDevUserResponse(
        email=email,
        user_id=user_id,
        deleted=DevDeletedCounts(
            todos=todos_deleted,
            conversations=conversations_deleted,
            projects=projects_deleted,
            user=user_deleted,
        ),
    )
