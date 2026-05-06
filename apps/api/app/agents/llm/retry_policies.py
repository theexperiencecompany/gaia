"""Per-agent LangGraph retry policies.

Defined in one place so we can tune each agent's retry behaviour
independently from observed failure modes (executor tends to be longer-running,
comms is user-facing latency-sensitive, subagents fan out in parallel).
"""

from app.agents.llm.client import _LLM_RETRYABLE_EXCEPTIONS
from langgraph.types import RetryPolicy


def _llm_retry_policy(
    max_attempts: int = 3,
    initial_interval: float = 1.0,
    backoff_factor: float = 2.0,
    max_interval: float = 30.0,
) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_interval=initial_interval,
        backoff_factor=backoff_factor,
        max_interval=max_interval,
        jitter=True,
        retry_on=lambda exc: isinstance(exc, _LLM_RETRYABLE_EXCEPTIONS),
    )


EXECUTOR_RETRY_POLICY = _llm_retry_policy()
COMMS_RETRY_POLICY = _llm_retry_policy()
SUBAGENT_RETRY_POLICY = _llm_retry_policy()
