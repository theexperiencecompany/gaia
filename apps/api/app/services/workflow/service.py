"""
Clean workflow service for GAIA workflow system.
Handles CRUD operations and execution coordination.
"""

import secrets
from typing import Any
import uuid

from pymongo.errors import DuplicateKeyError

from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.workflows import workflow_repository
from app.decorators.caching import Cacheable
from app.models.workflow_models import (
    CreateWorkflowRequest,
    DeactivationReason,
    PublicWorkflowRow,
    PublicWorkflowsResponse,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowDocument,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
    WorkflowUpdate,
    WorkflowWithIntegrations,
)
from app.services.workflow.integration_requirements import (
    build_integration_refs,
    compute_integration_refs,
    compute_missing_integrations,
    compute_required_integrations,
)
from app.services.workflow.trigger_service import TriggerService
from app.utils.creator import (
    SYSTEM_CREATOR_NAME,
    format_creator,
)
from app.utils.exceptions import TriggerRegistrationError
from app.utils.trigger_utils import get_integration_for_trigger
from app.utils.workflow_utils import (
    filter_existing_integration_ids,
    handle_workflow_error,
)
from shared.py.utils.slugify import slugify
from shared.py.wide_events import log

from .generation_service import WorkflowGenerationService
from .queue_service import WorkflowQueueService
from .scheduler import workflow_scheduler
from .validators import WorkflowValidator

_SLUG_SUFFIX_LEN = 6
_SLUG_MAX_RETRIES = 5


