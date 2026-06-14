"""Deterministic stand-in for the memory engine's single LLM boundary.

The engine funnels every LLM call (extraction, categorize, reconcile,
episode summary, consolidation) through
``app.memory.extraction._invoke_structured``. ``FakeMemoryLLM.invoke``
replaces it per test: register exactly one canned pydantic response (or a
callable over the prompt messages) per output schema, and any unregistered
call fails the test loudly. Everything downstream — degradation paths,
index normalization, hallucinated-target guards — runs for real.
"""

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.constants.memory import MemoryEntityType, MemoryKind, ReconcileOutcome
from app.memory.schemas import (
    ExtractedEdge,
    ExtractedEntity,
    ExtractedFact,
    ExtractedMemoryBatch,
    ReconcileBatchResult,
    ReconcileDecision,
)

_CANDIDATE_ID_PATTERN = re.compile(r"id=([0-9a-f-]{36})")

CannedResponse = BaseModel | None | Callable[[list[BaseMessage]], BaseModel | None]


@dataclass
class RecordedCall:
    """One captured LLM invocation: schema, prompt messages, operation tag."""

    output_model: type[BaseModel]
    messages: list[BaseMessage]
    operation: str

    @property
    def system(self) -> str:
        return str(self.messages[0].content)

    @property
    def human(self) -> str:
        return str(self.messages[-1].content)


class FakeMemoryLLM:
    """Canned, recorded replacement for ``extraction._invoke_structured``."""

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []
        self._responses: dict[type[BaseModel], CannedResponse] = {}

    def respond(self, output_model: type[BaseModel], response: CannedResponse) -> None:
        """Register the canned response (or messages->response callable) for a schema."""
        self._responses[output_model] = response

    def calls_for(self, output_model: type[BaseModel]) -> list[RecordedCall]:
        return [call for call in self.calls if call.output_model is output_model]

    async def invoke(
        self,
        output_model: type[BaseModel],
        messages: list[BaseMessage],
        *,
        operation: str,
    ) -> BaseModel | None:
        call = RecordedCall(output_model=output_model, messages=list(messages), operation=operation)
        self.calls.append(call)
        if output_model not in self._responses:
            raise AssertionError(
                f"Unexpected memory LLM call '{operation}' for {output_model.__name__}; "
                "register a canned response via fake_llm.respond(...)"
            )
        response = self._responses[output_model]
        if callable(response) and not isinstance(response, BaseModel):
            return response(messages)
        return response


def make_fact(
    content: str,
    *,
    category: str = "general",
    kind: MemoryKind = MemoryKind.FACT,
    importance: float = 0.6,
    entities: list[tuple[str, str]] | None = None,
    edges: list[tuple[str, str, str]] | None = None,
    **kwargs: Any,
) -> ExtractedFact:
    """Build an ExtractedFact the way the extraction LLM would emit it."""
    return ExtractedFact(
        content=content,
        kind=kind,
        category_path=category,
        importance=importance,
        entities=[
            ExtractedEntity(name=name, entity_type=MemoryEntityType(entity_type))
            for name, entity_type in (entities or [])
        ],
        edges=[
            ExtractedEdge(source=source, relationship=relationship, target=target)
            for source, relationship, target in (edges or [])
        ],
        **kwargs,
    )


def make_batch(
    facts: list[ExtractedFact] | None = None,
    entries: list[str] | None = None,
    agenda: list[str] | None = None,
) -> ExtractedMemoryBatch:
    return ExtractedMemoryBatch(
        facts=facts or [],
        episode_entries=entries or [],
        agenda_updates=agenda or [],
    )


def candidate_ids_from_prompt(messages: list[BaseMessage]) -> list[str]:
    """Extract the existing-memory candidate ids the reconcile prompt offered."""
    return _CANDIDATE_ID_PATTERN.findall(str(messages[-1].content))


def reconcile_against_first_candidate(
    outcome: ReconcileOutcome,
) -> Callable[[list[BaseMessage]], ReconcileBatchResult]:
    """Reconcile responder targeting the first candidate id shown in the prompt."""

    def _respond(messages: list[BaseMessage]) -> ReconcileBatchResult:
        ids = candidate_ids_from_prompt(messages)
        assert ids, "reconcile prompt offered no candidate ids"
        return ReconcileBatchResult(
            decisions=[
                ReconcileDecision(
                    new_fact_index=0,
                    decision=outcome,
                    target_memory_id=ids[0],
                )
            ]
        )

    return _respond
