"""
Stale Output Clearer Middleware.

Uses Anthropic's recommended "observation masking" pattern to replace large,
stale tool output content with compact placeholders. Messages are never
removed -- only their content is replaced once enough model turns have passed.

Size-based decay: larger outputs are masked sooner because they consume more
context budget for diminishing informational value.

Two phases:
1. _turns_for_size() maps output char-length to the number of AI turns
   before the output is considered stale.
2. abefore_model() scans all ToolMessages, masks stale ones with a
   placeholder that includes a VFS re-read reference when available.
"""

import re
from typing import Any

from app.constants.summarization import (
    STALE_DEFAULT_TURNS,
    STALE_MIN_SIZE,
    STALE_SIZE_TIERS,
)
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from shared.py.wide_events import log

# Regex to extract VFS source path from HTML comment tag
_VFS_SOURCE_RE = re.compile(r"<!--\s*vfs_source:\s*(.+?)\s*-->")


class StaleOutputClearerMiddleware(AgentMiddleware):
    """
    Masks stale tool outputs with compact placeholders before model calls.

    Larger outputs are masked sooner (size-based decay). The middleware
    never removes messages -- it replaces content in-place so the
    conversation structure stays intact.

    When a VFS path is available (from compaction or an HTML comment),
    the placeholder includes a re-read reference so the model can
    retrieve the original data if needed.

    Usage:
        middleware = StaleOutputClearerMiddleware(
            never_mask_tools={"vfs_read", "vfs_write"},
        )
    """

    def __init__(
        self,
        *,
        min_size: int = STALE_MIN_SIZE,
        size_tiers: list[tuple[int, int]] | None = None,
        default_turns: int = STALE_DEFAULT_TURNS,
        never_mask_tools: set[str] | None = None,
    ) -> None:
        """
        Initialize the stale output clearer middleware.

        Args:
            min_size: Outputs below this char count are never masked.
            size_tiers: List of (max_chars_exclusive, turns_before_mask) tuples,
                        ordered ascending by max_chars_exclusive. Falls back to
                        STALE_SIZE_TIERS from constants if not provided.
            default_turns: Turns threshold for outputs larger than every tier.
            never_mask_tools: Tool names whose outputs should never be masked.
        """
        super().__init__()
        self.min_size = min_size
        self.size_tiers = size_tiers if size_tiers is not None else STALE_SIZE_TIERS
        self.default_turns = default_turns
        self.never_mask_tools = never_mask_tools or set()

    def _turns_for_size(self, size: int) -> int:
        """
        Determine how many AI turns must pass before an output of *size*
        chars is considered stale.

        Iterates through size_tiers in order; if the output is smaller than
        a tier's max_chars_exclusive, that tier's turn count is returned.
        Outputs larger than every tier use default_turns.

        Args:
            size: Character count of the tool output.

        Returns:
            Number of AI turns after which the output should be masked.
        """
        for max_chars, turns in self.size_tiers:
            if size < max_chars:
                return turns
        return self.default_turns

    @staticmethod
    def _extract_reread_ref(
        content: str, additional_kwargs: dict[str, Any]
    ) -> str | None:
        """
        Extract a VFS path that can be used to re-read the original output.

        Checks two sources in priority order:
        1. ``additional_kwargs["vfs_path"]`` -- set by VFSCompactionMiddleware.
        2. ``<!-- vfs_source: <path> -->`` HTML comment embedded in content.

        Args:
            content: The ToolMessage content string.
            additional_kwargs: The ToolMessage's additional_kwargs dict.

        Returns:
            VFS path string, or None if no reference is available.
        """
        vfs_path = additional_kwargs.get("vfs_path")
        if vfs_path:
            return str(vfs_path)

        match = _VFS_SOURCE_RE.search(content)
        if match:
            return match.group(1)

        return None

    async def abefore_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        """
        Scan messages and mask stale tool outputs before the model call.

        For each ToolMessage the method checks:
        - Is it already masked? (skip)
        - Is its tool in the never_mask set? (skip)
        - Is its content below min_size? (skip)
        - Have enough AI turns elapsed since the message? (mask)

        When masking, the original content is replaced with a compact
        placeholder that preserves tool identity, original size, and
        an optional VFS re-read path.

        Args:
            state: Current agent state containing messages.
            runtime: The langgraph Runtime (unused but required by interface).

        Returns:
            ``{"messages": new_messages}`` if any messages were masked,
            or ``None`` if no changes were made.
        """
        messages: list[Any] = list(state.get("messages", []))
        if not messages:
            return None

        # Build an index of positions where AIMessages appear.
        # This lets us count how many AI turns have happened after a given
        # message position.
        ai_indices: list[int] = [
            i for i, msg in enumerate(messages) if isinstance(msg, AIMessage)
        ]

        new_messages: list[Any] = []
        total_chars_saved = 0
        any_modified = False

        for idx, msg in enumerate(messages):
            # Only consider ToolMessages
            if not isinstance(msg, ToolMessage):
                new_messages.append(msg)
                continue

            additional_kwargs: dict[str, Any] = getattr(
                msg, "additional_kwargs", {}
            ) or {}

            # Already masked or compacted -- keep as-is
            if additional_kwargs.get("masked") or additional_kwargs.get("compacted"):
                new_messages.append(msg)
                continue

            # Never mask certain tools
            tool_name = getattr(msg, "name", None) or ""
            if tool_name in self.never_mask_tools:
                new_messages.append(msg)
                continue

            # Get content size
            content = msg.content if hasattr(msg, "content") else str(msg)
            content_str = str(content)
            content_size = len(content_str)

            # Skip small outputs
            if content_size < self.min_size:
                new_messages.append(msg)
                continue

            # Count AI turns that occurred after this message
            turns_after = sum(1 for ai_idx in ai_indices if ai_idx > idx)

            # Check against required turns for this size
            required_turns = self._turns_for_size(content_size)
            if turns_after < required_turns:
                new_messages.append(msg)
                continue

            # --- Mask this message ---

            # Try to find a re-read reference
            reread_ref = self._extract_reread_ref(content_str, additional_kwargs)

            # Build placeholder content
            size_kb = content_size / 1024
            placeholder_parts = [
                f"[{tool_name} output masked — {size_kb:.1f} KB / {content_size} chars, "
                f"{turns_after} turns ago]",
            ]
            if reread_ref:
                placeholder_parts.append(
                    f"[Re-read via: {reread_ref}]"
                )

            placeholder_content = "\n".join(placeholder_parts)

            masked_msg = ToolMessage(
                content=placeholder_content,
                tool_call_id=msg.tool_call_id,
                name=tool_name,
                id=getattr(msg, "id", None),
                additional_kwargs={
                    **additional_kwargs,
                    "masked": True,
                    "original_length": content_size,
                },
            )

            new_messages.append(masked_msg)
            total_chars_saved += content_size - len(placeholder_content)
            any_modified = True

        if not any_modified:
            return None

        log.info(
            f"StaleOutputClearer masked stale tool outputs, "
            f"saving ~{total_chars_saved} chars"
        )
        return {"messages": new_messages}