def _slug_suffix() -> str:
    return secrets.token_hex(_SLUG_SUFFIX_LEN // 2)


async def generate_unique_workflow_slug(title: str, exclude_id: str | None = None) -> str:
    """Generate a slug from the title, suffixed with a short random hex token.

    The 6-char suffix makes collisions vanishingly unlikely (1 in 16M per public
    workflow). The DB has a partial-unique index on slug for is_public=true,
    so a true collision throws DuplicateKeyError at write time and the caller
    is expected to retry.
    """
    base = slugify(title) or "workflow"

    for _ in range(_SLUG_MAX_RETRIES):
        candidate = f"{base}-{_slug_suffix()}"
        conflict = await workflow_repository.find_public_slug_conflict(
            candidate, exclude_id=exclude_id
        )
        if conflict is None:
            return candidate

    raise RuntimeError(
        f"Failed to find unique slug for '{title}' after {_SLUG_MAX_RETRIES} retries"
    )


async def ensure_public_workflow_slug(workflow: WorkflowDocument) -> None:
    """Lazily backfill a slug on a legacy public workflow that's missing one.

    Mutates ``workflow.slug`` in place. No-op when the workflow is private or
    already has a slug. Persists the new slug via the repository.
    """
    if not workflow.is_public or workflow.slug:
        return

    for _ in range(_SLUG_MAX_RETRIES):
        slug = await generate_unique_workflow_slug(workflow.title, exclude_id=workflow.id)
        try:
            result = await workflow_repository.backfill_public_slug(workflow.id, slug)
            if result is not None:
                workflow.slug = result.slug
            else:
                # Someone else won the race — re-read the persisted slug.
                fresh = await workflow_repository.get(workflow.id)
                if fresh and fresh.slug:
                    workflow.slug = fresh.slug
            return
        except DuplicateKeyError:
            continue


class WorkflowService:
    """Service class for workflow operations."""

    @staticmethod
    async def _register_integration_triggers(
        workflow_id: str,
        user_id: str,
        trigger_config: TriggerConfig,
    ) -> tuple[list[str], bool]:
        """Register Composio triggers for integration-based workflows.

        Returns (trigger_ids, integration_connected). Callers decide activation
        from the connected flag, NOT from trigger_ids: account-level handlers
        (e.g. Gmail) legitimately return [] on success.
        """
        # Only handle integration type triggers
        if trigger_config.type != TriggerType.INTEGRATION:
            log.debug(
                f"{LogTag.WORKFLOW} Skipping trigger registration: trigger type is not INTEGRATION",
                type=trigger_config.type,
            )
            return [], True

        trigger_name = trigger_config.trigger_name
        if not trigger_name:
            raise TriggerRegistrationError(
                "Integration trigger requires 'trigger_name' but none was provided. "
                "This indicates a frontend configuration error.",
                trigger_name="unknown",
            )

        # Imported lazily to avoid a circular import via system_workflows.
        # Deferred import: lazy to break the circular import routed via system_workflows
        from app.services.oauth.oauth_service import (  # noqa: PLC0415 -- deferred
            check_integration_status,
        )

        integration_id = get_integration_for_trigger(trigger_name)
        if integration_id:
            connected = await check_integration_status(integration_id, user_id)
            if not connected:
                log.info(
                    f"{LogTag.WORKFLOW} Skipping trigger registration: integration not connected for user",
                    integration_id=integration_id,
                    user_id=user_id,
                )
                return [], False

        trigger_ids = await TriggerService.register_triggers(
            user_id=user_id,
            owner_id=workflow_id,
            trigger_name=trigger_name,
            trigger_config=trigger_config,
            raise_on_failure=True,
        )

        return trigger_ids, True

    @staticmethod
    async def create_workflow(
        request: CreateWorkflowRequest,
        user_id: str,
        user_timezone: str | None = None,
        is_todo_workflow: bool = False,
        source_todo_id: str | None = None,
    ) -> Workflow:
        """Create a new workflow with automatic timezone population.

        Uses Saga pattern for atomicity:
        1. Create workflow in pending state (activated=False)
        2. Register Composio triggers (if needed)
        3. Activate workflow with trigger IDs
        4. On failure: rollback (delete workflow)
        """
        workflow_id: str | None = None
        trigger_ids: list[str] = []

        # A system workflow is one-per-user, keyed by system_workflow_key. The user
        # can reach the same definition from two directions — connecting the
        # integration (the provisioner) or adding its explore card — so hand back
        # the one they already have instead of creating a near-duplicate.
        if request.system_workflow_key:
            existing = await workflow_repository.find_system_workflow(
                user_id, request.system_workflow_key
            )
            if existing:
                log.info(
                    f"{LogTag.WORKFLOW} System workflow already exists for user, returning it",
                    system_workflow_key=request.system_workflow_key,
                    workflow={"id": existing.id},
                )
                return existing

        try:
            # Calculate next_run for scheduled workflows with timezone awareness
            trigger_config = request.trigger_config

            # Automatically populate timezone field
            if trigger_config.type == "schedule":
                # The schedule's own timezone is authoritative — it is the wall-clock
                # context the cron was built against in the UI. Fall back to the
                # request-resolved user timezone only when the schedule didn't carry
                # one (e.g. the agent-created path), then UTC.
                timezone_to_use = trigger_config.timezone or user_timezone or "UTC"
                log.info(
                    f"{LogTag.WORKFLOW} Creating workflow with timezone",
                    timezone_to_use=timezone_to_use,
                )
                trigger_config.timezone = timezone_to_use
                if trigger_config.cron_expression:
                    trigger_config.update_next_run(user_timezone=timezone_to_use)
                log.set(
                    trigger_type=str(trigger_config.type),
                    trigger_name=trigger_config.trigger_name,
                    cron_expression=trigger_config.cron_expression,
                    trigger_timezone=trigger_config.timezone,
                    next_run_utc=trigger_config.next_run.isoformat()
                    if trigger_config.next_run
                    else None,
                )
            else:
                log.set(
                    trigger_type=str(trigger_config.type),
                    trigger_name=trigger_config.trigger_name,
                )

            # Use provided steps or initialize empty list for generation
            workflow_steps = request.steps or []

            # Step 1: Create workflow in PENDING state (activated=False). Keep
            # trigger_config.enabled in lockstep with activated (the single liveness
            # field) — a pending workflow is not live.
            trigger_config.enabled = False
            workflow = Workflow(
                title=request.title,
                description=request.description or "",
                prompt=request.prompt,
                icon=request.icon,
                icon_color=request.icon_color,
                steps=workflow_steps,
                trigger_config=trigger_config,
                activated=False,  # Start in pending state
                notify_on_completion=request.notify_on_completion,
                user_id=user_id,
                is_todo_workflow=is_todo_workflow,
                source_todo_id=source_todo_id,
                is_system_workflow=request.is_system_workflow,
                source_integration=request.source_integration,
                system_workflow_key=request.system_workflow_key,
                integration_ids=await filter_existing_integration_ids(request.integration_ids),
            )

            if workflow.is_public and not workflow.slug:
                workflow.slug = await generate_unique_workflow_slug(workflow.title)

            # Persist through the repository (python mode keeps datetimes native so
            # the scheduler's `scheduled_at: {"$lte": now}` scan matches; it raises
            # if the insert can't be read back). The local ``workflow`` stays the
            # response object the saga mutates and returns.
            await workflow_repository.create(WorkflowDocument(**workflow.model_dump()))

            workflow_id = workflow.id
            log.set(
                workflow={
                    "id": workflow_id,
                    "status": "pending",
                    "title": workflow.title,
                    "trigger_type": str(trigger_config.type),
                    "step_count": len(workflow_steps),
                }
            )
            log.info(
                f"{LogTag.WORKFLOW} Created pending workflow for user",
                workflow_id=workflow_id,
                user_id=user_id,
            )

            # Store in ChromaDB for semantic search (non-critical, don't fail on error)
            try:
                chroma = await ChromaClient.get_langchain_client(
                    "workflows", create_if_not_exists=True
                )
                content = (
                    f"{workflow.title} | "
                    f"{workflow.description or ''} | "
                    f"{workflow.prompt or ''} | "
                    f"{trigger_config.type}"
                )
                chroma.add_texts(
                    texts=[content],
                    metadatas=[
                        {
                            "user_id": user_id,
                            "workflow_id": str(workflow.id),
                            "trigger_type": trigger_config.type,
                        }
                    ],
                    ids=[str(workflow.id)],
                )
            except Exception as e:
                log.warning(
                    f"{LogTag.WORKFLOW} Failed to store workflow in ChromaDB",
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )

            if not workflow.id:
                raise ValueError("Workflow ID is required")

            # Step 2: Register integration triggers (this can raise TriggerRegistrationError)
            # The handlers will rollback their own partial triggers on failure.
            (
                trigger_ids,
                integration_connected,
            ) = await WorkflowService._register_integration_triggers(
                workflow_id=workflow.id,
                user_id=user_id,
                trigger_config=trigger_config,
            )

            # Steps supplied by the caller (adding an explore card) skip generation,
            # so the generation-time gate never runs on them. Apply the same rule
            # here: a workflow whose steps need apps the user hasn't connected is
            # created inactive rather than switched on and failing on first run.
            missing_step_integrations = await compute_missing_integrations(
                compute_required_integrations(workflow.steps), user_id
            )
            if missing_step_integrations:
                log.info(
                    f"{LogTag.WORKFLOW} Workflow created inactive — steps need unconnected integrations",
                    id=workflow.id,
                    missing_integrations=[m.id for m in missing_step_integrations],
                )

            integration_skipped = bool(missing_step_integrations) or (
                trigger_config.type == TriggerType.INTEGRATION and not integration_connected
            )

            if integration_skipped:
                log.set(
                    workflow={
                        "id": workflow.id,
                        "status": "pending_connection",
                        "title": workflow.title,
                        "trigger_type": str(trigger_config.type),
                        "step_count": len(workflow_steps),
                    }
                )
                log.info(
                    f"{LogTag.WORKFLOW} Workflow created inactive — integration for trigger not connected",
                    id=workflow.id,
                    trigger_name=trigger_config.trigger_name,
                )
            else:
                # Step 3: Activate workflow and store trigger IDs. enabled mirrors
                # activated; keyed by id alone (the create saga owns the row).
                await workflow_repository.mark_activated_with_triggers(
                    workflow.id, trigger_ids=trigger_ids
                )

                # Update local workflow object
                workflow.activated = True
                workflow.trigger_config.enabled = True
                if trigger_ids:
                    workflow.trigger_config.composio_trigger_ids = trigger_ids

                log.set(
                    workflow={
                        "id": workflow.id,
                        "status": "activated",
                        "title": workflow.title,
                        "trigger_type": str(trigger_config.type),
                        "step_count": len(workflow_steps),
                    }
                )
                log.info(
                    f"{LogTag.WORKFLOW} Activated workflow with triggers",
                    id=workflow.id,
                    trigger_ids_count=len(trigger_ids),
                )

                # Schedule the workflow if it's a scheduled type (activated here).
                if trigger_config.type == "schedule" and trigger_config.next_run:
                    await workflow_scheduler.schedule_workflow_execution(
                        workflow.id,
                        trigger_config.next_run,
                        repeat=trigger_config.cron_expression,  # Enable recurring if cron exists
                    )

            # Generate steps only if not provided
            if not request.steps:
                # Generate steps
                if request.generate_immediately:
                    # Scoping comes from the workflow's own (already filtered)
                    # integration_ids, so the queued path grounds identically.
                    await WorkflowService._generate_workflow_steps(workflow.id, user_id)
                    # Fetch the updated workflow with generated steps
                    updated_workflow = await WorkflowService.get_workflow(workflow.id, user_id)
                    return updated_workflow or workflow
                success = await WorkflowQueueService.queue_workflow_generation(workflow.id, user_id)
                if not success:
                    log.error(
                        f"{LogTag.WORKFLOW} Failed to queue workflow generation for",
                        id=workflow.id,
                        user_id=user_id,
                    )
            else:
                log.info(
                    f"{LogTag.WORKFLOW} Workflow created with pre-existing steps, skipping generation",
                    id=workflow.id,
                    steps_count=len(request.steps),
                )

            return workflow

        except TriggerRegistrationError as e:
            # Saga compensation: delete the pending workflow
            log.error(
                f"{LogTag.WORKFLOW} Trigger registration failed, rolling back workflow",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            if workflow_id:
                try:
                    await workflow_repository.delete_for_user(workflow_id, user_id)
                    log.info(f"{LogTag.WORKFLOW} Rolled back workflow", workflow_id=workflow_id)
                except Exception as delete_error:
                    log.error(
                        f"{LogTag.WORKFLOW} Failed to rollback workflow",
                        workflow_id=workflow_id,
                        error=str(delete_error),
                        error_type=type(delete_error).__name__,
                        user_id=user_id,
                    )
            raise

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error creating workflow",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            # For other errors, still try to cleanup if workflow was created
            if workflow_id:
                try:
                    # Cleanup any triggers that were registered
                    if trigger_ids:
                        trigger_name = request.trigger_config.trigger_name
                        if trigger_name:
                            await TriggerService.unregister_triggers(
                                user_id, trigger_name, trigger_ids, workflow_id
                            )
                    await workflow_repository.delete_for_user(workflow_id, user_id)
                    log.info(
                        f"{LogTag.WORKFLOW} Rolled back workflow after error",
                        workflow_id=workflow_id,
                    )
                except Exception as cleanup_error:
                    log.error(
                        f"{LogTag.WORKFLOW} Cleanup failed for",
                        workflow_id=workflow_id,
                        error=str(cleanup_error),
                        error_type=type(cleanup_error).__name__,
                        user_id=user_id,
                    )
            raise

    @staticmethod
    async def get_workflow(workflow_id: str, user_id: str) -> WorkflowWithIntegrations | None:
        """Get a workflow by ID."""
        try:
            doc = await workflow_repository.get_for_user(workflow_id, user_id)
            if not doc:
                return None

            await ensure_public_workflow_slug(doc)

            workflow = WorkflowWithIntegrations(**doc.model_dump())
            await WorkflowService._enrich_integration_fields(workflow, user_id)
            return workflow

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error getting workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def list_workflows(
        user_id: str,
        exclude_todo_workflows: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[WorkflowWithIntegrations], int]:
        """List a user's workflows (newest first), excluding auto-generated todo workflows by default.

        Each workflow is enriched with its required/missing integrations using a
        single connection-status call. Returns ``(workflows, total)`` where
        ``total`` is the full match count ignoring ``limit``/``offset``. Pass
        ``limit=None`` to fetch every match.
        """
        try:
            docs = await workflow_repository.list_for_user(
                user_id,
                exclude_todo_workflows=exclude_todo_workflows,
                limit=limit,
                offset=offset,
            )

            # Only a paginated caller needs a separate count; an unpaginated fetch
            # already holds every match, so counting again is a wasted round-trip.
            total = (
                await workflow_repository.count_for_user(
                    user_id, exclude_todo_workflows=exclude_todo_workflows
                )
                if limit is not None
                else offset + len(docs)
            )

            workflows: list[WorkflowWithIntegrations] = [
                WorkflowWithIntegrations(**doc.model_dump()) for doc in docs
            ]

            # Enrich all workflows with integration fields in one status call.
            # Deferred import: oauth_service → provisioner → service is circular.
            if workflows:
                from app.services.oauth import oauth_service  # noqa: PLC0415 -- oauth

                status_map = await oauth_service.get_all_integrations_status(user_id)
                for workflow in workflows:
                    required = compute_required_integrations(
                        workflow.steps, workflow.trigger_config
                    )
                    (
                        workflow.required_integrations,
                        workflow.missing_integrations,
                    ) = build_integration_refs(required, status_map)

            log.debug(
                f"{LogTag.WORKFLOW} Retrieved / workflows for user",
                workflows_count=len(workflows),
                total=total,
                user_id=user_id,
            )
            return workflows, total

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error listing workflows for user",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    @staticmethod
    async def _enrich_integration_fields(workflow: WorkflowWithIntegrations, user_id: str) -> None:
        """Populate required_integrations and missing_integrations in-place."""
        (
            workflow.required_integrations,
            workflow.missing_integrations,
        ) = await compute_integration_refs(workflow.steps, workflow.trigger_config, user_id)

    @staticmethod
    async def update_workflow(
        workflow_id: str,
        request: UpdateWorkflowRequest,
        user_id: str,
        user_timezone: str | None = None,
    ) -> Workflow | None:
        """Update an existing workflow with timezone awareness.

        Uses Saga pattern for trigger updates: if new trigger registration fails,
        attempts to restore the old triggers (compensation).
        """
        # Track state for potential rollback. registered_trigger_ids is declared
        # out here because the compensation block in the `except` below reads it on
        # every failure path, including an update that never touched triggers.
        old_trigger_ids: list[str] = []
        old_trigger_name: str = ""
        registered_trigger_ids: list[str] | None = None

        try:
            # Get current workflow to check for trigger changes
            current_workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not current_workflow:
                return None

            # `model_fields_set` is what the client actually sent — the same
            # distinction `model_dump(exclude_unset=True)` encoded, kept on the
            # request so every value below is read as a typed attribute.
            provided = request.model_fields_set
            update = WorkflowUpdate(**request.model_dump(exclude_unset=True))

            # enabled mirrors activated (the single liveness field). Resolve the
            # effective activated value for this update and never trust a client-sent
            # `enabled` that disagrees with it.
            effective_activated = (
                current_workflow.activated if request.activated is None else request.activated
            )

            # Handle trigger config changes
            if "trigger_config" in provided:
                if request.trigger_config is None:
                    raise ValueError("trigger_config cannot be null in a workflow update")
                # Copy so the update's timezone/next_run/enabled normalization can't
                # write back into the caller's request object.
                new_trigger_config = request.trigger_config.model_copy(deep=True)
                new_trigger_config.enabled = effective_activated

                # Automatically populate timezone field if it's a scheduled workflow.
                # The timezone chosen in the UI for this schedule wins. When the
                # update omits it, keep the zone the schedule already runs in —
                # editing a cron must not silently relocate the schedule to
                # whichever zone the request happened to resolve. Fall back to the
                # request-resolved user timezone only for a schedule that never had
                # one, then UTC.
                if new_trigger_config.type == "schedule":
                    timezone_to_use = (
                        new_trigger_config.timezone
                        or current_workflow.trigger_config.timezone
                        or user_timezone
                        or "UTC"
                    )
                    log.info(
                        f"{LogTag.WORKFLOW} Updating workflow with timezone",
                        workflow_id=workflow_id,
                        timezone_to_use=timezone_to_use,
                    )
                    new_trigger_config.timezone = timezone_to_use
                    if new_trigger_config.cron_expression:
                        new_trigger_config.update_next_run(user_timezone=timezone_to_use)

                # Check if we need to reschedule
                old_config = current_workflow.trigger_config
                schedule_changed = (
                    old_config.type != new_trigger_config.type
                    or old_config.cron_expression != new_trigger_config.cron_expression
                    or old_config.enabled != new_trigger_config.enabled
                )

                if schedule_changed and (
                    new_trigger_config.type == "schedule"
                    and new_trigger_config.enabled
                    and new_trigger_config.next_run
                    and effective_activated
                ):
                    # Reschedule to the new time/cron. When the workflow is instead
                    # being disabled or made non-scheduled, no teardown is needed:
                    # liveness is governed by `activated`, so a stale deferred fire
                    # is rejected by the claim gate.
                    await workflow_scheduler.reschedule_workflow(
                        workflow_id,
                        new_trigger_config.next_run,
                        repeat=new_trigger_config.cron_expression,
                    )

                # Handle trigger re-registration for integration triggers
                # Always delete and recreate triggers since Composio triggers can't be updated
                new_trigger_type = new_trigger_config.type
                is_integration_trigger = new_trigger_type == TriggerType.INTEGRATION

                if is_integration_trigger and current_workflow.activated:
                    old_trigger_name = old_config.trigger_name or ""
                    old_trigger_ids = old_config.composio_trigger_ids or []

                    # Register new triggers FIRST (old still active if this fails).
                    (
                        registered_trigger_ids,
                        _,
                    ) = await WorkflowService._register_integration_triggers(
                        workflow_id=workflow_id,
                        user_id=user_id,
                        trigger_config=new_trigger_config,
                    )

                    # Only unregister old triggers AFTER new ones are confirmed registered
                    if old_trigger_ids:
                        await TriggerService.unregister_triggers(
                            user_id, old_trigger_name, old_trigger_ids, workflow_id
                        )

                # Add new trigger IDs if triggers were registered
                if registered_trigger_ids is not None:
                    new_trigger_config.composio_trigger_ids = registered_trigger_ids

                # The repository dumps the update in python mode, so
                # trigger_config.next_run stays a native datetime (BSON date),
                # consistent with the create and re-arm paths.
                #
                # Rebuilt rather than assigned directly: model_copy carries the
                # request's __pydantic_fields_set__, and the repository's
                # model_dump(exclude_unset=True) propagates into the nested model
                # — so assigning it writes only the keys the client happened to
                # send, leaving the stored sub-document a different shape from
                # one written by the create path. Same values either way.
                update.trigger_config = TriggerConfig(**new_trigger_config.model_dump())

            # activated changed without a trigger_config rewrite: mirror the nested
            # `enabled` flag by rewriting the sub-document from the current config
            # (the typed update can't express a dotted `trigger_config.enabled` set;
            # the trigger_config branch above already syncs enabled in Case A).
            if "trigger_config" not in provided and "activated" in provided:
                synced = current_workflow.trigger_config
                synced.enabled = effective_activated
                # Rebuilt for the same reason as the branch above: a config read
                # back from a partially-written document carries only that
                # document's keys in its fields_set.
                update.trigger_config = TriggerConfig(**synced.model_dump())

            # An empty request (nothing set) is a bare touch, matching the prior
            # always-stamp-updated_at behavior — the typed update rejects an empty set.
            if not provided:
                await workflow_repository.touch(workflow_id, user_id)
                return await WorkflowService.get_workflow(workflow_id, user_id)

            try:
                updated = await workflow_repository.update_for_user(workflow_id, user_id, update)
            except Exception as db_err:
                # Compensate: unregister newly created triggers so they don't become orphaned
                if registered_trigger_ids is not None:
                    log.error(
                        f"{LogTag.WORKFLOW} MongoDB update failed for workflow ; unregistering newly registered triggers",
                        workflow_id=workflow_id,
                        registered_trigger_ids_count=len(registered_trigger_ids),
                        error=str(db_err),
                        error_type=type(db_err).__name__,
                        user_id=user_id,
                    )
                    await TriggerService.unregister_triggers(
                        user_id,
                        new_trigger_config.trigger_name or "",
                        registered_trigger_ids,
                        workflow_id,
                    )
                raise

            if updated is None:
                return None

            log.info(
                f"{LogTag.WORKFLOW} Updated workflow for user",
                workflow_id=workflow_id,
                user_id=user_id,
            )
            return await WorkflowService.get_workflow(workflow_id, user_id)

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error updating workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def delete_workflow(workflow_id: str, user_id: str) -> bool:
        """Delete a workflow."""
        try:
            # Get workflow first to access trigger config
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)

            # No schedule teardown needed: once the document is deleted, a deferred
            # ARQ fire finds no row to claim and is rejected by the claim gate.

            # Unregister Composio triggers if any (pass workflow_id for reference counting)
            if workflow:
                trigger_config = workflow.trigger_config
                trigger_ids = trigger_config.composio_trigger_ids or []
                if trigger_ids:
                    trigger_name = trigger_config.trigger_name
                    if trigger_name:
                        await TriggerService.unregister_triggers(
                            user_id, trigger_name, trigger_ids, workflow_id
                        )
                    else:
                        log.warning(
                            f"{LogTag.WORKFLOW} No trigger_name found for workflow, cannot unregister triggers",
                            workflow_id=workflow_id,
                            user_id=user_id,
                        )

            deleted = await workflow_repository.delete_for_user(workflow_id, user_id)

            if not deleted:
                return False

            log.set(workflow={"id": workflow_id, "status": "deleted"})
            log.info(
                f"{LogTag.WORKFLOW} Deleted workflow for user",
                workflow_id=workflow_id,
                user_id=user_id,
            )
            return True

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error deleting workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def execute_workflow(
        workflow_id: str, request: WorkflowExecutionRequest, user_id: str
    ) -> WorkflowExecutionResponse:
        """Execute a workflow."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            # Use simple validator for execution check
            WorkflowValidator.validate_for_execution(workflow)

            # Update last execution timestamp
            touched = await workflow_repository.touch(workflow_id, user_id)
            if not touched:
                raise ValueError(f"Failed to update workflow {workflow_id}")

            execution_id = f"exec_{workflow_id}_{uuid.uuid4().hex[:8]}"

            success = await WorkflowQueueService.queue_workflow_execution(
                workflow_id, user_id, request.context
            )
            if not success:
                raise ValueError(f"Failed to queue workflow execution for {workflow_id}")

            log.set(
                workflow={
                    "id": workflow_id,
                    "status": "executing",
                    "execution_id": execution_id,
                    "trigger_type": str(workflow.trigger_config.type)
                    if workflow.trigger_config
                    else None,
                    "step_count": len(workflow.steps),
                    "title": workflow.title,
                }
            )
            log.info(
                f"{LogTag.WORKFLOW} Started execution for workflow",
                execution_id=execution_id,
                workflow_id=workflow_id,
            )

            return WorkflowExecutionResponse(
                execution_id=execution_id,
                message="Workflow execution started",
            )

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error executing workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def get_workflow_status(workflow_id: str, user_id: str) -> WorkflowStatusResponse:
        """Get the current status of a workflow."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            total_steps = len(workflow.steps)
            progress_percentage = 0.0

            if total_steps > 0:
                progress_percentage = 0

            return WorkflowStatusResponse(
                workflow_id=workflow_id,
                activated=workflow.activated,
                current_step_index=workflow.current_step_index,
                total_steps=total_steps,
                progress_percentage=progress_percentage,
                last_updated=workflow.updated_at,
                error_message=workflow.error_message,
                logs=workflow.execution_logs,
            )

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error getting workflow status",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def activate_workflow(
        workflow_id: str, user_id: str, user_timezone: str | None = None
    ) -> Workflow | None:
        """Activate a workflow (enable its trigger).

        Uses Saga pattern: if trigger registration fails, the workflow remains inactive.
        """
        trigger_ids: list[str] = []

        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return None

            # Refuse activation when the workflow's steps need integrations the
            # user hasn't connected — an enabled workflow that can't run is
            # misleading. (Surfaced as a 400 by the activate endpoint.)
            required = compute_required_integrations(workflow.steps)
            missing = await compute_missing_integrations(required, user_id)
            if missing:
                names = ", ".join(ref.name for ref in missing)
                raise ValueError(f"Connect {names} to enable this workflow.")

            # 1. Register Composio triggers FIRST (can raise TriggerRegistrationError)
            trigger_config = workflow.trigger_config
            trigger_type = trigger_config.type

            # Recompute next_run from the cron so a stale/frozen schedule time (e.g.
            # left over from a prior deactivation) cannot carry over on reactivation.
            # The schedule's stored timezone is authoritative; the activating
            # request's tz is only a fallback for legacy rows that never stored one.
            if trigger_type == TriggerType.SCHEDULE and trigger_config.cron_expression:
                trigger_config.update_next_run(
                    user_timezone=trigger_config.timezone or user_timezone
                )

            # Refuse activation up front: registration would otherwise silently
            # no-op for a disconnected integration, confusing the user.
            if trigger_type == TriggerType.INTEGRATION and trigger_config.trigger_name:
                from app.services.oauth.oauth_service import (  # noqa: PLC0415 -- breaks circular chain: oauth_service -> provisioner -> this service
                    check_integration_status,
                )

                integration_id = get_integration_for_trigger(trigger_config.trigger_name)
                if integration_id and not await check_integration_status(integration_id, user_id):
                    raise TriggerRegistrationError(
                        f"Connect {integration_id} before activating this workflow.",
                        trigger_name=trigger_config.trigger_name,
                    )

            trigger_ids, _ = await WorkflowService._register_integration_triggers(
                workflow_id=workflow_id,
                user_id=user_id,
                trigger_config=trigger_config,
            )

            if trigger_ids:
                log.info(
                    f"{LogTag.WORKFLOW} Registered Composio triggers for workflow",
                    trigger_ids_count=len(trigger_ids),
                    workflow_id=workflow_id,
                )

            # Get trigger_name for potential rollback
            trigger_name = trigger_config.trigger_name

            # 2. Activate: set liveness (activated) and re-arm run-state to idle
            # (status=scheduled) with the freshly recomputed next_run.
            activated = await workflow_repository.activate(
                workflow_id,
                user_id,
                trigger_ids=trigger_ids,
                next_run=trigger_config.next_run,
            )

            if activated is None:
                # Rollback triggers if DB update fails (pass workflow_id for reference counting)
                if trigger_ids and trigger_name:
                    await TriggerService.unregister_triggers(
                        user_id, trigger_name, trigger_ids, workflow_id
                    )
                return None

            # 3. Get updated workflow
            updated_workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not updated_workflow:
                return None

            # 4. Schedule if needed — liveness is governed by `activated`.
            if (
                trigger_type == "schedule"
                and updated_workflow.activated
                and updated_workflow.trigger_config.next_run
            ):
                await workflow_scheduler.schedule_workflow_execution(
                    workflow_id,
                    updated_workflow.trigger_config.next_run,
                    repeat=updated_workflow.trigger_config.cron_expression,
                    max_occurrences=getattr(updated_workflow, "max_occurrences", None),
                    stop_after=getattr(updated_workflow, "stop_after", None),
                )

            log.set(workflow={"id": workflow_id, "status": "activated"})
            log.info(
                f"{LogTag.WORKFLOW} Activated workflow for user",
                workflow_id=workflow_id,
                user_id=user_id,
            )
            return updated_workflow

        except TriggerRegistrationError as e:
            # Trigger registration failed - workflow remains inactive
            log.error(
                f"{LogTag.WORKFLOW} Failed to activate workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

        except ValueError:
            # Validation refusal (e.g. missing step integrations) — a normal 400,
            # surfaced to the user; not an internal error to log loudly.
            raise

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error activating workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def deactivate_workflow(
        workflow_id: str,
        user_id: str,
        user_timezone: str | None = None,
        *,
        reason: DeactivationReason | None = None,
    ) -> Workflow | None:
        """Deactivate a workflow (disable its trigger). ``reason`` marks a system
        pause; a user switching the workflow off passes none."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return None

            # Liveness is governed by `activated` (set False below). A deferred ARQ
            # fire already in Redis is harmless — the claim gate rejects it because
            # the row is no longer `activated`. No status write is needed here.

            # Unregister Composio triggers if any (pass workflow_id for reference counting)
            trigger_config = workflow.trigger_config
            trigger_ids = trigger_config.composio_trigger_ids or []
            if trigger_ids:
                trigger_name = trigger_config.trigger_name
                if trigger_name:
                    await TriggerService.unregister_triggers(
                        user_id, trigger_name, trigger_ids, workflow_id
                    )
                    log.info(
                        f"{LogTag.WORKFLOW} Unregistered Composio triggers for workflow",
                        trigger_ids_count=len(trigger_ids),
                        workflow_id=workflow_id,
                    )
                else:
                    log.warning(
                        f"{LogTag.WORKFLOW} No trigger_name found for workflow, cannot unregister triggers",
                        workflow_id=workflow_id,
                        user_id=user_id,
                    )

            # Update trigger to disabled and clear trigger IDs
            deactivated = await workflow_repository.deactivate(workflow_id, user_id, reason=reason)

            if deactivated is None:
                return None

            log.set(workflow={"id": workflow_id, "status": "deactivated"})
            log.info(
                f"{LogTag.WORKFLOW} Deactivated workflow for user",
                workflow_id=workflow_id,
                user_id=user_id,
            )
            return await WorkflowService.get_workflow(workflow_id, user_id)

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error deactivating workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def regenerate_workflow_steps(
        workflow_id: str,
        user_id: str,
        regeneration_reason: str | None = None,
        force_different_tools: bool = True,
        integration_ids: list[str] | None = None,
    ) -> Workflow | None:
        """Regenerate steps for an existing workflow."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return None

            effective_integration_ids = (
                integration_ids if integration_ids is not None else workflow.integration_ids
            )

            steps = await WorkflowGenerationService.generate_steps_with_llm(
                workflow.effective_prompt,
                workflow.title,
                workflow.trigger_config,
                description=workflow.description,
                integration_ids=effective_integration_ids or None,
                user_id=user_id,
            )

            # Same gating as _generate_workflow_steps: if the regenerated steps
            # need an integration the user hasn't connected, force the workflow
            # inactive so an enabled-but-unrunnable workflow can't keep firing.
            required = compute_required_integrations(steps)
            missing = await compute_missing_integrations(required, user_id)

            # Persist only integration_ids the user still has connected — a stale
            # id from the client must not resurrect an integration they removed.
            filtered_integration_ids = (
                await filter_existing_integration_ids(integration_ids)
                if integration_ids is not None
                else None
            )

            if missing:
                log.info(
                    f"{LogTag.WORKFLOW} Workflow kept inactive — missing step integrations",
                    workflow_id=workflow_id,
                    missing_integrations=[m.id for m in missing],
                )

            result = await workflow_repository.set_steps(
                workflow_id,
                user_id,
                steps,
                deactivate=bool(missing),
                integration_ids=filtered_integration_ids,
            )

            if result:
                workflow = WorkflowWithIntegrations(**result.model_dump())
                # Match get_workflow/list_workflows so the regenerated steps'
                # required/missing integrations surface in the UI.
                await WorkflowService._enrich_integration_fields(workflow, user_id)
                return workflow
            return None

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error regenerating workflow steps",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def increment_execution_count(
        workflow_id: str, user_id: str, is_successful: bool = False
    ) -> bool:
        """Increment workflow execution statistics."""
        try:
            success = await workflow_repository.record_execution(
                workflow_id, user_id, successful=is_successful
            )
            if success:
                log.debug(
                    f"{LogTag.WORKFLOW} Updated execution count for workflow",
                    workflow_id=workflow_id,
                    successful_increment=1 if is_successful else 0,
                )
            else:
                log.warning(
                    f"{LogTag.WORKFLOW} Failed to update execution count - workflow not found",
                    workflow_id=workflow_id,
                    user_id=user_id,
                )

            return success

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error updating execution count for workflow",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            return False

    @staticmethod
    @Cacheable(smart_hash=True, ttl=300, model=PublicWorkflowsResponse)
    async def get_community_workflows(
        limit: int = 20,
        offset: int = 0,
        user_id: str | None = None,
    ) -> PublicWorkflowsResponse:
        """Get public workflows from the community marketplace with caching."""
        try:
            rows = await workflow_repository.find_community(limit=limit, offset=offset)
            total = await workflow_repository.count_community()

            formatted_workflows = [
                await WorkflowService._format_public_workflow(row) for row in rows
            ]

            return PublicWorkflowsResponse(workflows=formatted_workflows, total=total)

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error fetching community workflows",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            raise

    @staticmethod
    async def _format_public_workflow(
        row: PublicWorkflowRow, *, default_creator_name: str | None = None
    ) -> dict[str, Any]:
        """Shape one hydrated marketplace row into the public-card dict.

        Shared by the community and explore lists so the two payloads can't drift.
        Backfills a legacy public workflow's missing slug in place first.
        """
        await ensure_public_workflow_slug(row)
        normalized_steps = [
            {
                "id": step.id,
                "title": step.title,
                "description": step.description,
                "category": step.category or "general",
            }
            for step in row.steps
        ]
        return {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "slug": row.slug,
            "prompt": row.prompt,
            "icon": row.icon,
            "icon_color": row.icon_color,
            # Present only on the built-in cards: lets the client dedupe against a
            # workflow the user was already provisioned, and name the integration
            # that sets it up automatically.
            "system_workflow_key": row.system_workflow_key,
            "source_integration": row.source_integration,
            # The card advertises "Daily at 8am" / "on new email", so adding it has
            # to reproduce that trigger — without this the client can only guess,
            # and every added workflow silently became manual.
            "trigger_config": row.trigger_config.model_dump(mode="json"),
            "steps": normalized_steps,
            "created_at": row.created_at,
            "creator": format_creator(row, default_name=default_creator_name),
        }

    @staticmethod
    @Cacheable(smart_hash=True, ttl=600, model=PublicWorkflowsResponse)
    async def get_explore_workflows(
        limit: int = 25,
        offset: int = 0,
    ) -> PublicWorkflowsResponse:
        """Get explore/featured workflows for the discover section with caching."""
        try:
            rows = await workflow_repository.find_explore(limit=limit, offset=offset)
            total = await workflow_repository.count_explore()

            formatted_workflows = []
            for row in rows:
                # Explore rows carry the community card shape plus the featured-only
                # categories/total_executions, and default the creator to the GAIA
                # team (the plain lookup never resolves a real user — see the repo).
                formatted = await WorkflowService._format_public_workflow(
                    row, default_creator_name=SYSTEM_CREATOR_NAME
                )
                formatted["categories"] = row.use_case_categories
                formatted["total_executions"] = row.total_executions
                formatted_workflows.append(formatted)

            return PublicWorkflowsResponse(workflows=formatted_workflows, total=total)

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error fetching explore workflows",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    @staticmethod
    async def _generate_workflow_steps(
        workflow_id: str,
        user_id: str,
        integration_ids: list[str] | None = None,
    ) -> None:
        """Generate workflow steps using LLM with structured output.

        Falls back to the workflow's own integration_ids so every caller
        (immediate, queued, agent-created) scopes the tool palette the same way.
        """
        try:
            await workflow_repository.touch(workflow_id, user_id)

            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return

            # Generate steps using structured LLM output.
            # Raises RuntimeError on failure (no silent empty-list return).
            steps = await WorkflowGenerationService.generate_steps_with_llm(
                workflow.effective_prompt,
                workflow.title,
                workflow.trigger_config,
                description=workflow.description,
                integration_ids=integration_ids or workflow.integration_ids or None,
                user_id=user_id,
            )

            required = compute_required_integrations(steps)
            missing = await compute_missing_integrations(required, user_id)

            if missing:
                # Keep deactivated when step integrations are not connected.
                log.info(
                    f"{LogTag.WORKFLOW} Workflow kept inactive — missing step integrations",
                    workflow_id=workflow_id,
                    missing_integrations=[m.id for m in missing],
                )

            await workflow_repository.set_steps(
                workflow_id, user_id, steps, deactivate=bool(missing)
            )

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error generating workflow steps for",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            # Persist the error message so the status endpoint can report why it failed
            try:
                await workflow_repository.set_error_message(workflow_id, user_id, str(e))
            except Exception as db_err:
                log.error(
                    f"{LogTag.WORKFLOW} Failed to persist error_message for",
                    workflow_id=workflow_id,
                    error=str(db_err),
                    error_type=type(db_err).__name__,
                    user_id=user_id,
                )
            await handle_workflow_error(workflow_id, user_id, e)
