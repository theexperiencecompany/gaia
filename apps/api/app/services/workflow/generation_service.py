"""Workflow generation service for LLM-based step creation."""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser

from app.agents.llm.client import init_llm
from app.agents.prompts.trigger_prompts import generate_trigger_context
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_PROMPT_GENERATION_SYSTEM,
    WORKFLOW_PROMPT_GENERATION_TEMPLATE,
)
from app.agents.templates.workflow_template import WORKFLOW_GENERATION_TEMPLATE
from app.agents.tools.core.registry import get_tool_registry
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.log_tags import LogTag
from app.models.workflow_models import (
    GeneratedPromptOutput,
    GeneratedStep,
    GeneratedWorkflow,
    SuggestedTrigger,
)
from shared.py.wide_events import log

prompt_output_parser = PydanticOutputParser(pydantic_object=GeneratedPromptOutput)

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


def _build_trigger_hint(trigger_config: dict | None) -> str:
    """Build a minimal, human-readable trigger hint for the LLM.

    We intentionally omit raw cron/timezone/next_run so the LLM cannot
    leak scheduling details into the instructions prose.
    """
    if not trigger_config:
        return (
            "No trigger selected yet — suggest the most appropriate trigger "
            "type based on the user's intent."
        )

    trigger_type = trigger_config.get("type", "manual")

    if trigger_type == "schedule":
        cron = trigger_config.get("cron_expression", "")
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
    trigger_name = trigger_config.get("trigger_name", "")
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


def enrich_steps(
    generated_steps: list[GeneratedStep],
    category_icon_urls: dict[str, str] | None = None,
) -> list[dict]:
    """Convert minimal generated steps to full step schema with id.

    ``category_icon_urls`` maps a custom integration id (used as a step category)
    to its icon URL, so the frontend can render an icon the category name alone
    can't resolve. Built-in categories resolve by name and stay ``None``.
    """
    icons = category_icon_urls or {}
    enriched = []
    for i, step in enumerate(generated_steps):
        enriched.append(
            {
                "id": f"step_{i}",
                "title": step.title,
                "category": step.category,
                "description": step.description,
                "icon_url": icons.get(step.category),
            }
        )
    return enriched


def _parse_workflow_response(content: str) -> GeneratedWorkflow:
    """Parse raw LLM text into GeneratedWorkflow, handling markdown fences."""
    cleaned = content.strip()
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        else:
            cleaned = cleaned[3:]
    cleaned = cleaned.removesuffix("```")
    cleaned = cleaned.strip()
    return GeneratedWorkflow.model_validate_json(cleaned)


