"""Workflow generation service for LLM-based step creation."""

from dataclasses import dataclass
import re
from typing import TypeVar, cast

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.agents.llm.client import (
    ainvoke_llm,
    background_structured_runnable,
    metered_config,
)
from app.agents.prompts.trigger_prompts import generate_trigger_context
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_PROMPT_GENERATION_SYSTEM,
    WORKFLOW_PROMPT_GENERATION_TEMPLATE,
)
from app.agents.templates.workflow_template import WORKFLOW_GENERATION_TEMPLATE
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.integrations import MANAGED_BY_INTERNAL
from app.constants.log_tags import LogTag
from app.models.workflow_models import (
    GeneratedPromptOutput,
    GeneratedPromptResult,
    GeneratedStep,
    GeneratedWorkflow,
    PromptTriggerHint,
    SuggestedTrigger,
    TriggerConfig,
    WorkflowStep,
)
from shared.py.wide_events import log

_StructuredSchemaT = TypeVar("_StructuredSchemaT", bound=BaseModel)

_MAX_GENERATION_ATTEMPTS = 2

# Provider messages can be long (OpenRouter's 402 body quotes credit figures);
# the modal shows this inline, so keep it to one readable line.
_MAX_REASON_CHARS = 300


class WorkflowStepGenerationError(RuntimeError):
    """Step generation failed for a reason the user should be told about.

    Subclasses ``RuntimeError`` so callers that already treat generation failure
    as a runtime error keep working; the API layer catches this type to turn the
    opaque 500 into a message the workflow modal can render.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _failure_reason(error: BaseException) -> str:
    """A one-line, user-showable summary of why generation failed.

    The exception type is included because provider errors (a 402 from the
    model gateway, a timeout) say nothing about workflows on their own, and a
    bare message like "This request requires more credits" reads as if the
    user's own account is at fault.
    """
    detail = " ".join(str(error).split()) or error.__class__.__name__
    if len(detail) > _MAX_REASON_CHARS:
        detail = detail[: _MAX_REASON_CHARS - 1].rstrip() + "…"
    return f"{type(error).__name__}: {detail}"


async def _structured_one_shot(
    schema: type[_StructuredSchemaT],
    prompt: LanguageModelInput,
    *,
    label: str,
    user_id: str,
) -> _StructuredSchemaT:
    """A structured one-shot on the provider THIS deployment actually runs on.

    ``ainvoke_structured`` is hardwired to the OpenRouter aux lane. A deployment
    pointed at a custom endpoint (``DEV_DEFAULT_MODEL=custom``) has no working
    OpenRouter route, so every workflow generation died on a provider error
    before the model was ever asked — which surfaced as a blank 500 from
    ``/regenerate-steps``. ``background_structured_runnable`` picks the lane
    this deployment is configured for and falls back to the aux lane otherwise.
    """
    config = metered_config(user_id)
    return cast(
        _StructuredSchemaT,
        await ainvoke_llm(
            background_structured_runnable(schema, config=config),
            prompt,
            label=label,
            config=config,
        ),
    )


def _slug_to_friendly_name(slug: str) -> str:
    for integration in OAUTH_INTEGRATIONS:
        if integration.id == slug:
            return integration.name
    return slug


def _normalize_slugs(slugs: list[str] | None) -> list[str]:
    if not slugs:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in slugs:
        s = (raw or "").strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _extract_explicit_mentions(prompt: str) -> set[str]:
    """Return integration IDs that are explicitly named in the workflow prompt.

    Checks each integration's name and id against the prompt text so that
    a step using that integration is guaranteed to be included even when the
    integration is not in the user's preferred-integration set.
    """
    lower_prompt = prompt.lower()
    mentioned: set[str] = set()
    for integration in OAUTH_INTEGRATIONS:
        # Word-boundary match so short/common names/ids (e.g. "box" in "inbox")
        # don't get flagged as explicit mentions and force-include integrations.
        for token in (integration.name.lower(), integration.id.lower()):
            if re.search(rf"\b{re.escape(token)}\b", lower_prompt):
                mentioned.add(integration.id)
                break
    return mentioned


def _build_trigger_hint(trigger_config: PromptTriggerHint | None) -> str:
    """Build a minimal, human-readable trigger hint for the LLM.

    We intentionally omit raw cron/timezone/next_run so the LLM cannot
    leak scheduling details into the instructions prose.
    """
    if not trigger_config:
        return (
            "No trigger selected yet — suggest the most appropriate trigger "
            "type based on the user's intent."
        )

    trigger_type = trigger_config.type

    if trigger_type == "schedule":
        cron = trigger_config.cron_expression
        hint = "User has selected a scheduled trigger"
        if cron:
            hint += f" (current cron: {cron})"
        hint += ". Suggest a cron expression that matches the described cadence."
        return hint
    if trigger_type == "manual":
        return (
            "User has selected a manual trigger. Respect this unless "
            "the instructions clearly imply a recurring schedule."
        )
    # Integration triggers
    trigger_name = trigger_config.trigger_name
    if trigger_name:
        return f"User has selected an integration trigger ({trigger_name})."
    return f"User has selected trigger type: {trigger_type}."


def _build_available_triggers(
    connected_integration_ids: set[str] | None = None,
) -> str:
    """Build a compact list of available integration triggers for the LLM.

    If `connected_integration_ids` is provided, only triggers from those
    integrations are listed. This prevents the LLM from suggesting triggers
    the user can't actually use.
    """
    lines: list[str] = []
    for integration in OAUTH_INTEGRATIONS:
        if (
            connected_integration_ids is not None
            and integration.id not in connected_integration_ids
        ):
            continue
        for tc in integration.associated_triggers:
            schema = tc.workflow_trigger_schema
            if schema:
                desc = f" — {schema.description}" if schema.description else ""
                lines.append(f"- {schema.slug}: {schema.name} ({integration.name}){desc}")
    if not lines:
        return ""
    return "Available integration triggers (use the slug for trigger_name):\n" + "\n".join(lines)


def enrich_steps(generated_steps: list[GeneratedStep]) -> list[WorkflowStep]:
    """Convert minimal generated steps to the full step schema with ids."""
    return [
        WorkflowStep(
            id=f"step_{i}",
            title=step.title,
            category=step.category,
            description=step.description,
        )
        for i, step in enumerate(generated_steps)
    ]


def _collect_registry_categories(
    tool_registry: ToolRegistry, active_set: set[str]
) -> tuple[list[str], list[str]]:
    """List the tool-registry categories the generator may use, with their tools.

    Provider categories (``require_integration``) are included only when the
    integration is in ``active_set``; core categories are always included.
    """
    category_names: list[str] = []
    tools_with_categories: list[str] = []
    for category, cat_obj in tool_registry.get_all_category_objects().items():
        if cat_obj.require_integration:
            # Provider category: include only when in the active set.
            integration_key = (cat_obj.integration_name or category).lower()
            if integration_key not in active_set:
                continue
        # Core category (require_integration=False): always include.
        category_names.append(category)
        tool_names = [
            tool.name if hasattr(tool, "name") else str(tool) for tool in cat_obj.get_tool_objects()
        ]
        tools_with_categories.append(f"{category}: {', '.join(tool_names)}")
    return category_names, tools_with_categories


def _collect_subagent_categories(active_set: set[str]) -> tuple[list[str], list[str]]:
    """List subagent capabilities offered to the generator as categories.

    Internal subagents (todos/reminders/skills) are always-available core
    capabilities; provider subagents are gated by the active set so
    unconnected/unnamed ones stay out.
    """
    category_names: list[str] = []
    tools_with_categories: list[str] = []
    for integration in OAUTH_INTEGRATIONS:
        if integration.subagent_config and integration.subagent_config.has_subagent:
            is_internal = integration.managed_by == MANAGED_BY_INTERNAL
            if not is_internal and integration.id.lower() not in active_set:
                continue
            cfg = integration.subagent_config
            category_names.append(integration.id)
            tools_with_categories.append(f"{integration.id} (subagent): {cfg.capabilities}")
    return category_names, tools_with_categories


async def _collect_custom_integration_categories(
    user_id: str, active_set: set[str]
) -> tuple[list[str], list[str], dict[str, str]]:
    """List the user's selected custom (MCP / self-added) integrations.

    These aren't in the static registry or ``OAUTH_INTEGRATIONS``, so each is
    surfaced as its own category keyed by integration id, along with the
    id -> display-name map the preferred-tools hint needs. Loading them is an
    enrichment: on failure this degrades to the built-in catalog.
    """
    category_names: list[str] = []
    tools_with_categories: list[str] = []
    display_names: dict[str, str] = {}
    try:
        # Local import: my_integrations -> tools/oauth services transitively
        # import this module, so a top-level import is a circular import.
        from app.services.integrations.my_integrations import (  # noqa: PLC0415 -- my_integrations transitively re-imports this module; top-level would be circular
            get_my_integrations,
        )

        my_integrations = await get_my_integrations(user_id)
        for integ in my_integrations.integrations:
            if integ.source != "custom":
                continue
            if integ.id.lower() not in active_set:
                continue
            category_names.append(integ.id)
            display_names[integ.id.lower()] = integ.name
            summary = integ.description or integ.name
            tools_with_categories.append(
                f"{integ.id} (custom integration): {integ.name}. {summary}"
            )
    except Exception as e:
        # Custom integrations are an enrichment for generation; degrade to
        # the built-in catalog rather than failing the whole generation.
        log.warning(
            f"{LogTag.WORKFLOW} Could not load custom integrations for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
    return category_names, tools_with_categories, display_names


def _build_integration_hints(
    prefer_set: set[str], explicit_set: set[str], display_names: dict[str, str]
) -> list[str]:
    """Build the preferred/explicit integration hint lines appended to the prompt.

    Each slug is resolved to a human label plus its category id: the name tells
    the LLM what the user meant; the id is what each step's ``category`` must be
    set to for that integration's tools to resolve. Custom integrations are
    keyed by an opaque uuid, so ``display_names`` supplies the human name
    ``OAUTH_INTEGRATIONS`` can't.
    """

    def _hint_label(slug: str) -> str:
        name = display_names.get(slug) or _slug_to_friendly_name(slug)
        return f"{name} (category: {slug})" if name != slug else slug

    hint_parts: list[str] = []
    if prefer_set:
        friendly_prefer = [_hint_label(s) for s in sorted(prefer_set)]
        hint_parts.append(
            "Preferred integrations (use where the workflow makes sense): "
            + ", ".join(friendly_prefer)
        )
    if explicit_set:
        friendly_explicit = [_hint_label(s) for s in sorted(explicit_set)]
        hint_parts.append(
            "Integrations the user explicitly named — MUST appear in the steps: "
            + ", ".join(friendly_explicit)
        )
    return hint_parts


def _validated_steps(result: GeneratedWorkflow | None) -> list[WorkflowStep] | None:
    """Enrich a candidate generation result, or return None when it is unusable.

    An empty result is regenerable rather than fatal, so it is reported as
    absence instead of raising.
    """
    if not result or not result.steps:
        return None
    return enrich_steps(result.steps)


async def _run_generation_attempt(
    formatted_prompt: str, *, user_id: str, attempt: int
) -> tuple[list[WorkflowStep] | None, Exception | None]:
    """Run one generation attempt and classify its outcome.

    Returns ``(steps, None)`` on success and ``(None, error)`` when the attempt
    is regenerable — empty output or schema-invalid structured output. Provider
    failures are not regenerable and are raised as
    ``WorkflowStepGenerationError``.
    """
    try:
        result = await _structured_one_shot(
            GeneratedWorkflow,
            formatted_prompt,
            label="workflow_generation",
            user_id=user_id,
        )
    except (ValidationError, OutputParserException) as e:
        # Schema-invalid structured output is regenerable; the provider's
        # own retry/fallback already ran inside ainvoke_llm.
        log.warning(
            f"{LogTag.WORKFLOW} Structured output invalid; regenerating",
            attempt=attempt + 1,
            max_attempts=_MAX_GENERATION_ATTEMPTS,
            error_type=type(e).__name__,
        )
        return None, e
    except Exception as e:
        # Not regenerable: the provider itself failed (auth, credit,
        # timeout) after ainvoke_llm's own retry+fallback. Re-raise as
        # the typed error so the API answers with the reason instead of
        # a blank 500 — the cause chain is kept, nothing is swallowed.
        log.error(
            f"{LogTag.WORKFLOW} ========== FAILED: provider error",
            attempt=attempt + 1,
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )
        raise WorkflowStepGenerationError(_failure_reason(e)) from e

    steps_data = _validated_steps(result)
    if steps_data is not None:
        log.info(f"{LogTag.WORKFLOW} ========== DONE: steps", steps_data_count=len(steps_data))
        return steps_data, None

    log.warning(
        f"{LogTag.WORKFLOW} No steps; regenerating",
        attempt=attempt + 1,
        max_attempts=_MAX_GENERATION_ATTEMPTS,
    )
    return None, ValueError(
        "LLM returned a workflow with no steps — the model may not have understood the request"
    )


@dataclass(frozen=True)
class WorkflowPromptRequest:
    """The inputs that shape a generated/improved workflow instruction prompt.

    Grouped into one object because they travel together from the API layer:
    what the workflow is (``title``/``description``), what the user already
    wrote (``existing_prompt``), and which integrations may or should be named
    (``connected_integration_ids``/``integration_ids``).
    """

    title: str | None = None
    description: str | None = None
    trigger_config: PromptTriggerHint | None = None
    existing_prompt: str | None = None
    connected_integration_ids: set[str] | None = None
    integration_ids: list[str] | None = None


class WorkflowGenerationService:
    """Service for generating workflow steps using LLM."""

    @staticmethod
    async def generate_steps_with_llm(
        prompt: str,
        title: str,
        trigger_config: TriggerConfig | None = None,
        description: str | None = None,
        integration_ids: list[str] | None = None,
        *,
        user_id: str,
    ) -> list[WorkflowStep]:
        """Generate workflow steps using the LLM's native structured output.

        Raises:
            WorkflowStepGenerationError: If generation fails — either the
                provider call failed outright or every attempt came back
                empty/schema-invalid. Carries a user-showable ``reason``.
        """
        log.info(f"{LogTag.WORKFLOW} ========== START", title=title)

        log.info(f"{LogTag.WORKFLOW} Getting tool registry...")
        tool_registry = await get_tool_registry()

        normalized_slugs = _normalize_slugs(integration_ids)
        prefer_set = set(normalized_slugs)
        explicit_set = _extract_explicit_mentions(prompt)
        # Union of preferred integrations and those explicitly named in the prompt.
        # Preferred integrations are soft hints; explicit mentions are hard requirements.
        active_set = prefer_set | explicit_set

        category_names, tools_with_categories = _collect_registry_categories(
            tool_registry, active_set
        )
        subagent_categories, subagent_lines = _collect_subagent_categories(active_set)
        category_names.extend(subagent_categories)
        tools_with_categories.extend(subagent_lines)

        for tool in tool_registry.get_core_tools():
            tool_name = tool.name if hasattr(tool, "name") else str(tool)
            tools_with_categories.append(f"Always Available: {tool_name}")

        # gaia is always a valid category — for pure LLM reasoning steps
        category_names.append("gaia")
        tools_with_categories.append(
            "gaia: GAIA reasoning — summarize content, draft text, classify items, "
            "generate outlines, extract key points, write briefs. No external tool call."
        )

        # Selected custom-integration ids -> display name. Custom integrations are
        # keyed by an opaque uuid, so the preferred-tools hint must resolve the
        # human name here (OAUTH_INTEGRATIONS doesn't know them).
        selected_display_names: dict[str, str] = {}
        if user_id:
            (
                custom_categories,
                custom_lines,
                selected_display_names,
            ) = await _collect_custom_integration_categories(user_id, active_set)
            category_names.extend(custom_categories)
            tools_with_categories.extend(custom_lines)

        log.info(
            f"{LogTag.WORKFLOW} Categories resolved",
            category_count=len(category_names),
            prefer=sorted(prefer_set),
            explicit=sorted(explicit_set),
        )

        trigger_context = generate_trigger_context(trigger_config)

        log.info(f"{LogTag.WORKFLOW} Formatting prompt...")
        prompt_context = prompt
        if description:
            prompt_context = (
                f"{prompt}\n\nShort display summary for additional context: {description}"
            )

        hint_parts = _build_integration_hints(prefer_set, explicit_set, selected_display_names)
        if hint_parts:
            prompt_context = prompt_context + "\n\n" + "\n".join(hint_parts)

        formatted_prompt = WORKFLOW_GENERATION_TEMPLATE.format(
            description=prompt_context,
            title=title,
            trigger_context=trigger_context,
            tools="\n".join(tools_with_categories),
            categories=", ".join(category_names),
        )
        log.info(f"{LogTag.WORKFLOW} Prompt built", prompt_chars=len(formatted_prompt))

        # Transient provider errors are retried inside ainvoke_llm; this loop
        # only regenerates when the model returns an empty or schema-invalid result.
        last_error: Exception | None = None
        for attempt in range(_MAX_GENERATION_ATTEMPTS):
            if attempt > 0:
                log.info(
                    f"{LogTag.WORKFLOW} Regeneration attempt for", attempt=attempt, title=title
                )

            steps_data, last_error = await _run_generation_attempt(
                formatted_prompt, user_id=user_id, attempt=attempt
            )
            if steps_data is not None:
                return steps_data

        log.error(
            f"{LogTag.WORKFLOW} ========== FAILED after attempts",
            _max_generation_attempts=_MAX_GENERATION_ATTEMPTS,
            last_error=last_error,
            user_id=user_id,
        )
        # Every exhausted attempt returned a reason, so there is always one to
        # show: `_run_generation_attempt` only yields no steps together with the
        # error that explains why.
        reason = f"the model returned no usable steps after {_MAX_GENERATION_ATTEMPTS} attempts"
        if last_error:
            reason += f" ({_failure_reason(last_error)})"
        raise WorkflowStepGenerationError(reason) from last_error

    @staticmethod
    async def generate_workflow_prompt(
        request: WorkflowPromptRequest,
        *,
        user_id: str,
    ) -> GeneratedPromptResult:
        """Generate or improve workflow instructions using LLM.

        If `request.connected_integration_ids` is provided, the available-triggers
        list shown to the LLM is restricted to those integrations.
        If `request.integration_ids` is provided, the LLM is hinted to prefer
        those integrations when naming triggers/actions.
        """
        title = request.title
        description = request.description
        existing_prompt = request.existing_prompt
        trigger_hint = _build_trigger_hint(request.trigger_config)
        available_triggers = _build_available_triggers(request.connected_integration_ids)

        normalized_slugs = _normalize_slugs(request.integration_ids)
        if normalized_slugs:
            friendly = [_slug_to_friendly_name(s) for s in normalized_slugs]
            integrations_hint = (
                "User has selected these integrations as preferred tools for this "
                "workflow: " + ", ".join(friendly) + ". Name them naturally in the "
                "instructions and prefer triggers/actions that use them."
            )
        else:
            integrations_hint = ""

        formatted = WORKFLOW_PROMPT_GENERATION_TEMPLATE.format(
            title_section=f"Title: {title}\n" if title else "",
            description_section=f"Description: {description}" if description else "",
            trigger_hint=trigger_hint,
            integrations_hint=integrations_hint,
            available_triggers=available_triggers,
            existing_section=(
                f"Existing instructions to improve:\n{existing_prompt}" if existing_prompt else ""
            ),
            mode_instruction=(
                "Improve these instructions — keep the user's intent, add specificity, "
                "edge case handling, and output details."
                if existing_prompt
                else "Generate comprehensive workflow instructions from scratch."
            ),
        )

        messages = [
            SystemMessage(content=WORKFLOW_PROMPT_GENERATION_SYSTEM),
            HumanMessage(content=formatted),
        ]

        result = await _structured_one_shot(
            GeneratedPromptOutput,
            messages,
            label="workflow_prompt",
            user_id=user_id,
        )

        suggested: SuggestedTrigger | None = None
        if result.trigger_type in ("manual", "schedule", "integration"):
            suggested = SuggestedTrigger(
                type=result.trigger_type,
                cron_expression=result.cron_expression,
                trigger_name=result.trigger_name,
            )

        return {"prompt": result.instructions, "suggested_trigger": suggested}
