"""Shared types for the GAIA eval harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Case:
    """One eval scenario: prompt(s), ground truth, and how to run/score it."""

    id: str
    ticket: str
    prompt: str
    expected: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    transport: str = "in-process"
    setup: dict[str, Any] = field(default_factory=dict)

    @property
    def gates(self) -> list[str]:
        return list(self.expected.get("score", {}).get("gates", []))


@dataclass
class CaseRun:
    """What actually happened when the agent ran a case."""

    case_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    end_state: dict[str, Any] | None = None
    text: str = ""
    raw: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_s: float = 0.0
    error: str | None = None


@dataclass
class ProviderError(Exception):
    """Raised by a transport when the provider itself failed (not the agent).

    Triggers rotation to the next provider in the catalog.
    """

    provider: str
    reason: str

    def __str__(self) -> str:
        return f"provider {self.provider} failed: {self.reason}"


class ProviderHealth:
    """Result of a boot-time provider health check."""

    def __init__(self, ok: bool, reason: str = "") -> None:
        self.ok = ok
        self.reason = reason

    def __bool__(self) -> bool:
        return self.ok
