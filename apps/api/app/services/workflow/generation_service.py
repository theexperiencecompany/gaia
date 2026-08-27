"""Workflow generation service for LLM-based step creation."""

import re

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.prompts.trigger_prompts import generate_trigger_context
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_PROMPT_GENERATION_SYSTEM,
    WORKFLOW_PROMPT_GENERATION_TEMPLATE,
)
from app.agents.templates.workflow_template import WORKFLOW_GENERATION_TEMPLATE
from app.agents.tools.core.registry import get_tool_registry
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

_MAX_GENERATION_ATTEMPTS = 2


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
            RuntimeError: If generation fails after all retry attempts.
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

        tools_with_categories = []
        category_names = []
        # Selected custom-integration ids -> display name. Custom integrations are
        # keyed by an opaque uuid, so the preferred-tools hint must resolve the
        # human name here (OAUTH_INTEGRATIONS doesn't know them).
        selected_display_names: dict[str, str] = {}
        categories = tool_registry.get_all_category_objects()
        for category, cat_obj in categories.items():
            if cat_obj.require_integration:
                # Provider category: include only when in the active set.
                integration_key = (cat_obj.integration_name or category).lower()
                if integration_key not in active_set:
                    continue
            # Core category (require_integration=False): always include.
            category_names.append(category)
            category_tools = cat_obj.get_tool_objects()
            tool_names = [
                tool.name if hasattr(tool, "name") else str(tool) for tool in category_tools
            ]
            tools_with_categories.append(f"{category}: {', '.join(tool_names)}")

        # Add subagent capabilities. Internal subagents (todos/reminders/skills)
        # are always-available core capabilities — include them unconditionally,
        # mirroring the always-on core categories above. Provider subagents are
        # gated by the active set, so unconnected/unnamed ones stay out.
        for integration in OAUTH_INTEGRATIONS:
            if integration.subagent_config and integration.subagent_config.has_subagent:
                is_internal = integration.managed_by == MANAGED_BY_INTERNAL
                if not is_internal and integration.id.lower() not in active_set:
                    continue
                cfg = integration.subagent_config
                category_names.append(integration.id)
                tools_with_categories.append(f"{integration.id} (subagent): {cfg.capabilities}")

        for tool in tool_registry.get_core_tools():
            tool_name = tool.name if hasattr(tool, "name") else str(tool)
            tools_with_categories.append(f"Always Available: {tool_name}")

        # gaia is always a valid category — for pure LLM reasoning steps
        category_names.append("gaia")
        tools_with_categories.append(
            "gaia: GAIA reasoning — summarize content, draft text, classify items, "
            "generate outlines, extract key points, write briefs. No external tool call."
        )

        # The user's CUSTOM integrations (MCP / self-added) aren't in the static
        # registry or OAUTH_INTEGRATIONS, so the generator never saw them. Surface
        # each as its own category (keyed by integration id) so steps can use them.
        if user_id:
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
                    selected_display_names[integ.id.lower()] = integ.name
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

        # Resolve a slug to a human label plus its category id. The name tells
        # the LLM what the user meant; the id is what each step's `category`
        # must be set to for that integration's tools to resolve. Custom
        # integrations are keyed by an opaque uuid, so selected_display_names
        # supplies the human name OAUTH_INTEGRATIONS can't.
        def _hint_label(slug: str) -> str:
            name = selected_display_names.get(slug) or _slug_to_friendly_name(slug)
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

        # Transient provider errors are retried inside ainvoke_structured; this loop
        # only regenerates when the model returns an empty or schema-invalid result.
        last_error: Exception | None = None
        for attempt in range(_MAX_GENERATION_ATTEMPTS):
            if attempt > 0:
                log.info(
                    f"{LogTag.WORKFLOW} Regeneration attempt for", attempt=attempt, title=title
                )

            try:
                result = await ainvoke_structured(
                    GeneratedWorkflow,
                    formatted_prompt,
                    label="workflow_generation",
                    config=metered_config(user_id),
                )
            except (ValidationError, OutputParserException) as e:
                # Schema-invalid structured output is regenerable; provider errors
                # keep propagating so ainvoke_structured owns retry/fallback.
                last_error = e
                log.warning(
                    f"{LogTag.WORKFLOW} Structured output invalid; regenerating",
                    attempt=attempt + 1,
                    max_attempts=_MAX_GENERATION_ATTEMPTS,
                    error_type=type(e).__name__,
                )
                continue

            if result and result.steps:
                steps_data = enrich_steps(result.steps)
                log.info(
                    f"{LogTag.WORKFLOW} ========== DONE: steps", steps_data_count=len(steps_data)
                )
                return steps_data

            last_error = ValueError(
                "LLM returned a workflow with no steps — "
                "the model may not have understood the request"
            )
            log.warning(
                f"{LogTag.WORKFLOW} No steps; regenerating",
                attempt=attempt + 1,
                max_attempts=_MAX_GENERATION_ATTEMPTS,
            )

        log.error(
            f"{LogTag.WORKFLOW} ========== FAILED after attempts",
            _max_generation_attempts=_MAX_GENERATION_ATTEMPTS,
            last_error=last_error,
            user_id=user_id,
        )
        raise RuntimeError(
            f"Workflow step generation failed for '{title}' "
            f"after {_MAX_GENERATION_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    @staticmethod
    async def generate_workflow_prompt(
        title: str | None = None,
        description: str | None = None,
        trigger_config: PromptTriggerHint | None = None,
        existing_prompt: str | None = None,
        connected_integration_ids: set[str] | None = None,
        integration_ids: list[str] | None = None,
        *,
        user_id: str,
    ) -> GeneratedPromptResult:
        """Generate or improve workflow instructions using LLM.

        If `connected_integration_ids` is provided, the available-triggers
        list shown to the LLM is restricted to those integrations.
        If `integration_ids` is provided, the LLM is hinted to prefer
        those integrations when naming triggers/actions.
        """
        trigger_hint = _build_trigger_hint(trigger_config)
        available_triggers = _build_available_triggers(connected_integration_ids)

        normalized_slugs = _normalize_slugs(integration_ids)
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

        result = await ainvoke_structured(
            GeneratedPromptOutput,
            messages,
            label="workflow_prompt",
            config=metered_config(user_id),
        )

        suggested: SuggestedTrigger | None = None
        if result.trigger_type in ("manual", "schedule", "integration"):
            suggested = SuggestedTrigger(
                type=result.trigger_type,
                cron_expression=result.cron_expression,
                trigger_name=result.trigger_name,
            )

        return {"prompt": result.instructions, "suggested_trigger": suggested}
