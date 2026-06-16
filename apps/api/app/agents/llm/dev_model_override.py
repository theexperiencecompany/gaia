"""Dev-only per-agent model overrides (ENV=development).

Lets the web chat header force specific OpenRouter models for the comms and
executor agents independently, to benchmark which models perform best per task.
All overrides route through OpenRouter and lift the output cap. No effect in
production — every function is a no-op unless ``settings.ENV == "development"``.

Flow:
- ``apply_comms_dev_override`` runs on the comms agent's configurable. It forces
  the comms model (if selected) and stashes the executor selection as a
  passthrough key so ``call_executor`` can read it.
- ``apply_executor_dev_override`` runs on the executor's configurable (a copy of
  the comms configurable). It applies the executor model if selected; if only the
  comms model was overridden, it pins the executor back to the default so the
  comms override never leaks into the executor.
"""

from app.config.settings import settings
from app.constants.llm import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_NAME,
    DEV_MODEL_INFERENCE_PROVIDER,
    DEV_OPENROUTER_MAX_OUTPUT_TOKENS,
)

# Passthrough keys carrying dev selections from the comms configurable into the
# executor configurable (and propagated by build_agent_config).
DEV_COMMS_MODEL_KEY = "dev_comms_model"
DEV_EXECUTOR_MODEL_KEY = "dev_executor_model"
# Output-cap override consumed by the OpenRouter LLM's ConfigurableField.
DEV_MAX_OUTPUT_TOKENS_KEY = "dev_max_output_tokens"


def _is_dev() -> bool:
    return settings.ENV == "development"


_ALLOWED_PROVIDERS = (DEFAULT_LLM_PROVIDER, DEV_MODEL_INFERENCE_PROVIDER)


def _force_model(configurable: dict, value: str) -> None:
    """Pin the agent to a specific dev model.

    `value` is "<provider>:<model_id>" (e.g. "openrouter:deepseek/deepseek-v4-pro"
    or "gemini:gemini-3.1-flash-lite"). The provider is explicit — no guessing
    from the id shape. A malformed value falls back to OpenRouter. OpenRouter
    runs get a lifted output cap so reasoning models aren't truncated.
    """
    provider, sep, model_id = value.partition(":")
    if not sep or provider not in _ALLOWED_PROVIDERS:
        provider, model_id = DEV_MODEL_INFERENCE_PROVIDER, value
    configurable["provider"] = provider
    configurable["model"] = model_id
    configurable["model_name"] = model_id
    if provider == DEV_MODEL_INFERENCE_PROVIDER:
        configurable[DEV_MAX_OUTPUT_TOKENS_KEY] = DEV_OPENROUTER_MAX_OUTPUT_TOKENS
    else:
        configurable.pop(DEV_MAX_OUTPUT_TOKENS_KEY, None)


def apply_comms_dev_override(
    configurable: dict,
    comms_model: str | None,
    executor_model: str | None,
) -> None:
    """Apply the comms model override and stash the executor selection."""
    if not _is_dev():
        return
    if comms_model:
        configurable[DEV_COMMS_MODEL_KEY] = comms_model
        _force_model(configurable, comms_model)
    if executor_model:
        # Consumed later by apply_executor_dev_override inside call_executor.
        configurable[DEV_EXECUTOR_MODEL_KEY] = executor_model


def apply_executor_dev_override(configurable: dict) -> None:
    """Apply the executor model override on the executor's configurable copy."""
    if not _is_dev():
        return
    executor_model = configurable.get(DEV_EXECUTOR_MODEL_KEY)
    comms_model = configurable.get(DEV_COMMS_MODEL_KEY)
    if executor_model:
        _force_model(configurable, executor_model)
    elif comms_model:
        # Comms-only override: keep the executor on the default model.
        configurable["provider"] = DEFAULT_LLM_PROVIDER
        configurable["model"] = DEFAULT_MODEL_NAME
        configurable["model_name"] = DEFAULT_MODEL_NAME
        configurable.pop(DEV_MAX_OUTPUT_TOKENS_KEY, None)
