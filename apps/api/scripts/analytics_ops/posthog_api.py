"""PostHog access for analytics_ops: the CI checker's REST client for reads, the SDK for sends."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, TracebackType
from typing import Protocol

from posthog import Posthog

REPO_ROOT = Path(__file__).resolve().parents[4]
CI_ANALYTICS = REPO_ROOT / "scripts" / "ci" / "analytics.py"
QUERY_SCOPES = ("query:read", "project:read")

Row = list[object]


class PostHogReader(Protocol):
    """The reads analytics_ops makes through scripts/ci/analytics.py's PostHog client."""

    def hogql(self, query: str, values: Mapping[str, object] | None = None) -> list[Row]:
        """Run a HogQL query and return its rows."""
        ...

    def project(self) -> dict[str, object]:
        """Fetch the project, api_token included."""
        ...


class TargetName(StrEnum):
    """The PostHog projects analytics_ops may read and write."""

    PROD = "prod"
    E2E = "e2e"


@dataclass(frozen=True)
class Target:
    """One project: the file naming it, the personal key that reads it, the token that writes it."""

    project_json: Path
    key_env: str
    token_env: str

    @property
    def host(self) -> str:
        """Return the app host the project file names; the SDK maps it to the ingestion host."""
        host: str = json.loads(self.project_json.read_text(encoding="utf-8"))["host"]
        return host


TARGETS: dict[TargetName, Target] = {
    TargetName.PROD: Target(
        REPO_ROOT / "config" / "posthog" / "project.json",
        "POSTHOG_PERSONAL_API_KEY",
        "POSTHOG_PROJECT_TOKEN",
    ),
    TargetName.E2E: Target(
        REPO_ROOT / "config" / "posthog" / "e2e.json",
        "POSTHOG_E2E_PERSONAL_API_KEY",
        "POSTHOG_E2E_PROJECT_TOKEN",
    ),
}


def _load_ci_analytics() -> ModuleType:
    """Load scripts/ci/analytics.py, the one PostHog REST client in the repo, as a module."""
    spec = importlib.util.spec_from_file_location("ci_analytics", CI_ANALYTICS)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {CI_ANALYTICS}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CI_ANALYTICS = _load_ci_analytics()
# Properties the capture path adds to every event; not catalog properties.
ENVELOPE_PROPERTIES: frozenset[str] = _CI_ANALYTICS.ENVELOPE_PROPERTIES


def reader(target: Target, scopes: Sequence[str] = QUERY_SCOPES) -> PostHogReader:
    """Return a reader for target's project; exit 1 when its personal key is unset.

    The CI client prints which key is missing, where to create it and with which scopes.
    """
    client: PostHogReader | None = _CI_ANALYTICS.client_from_env(
        scopes, key_env=target.key_env, project_json=target.project_json
    )
    if client is None:
        raise SystemExit(1)
    return client


@dataclass
class Sender:
    """An SDK client that remembers every failed upload, so a run cannot end looking clean."""

    client: Posthog
    failures: list[Exception] = field(default_factory=list)

    @classmethod
    def open(cls, target: Target, read: PostHogReader) -> Sender:
        """Build a sender for target's token, refusing a token that is not the read project's own.

        Reads and writes must hit one project, or a dry run plans against one
        and the apply lands in another.
        """
        token = os.environ.get(target.token_env)
        if not token:
            raise SystemExit(f"{target.token_env} is not set: export the project token to send to")
        if read.project()["api_token"] != token:
            raise SystemExit(
                f"{target.token_env} is not the token of the project in "
                f"{target.project_json.name}; refusing to write where the plan was not read"
            )
        failures: list[Exception] = []
        client = Posthog(
            token, host=target.host, on_error=lambda error, _batch: failures.append(error)
        )
        return cls(client, failures)

    def __enter__(self) -> Sender:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Flush and stop the client even when a send raised; exit 1 on a failed upload otherwise.

        A send's own exception is left to propagate: the upload failures are
        printed, never raised over it.
        """
        self.client.shutdown()
        if not self.failures:
            return
        message = f"{len(self.failures)} PostHog upload(s) failed; first: {self.failures[0]!r}"
        if exc is not None:
            print(message, file=sys.stderr)
            return
        raise SystemExit(message)


# The most rows one query may return before a script refuses to trust it as complete.
ROW_CAP = 10_000


def hogql_complete(read: PostHogReader, query: str, values: Mapping[str, object]) -> list[Row]:
    """Run a query whose text ends in LIMIT {limit}; exit 1 if it filled the cap, as rows may be missing."""
    rows = read.hogql(query, {**values, "limit": ROW_CAP})
    if len(rows) >= ROW_CAP:
        raise SystemExit(f"a query returned {ROW_CAP} rows, its cap; the result may be partial")
    return rows
