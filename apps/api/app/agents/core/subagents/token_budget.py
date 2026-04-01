"""
Token budget enforcement for subagent invocations.

Public API:
- SubagentTokenLimitError   — exception raised when budget is exceeded
- TokenBudgetCallbackHandler — inject into LangGraph config to auto-enforce
- inject_token_budget        — helper to add the callback to a config dict
- get_token_limit_summary    — final no-tools LLM call to report partial work
"""

from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from shared.py.wide_events import log

_BUDGET_EXCEEDED_PROMPT = (
    "You have reached your token budget. "
    "Summarize: (1) what you accomplished so far, (2) what data/findings you collected, "
    "(3) what still needs to be done."
)

_BUDGET_EXCEEDED_FOOTER = (
    "\n\n⚡ Token budget exhausted mid-execution. "
    "Parent agent can consider breaking remaining work into smaller parallel subagents."
)


class SubagentTokenLimitError(Exception):
    """Raised when a subagent exceeds its token budget."""

    def __init__(self, tokens_used: int, limit: int) -> None:
        self.tokens_used = tokens_used
        self.limit = limit
        super().__init__(
            f"Subagent token limit exceeded: {tokens_used:,} / {limit:,} tokens"
        )


class TokenBudgetCallbackHandler(UsageMetadataCallbackHandler):
    """Enforces a max token budget by raising SubagentTokenLimitError from on_llm_end.

    Because the exception fires inside the LangChain callback, it propagates
    through the graph execution and stops all running nodes — including nested
    subgraphs. ``raise_error = True`` ensures LangChain's dispatcher re-raises
    it instead of swallowing it silently.
    """

    raise_error: bool = True

    def __init__(self, max_tokens: int) -> None:
        super().__init__()
        self.max_tokens = max_tokens

    @property
    def total_tokens(self) -> int:
        return sum(
            v.get("total_tokens", 0)
            for v in self.usage_metadata.values()
            if isinstance(v, dict)
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:  # type: ignore[override]
        super().on_llm_end(response, **kwargs)
        used = self.total_tokens
        if used >= self.max_tokens:
            log.warning(
                "Subagent token budget exceeded",
                tokens_used=used,
                limit=self.max_tokens,
            )
            raise SubagentTokenLimitError(used, self.max_tokens)


def inject_token_budget(
    config: dict, max_tokens: int
) -> tuple[dict, TokenBudgetCallbackHandler]:
    """Return a new config with TokenBudgetCallbackHandler appended to callbacks."""
    cb = TokenBudgetCallbackHandler(max_tokens)
    existing = config.get("callbacks") or []
    return {**config, "callbacks": [*existing, cb]}, cb


async def get_token_limit_summary(
    graph: Any,
    config: dict,
    initial_state: dict,
    tokens_used: int,
    limit: int,
) -> str:
    """One final LLM call using the full graph message history.

    Fetches the conversation state from the checkpointer, appends a summary
    prompt, and invokes the LLM without tools so no new loop starts.
    """
    from app.agents.llm.client import init_llm

    try:
        state = await graph.aget_state(config)
        messages: list = list(state.values.get("messages", []))
    except Exception as exc:
        log.warning("failed to fetch graph state for token limit summary", error=str(exc))
        messages = list(initial_state.get("messages", []))

    messages.append(HumanMessage(content=_BUDGET_EXCEEDED_PROMPT))

    try:
        response = await init_llm().ainvoke(messages)
        if isinstance(response, AIMessage) and response.content:
            return (
                f"⚠️ Token limit reached ({tokens_used:,}/{limit:,} tokens). "
                f"Summary:\n\n{response.content}"
                f"{_BUDGET_EXCEEDED_FOOTER}"
            )
    except Exception as exc:
        log.warning("token limit summary LLM call failed", error=str(exc))

    return f"Token limit reached ({tokens_used:,}/{limit:,} tokens) before producing results."
