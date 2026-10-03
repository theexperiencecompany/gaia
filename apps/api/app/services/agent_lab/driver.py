"""AgentDriver: one interface driving a CLI inside the user's sandbox."""

from abc import ABC, abstractmethod
from typing import ClassVar

from app.db.repositories.agent_lab_sessions import agent_lab_session_repository
from app.models.agent_lab_models import (
    AgentKind,
    AgentSessionDocument,
    AgentSessionState,
    AgentSessionUpdate,
)
from app.services.sandbox import acquire_sandbox
from app.utils.errors import AppError

_COMMAND_TIMEOUT_SECONDS = 120

_TERMINAL_STATES: frozenset[AgentSessionState] = frozenset(
    {AgentSessionState.STOPPED, AgentSessionState.FAILED}
)


class AgentDriver(ABC):
    """Drives one CLI kind inside the user's sandbox; subclass per CLI (Tasks 8-10)."""

    agent_kind: ClassVar[AgentKind]

    @classmethod
    @abstractmethod
    def build_start_command(cls, prompt: str) -> str:
        """Shell command launching a session for prompt."""

    @classmethod
    @abstractmethod
    def build_message_command(cls, text: str) -> str:
        """Shell command sending a follow-up message to the session."""

    @classmethod
    @abstractmethod
    def build_stop_command(cls) -> str:
        """Shell command stopping the session."""

    @classmethod
    async def start(cls, user_id: str, prompt: str, todo_id: str) -> AgentSessionDocument:
        """Start a session for todo_id; rejects a missing todo_id before touching anything."""
        if not todo_id.strip():
            raise AppError(
                message="todo_id is required to start an agent lab session",
                why="every lab run links to a tracked todo",
                fix="pass the active todo id to lab_start",
                status_code=400,
                code="agent_lab_todo_required",
            )
        created = await agent_lab_session_repository.create(
            AgentSessionDocument(
                user_id=user_id,
                todo_id=todo_id,
                agent=cls.agent_kind,
                state=AgentSessionState.STARTING,
            )
        )
        sandbox_ref: str | None = None
        try:
            async with acquire_sandbox(user_id) as sbx:
                raw_ref: object = getattr(sbx, "sandbox_id", None)
                sandbox_ref = raw_ref if isinstance(raw_ref, str) else None
                result = await sbx.commands.run(
                    cls.build_start_command(prompt), timeout=_COMMAND_TIMEOUT_SECONDS
                )
                if result.exit_code != 0:
                    raise AppError(
                        message="agent failed to start in sandbox",
                        why="the CLI launch command exited non-zero",
                        fix="check the sandbox is healthy and retry lab_start",
                        status_code=502,
                        code="agent_lab_start_failed",
                    )
        except Exception:
            await agent_lab_session_repository.update(
                created.id,
                user_id=user_id,
                update=AgentSessionUpdate(state=AgentSessionState.FAILED),
            )
            raise
        return await cls._transition(
            created.id, user_id, AgentSessionState.RUNNING, sandbox_ref=sandbox_ref
        )

    @classmethod
    async def message(cls, user_id: str, session_id: str, text: str) -> AgentSessionDocument:
        """Send a follow-up message to a running session."""
        session = await cls._load(user_id, session_id)
        if session.state is not AgentSessionState.RUNNING:
            raise AppError(
                message="agent lab session is not running",
                why="messages only reach an actively running session",
                fix="start a new session with lab_start",
                status_code=409,
                code="agent_lab_session_not_running",
            )
        async with acquire_sandbox(user_id) as sbx:
            result = await sbx.commands.run(
                cls.build_message_command(text), timeout=_COMMAND_TIMEOUT_SECONDS
            )
            if result.exit_code != 0:
                raise AppError(
                    message="agent failed to accept the message",
                    why="the CLI message command exited non-zero",
                    fix="check lab_status, then retry or restart the session",
                    status_code=502,
                    code="agent_lab_message_failed",
                )
        return await cls._load(user_id, session_id)

    @classmethod
    async def stop(cls, user_id: str, session_id: str) -> AgentSessionDocument:
        """Stop a session; already-terminal sessions return untouched without sandbox work."""
        session = await cls._load(user_id, session_id)
        if session.state in _TERMINAL_STATES:
            return session
        async with acquire_sandbox(user_id) as sbx:
            result = await sbx.commands.run(
                cls.build_stop_command(), timeout=_COMMAND_TIMEOUT_SECONDS
            )
            if result.exit_code != 0:
                raise AppError(
                    message="agent failed to stop in sandbox",
                    why="the CLI stop command exited non-zero",
                    fix="retry lab_stop; the session state is unchanged",
                    status_code=502,
                    code="agent_lab_stop_failed",
                )
        return await cls._transition(session_id, user_id, AgentSessionState.STOPPED)

    @classmethod
    async def status(cls, user_id: str, session_id: str) -> AgentSessionDocument:
        """Report a session; probes the sandbox for live sessions, skips it for terminal ones."""
        session = await cls._load(user_id, session_id)
        if session.state in _TERMINAL_STATES:
            return session
        async with acquire_sandbox(user_id):
            pass
        return await cls._load(user_id, session_id)

    @classmethod
    async def _load(cls, user_id: str, session_id: str) -> AgentSessionDocument:
        """Fetch the caller's session; fails loud when missing or another user's."""
        session = await agent_lab_session_repository.get_for_user(session_id, user_id=user_id)
        if session is None:
            raise AppError(
                message="agent lab session not found",
                why="the id is unknown or belongs to another user",
                fix="list active sessions, then retry with a live id",
                status_code=404,
                code="agent_lab_session_not_found",
            )
        return session

    @classmethod
    async def _transition(
        cls, session_id: str, user_id: str, state: AgentSessionState, sandbox_ref: str | None = None
    ) -> AgentSessionDocument:
        """Apply a state transition; fails loud when the session vanished mid-flight."""
        update = AgentSessionUpdate(state=state, sandbox_session_ref=sandbox_ref)
        if sandbox_ref is None:
            update = AgentSessionUpdate(state=state)
        updated = await agent_lab_session_repository.update(
            session_id, user_id=user_id, update=update
        )
        if updated is None:
            raise AppError(
                message="agent lab session vanished",
                why="the session was deleted between the state change and its read-back",
                fix="start a new session with lab_start",
                status_code=404,
                code="agent_lab_session_not_found",
            )
        return updated