class WorkflowGenerationService:
    """Service for generating workflow steps using LLM."""

    @staticmethod
    async def generate_steps_with_llm(
        prompt: str,
        title: str,
        trigger_config=None,
        description: str | None = None,
        selected_integrations: list[str] | None = None,
        user_id: str | None = None,
    ) -> list:
        """Generate workflow steps using LLM with structured output.

        Uses the LLM's native structured output (function calling / JSON schema)
        for reliable generation. Falls back to text parsing if the provider
        doesn't support with_structured_output. Retries once on failure.

        Raises:
            RuntimeError: If generation fails after all retry attempts.
        """
        log.info(f"{LogTag.WORKFLOW} ========== START: {title} ==========")

        log.info(f"{LogTag.WORKFLOW} Getting tool registry...")
        tool_registry = await get_tool_registry()

        normalized_slugs = _normalize_slugs(selected_integrations)
        slug_set = set(normalized_slugs)
        # An empty selection means "no filter" — show the whole registry.
        filter_active = bool(slug_set)

        tools_with_categories = []
        category_names = []
        # Custom integration ids -> icon URL, so generated steps that use a
        # custom integration carry an icon the frontend can render.
        category_icon_urls: dict[str, str] = {}
        # Selected custom-integration ids -> display name. Custom integrations are
        # keyed by an opaque uuid, so the preferred-tools hint must resolve the
        # human name here (OAUTH_INTEGRATIONS doesn't know them).
        selected_display_names: dict[str, str] = {}
        categories = tool_registry.get_all_category_objects()
        for category in categories.keys():
            if filter_active and category.lower() not in slug_set:
                continue
            category_names.append(category)
            category_tools = categories[category].get_tool_objects()
            tool_names = [
                tool.name if hasattr(tool, "name") else str(tool) for tool in category_tools
            ]
            tools_with_categories.append(f"{category}: {', '.join(tool_names)}")

        # Add subagent capabilities
        for integration in OAUTH_INTEGRATIONS:
            if integration.subagent_config and integration.subagent_config.has_subagent:
                if filter_active and integration.id.lower() not in slug_set:
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
        # each as its own category (keyed by integration id) with its icon URL, so
        # steps can use them and resolve an icon on the frontend.
        if user_id:
            try:
                # Local import: my_integrations -> tools/oauth services transitively
                # import this module, so a top-level import is a circular import.
                from app.services.integrations.my_integrations import (
                    get_my_integrations,
                )

                my_integrations = await get_my_integrations(user_id)
                for integ in my_integrations.integrations:
                    if integ.source != "custom":
                        continue
                    if filter_active and integ.id.lower() not in slug_set:
                        continue
                    category_names.append(integ.id)
                    selected_display_names[integ.id.lower()] = integ.name
                    summary = integ.description or integ.name
                    tools_with_categories.append(
                        f"{integ.id} (custom integration): {integ.name}. {summary}"
                    )
                    if integ.icon_url:
                        category_icon_urls[integ.id] = integ.icon_url
            except Exception as e:
                # Custom integrations are an enrichment for generation; degrade to
                # the built-in catalog rather than failing the whole generation.
                log.warning(
                    f"{LogTag.WORKFLOW} Could not load custom integrations for user {user_id}: {e}"
                )

        log.info(
            f"{LogTag.WORKFLOW} Categories: {len(category_names)} "
            f"(filtered={filter_active}, slugs={normalized_slugs})"
        )

        trigger_context = generate_trigger_context(trigger_config)

        llm = init_llm()

        # Use native structured output for reliable JSON generation.
        # with_structured_output uses the LLM's function-calling / JSON schema
        # instead of fragile prompt-based text parsing.
        use_native_structured = hasattr(llm, "with_structured_output")
        structured_llm = None
        if use_native_structured:
            try:
                structured_llm = llm.with_structured_output(GeneratedWorkflow)
            except (NotImplementedError, TypeError):
                log.info(
                    f"{LogTag.WORKFLOW} LLM does not support with_structured_output, "
                    "using text parsing fallback"
                )

        log.info(f"{LogTag.WORKFLOW} Formatting prompt...")
        prompt_context = prompt
        if description:
            prompt_context = (
                f"{prompt}\n\nShort display summary for additional context: {description}"
            )
        if normalized_slugs:

            def _hint_label(slug: str) -> str:
                name = selected_display_names.get(slug) or _slug_to_friendly_name(slug)
                # Pass both the human name and the category id: the name tells the
                # LLM what the user meant, the id is what each step's `category`
                # must be set to for that integration's tools to resolve.
                return f"{name} (category: {slug})" if name != slug else slug

            friendly = [_hint_label(s) for s in normalized_slugs]
            integration_hint = (
                "User has selected these integrations as preferred tools for this workflow: "
                + ", ".join(friendly)
                + ". Prioritise steps that use these integrations where appropriate, "
                "setting each such step's category to the given id."
            )
            prompt_context = f"{prompt_context}\n\n{integration_hint}"

        formatted_prompt = WORKFLOW_GENERATION_TEMPLATE.format(
            description=prompt_context,
            title=title,
            trigger_context=trigger_context,
            tools="\n".join(tools_with_categories),
            categories=", ".join(category_names),
        )
        log.info(f"{LogTag.WORKFLOW} Prompt: {len(formatted_prompt)} chars")

        last_error: Exception | None = None
        for attempt in range(_MAX_GENERATION_ATTEMPTS):
            try:
                if attempt > 0:
                    log.info(f"{LogTag.WORKFLOW} Retry attempt {attempt} for: {title}")

                log.info(f"{LogTag.WORKFLOW} === CALLING LLM ===")

                if structured_llm:
                    result = await structured_llm.ainvoke(formatted_prompt)
                else:
                    # Fallback: invoke LLM and parse text response.
                    # Append minimal format guidance since with_structured_output
                    # isn't available to constrain the output schema.
                    fallback_prompt = (
                        formatted_prompt
                        + "\n\nRespond with ONLY a JSON object in this exact format, "
                        "no other text:\n"
                        '{"steps": [{"title": "...", "category": "...", '
                        '"description": "..."}]}'
                    )
                    llm_response = await llm.ainvoke(fallback_prompt)
                    response_content = getattr(llm_response, "content", str(llm_response))
                    log.debug(f"{LogTag.WORKFLOW} Raw response ({len(response_content)} chars)")
                    result = _parse_workflow_response(response_content)

                log.info(f"{LogTag.WORKFLOW} === LLM RESPONDED ===")

                if not result or not result.steps:
                    raise ValueError(
                        "LLM returned a workflow with no steps — "
                        "the model may not have understood the request"
                    )

                steps_data = enrich_steps(result.steps, category_icon_urls)

                log.info(f"{LogTag.WORKFLOW} ========== DONE: {len(steps_data)} steps ==========")
                return steps_data

            except Exception as e:
                last_error = e
                log.warning(
                    f"{LogTag.WORKFLOW} Attempt {attempt + 1}/{_MAX_GENERATION_ATTEMPTS} failed: {e}"
                )

        log.error(
            f"{LogTag.WORKFLOW} ========== FAILED after {_MAX_GENERATION_ATTEMPTS} "
            f"attempts: {last_error} =========="
        )
        raise RuntimeError(
            f"Workflow step generation failed for '{title}' "
            f"after {_MAX_GENERATION_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    @staticmethod
    async def generate_workflow_prompt(
        title: str | None = None,
        description: str | None = None,
        trigger_config: dict | None = None,
        existing_prompt: str | None = None,
        connected_integration_ids: set[str] | None = None,
        selected_integrations: list[str] | None = None,
    ) -> dict:
        """Generate or improve workflow instructions using LLM.

        Returns a dict with keys: prompt, suggested_trigger (optional).

        If `connected_integration_ids` is provided, the available-triggers
        list shown to the LLM is restricted to those integrations.
        If `selected_integrations` is provided, the LLM is hinted to prefer
        those integrations when naming triggers/actions.
        """
        trigger_hint = _build_trigger_hint(trigger_config)
        available_triggers = _build_available_triggers(connected_integration_ids)

        normalized_slugs = _normalize_slugs(selected_integrations)
        if normalized_slugs:
            friendly = [_slug_to_friendly_name(s) for s in normalized_slugs]
            integrations_hint = (
                "User has selected these integrations as preferred tools for this "
                "workflow: " + ", ".join(friendly) + ". Name them naturally in the "
                "instructions and prefer triggers/actions that use them."
            )
        else:
            integrations_hint = ""

        llm = init_llm()

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
            format_instructions=prompt_output_parser.get_format_instructions(),
        )

        messages = [
            SystemMessage(content=WORKFLOW_PROMPT_GENERATION_SYSTEM),
            HumanMessage(content=formatted),
        ]

        response = await llm.ainvoke(messages)
        raw_content = getattr(response, "content", str(response))
        if isinstance(raw_content, list):
            raw_content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in raw_content
            )
        response_content = raw_content.strip()

        result = prompt_output_parser.parse(response_content)

        suggested: SuggestedTrigger | None = None
        if result.trigger_type in ("manual", "schedule", "integration"):
            suggested = SuggestedTrigger(
                type=result.trigger_type,
                cron_expression=result.cron_expression,
                trigger_name=result.trigger_name,
            )

        return {"prompt": result.instructions, "suggested_trigger": suggested}
