"""The single entry point every agent tier uses to build its run context.

Before this, comms and the four worker tiers each built their own dynamic-context
message, and the two implementations had already drifted far enough that
subagent per-turn content was landing in the byte-stable cache prefix. There is
now one function; a tier is an argument to it.
"""

import asyncio
from dataclasses import dataclass

from langchain_core.messages import SystemMessage

from app.agents.context.section_context import SectionContext
from app.agents.context.sections import Section, sections_for
from app.agents.context.slots import (
    DYNAMIC_CONTEXT_MARKER,
    LEGACY_DYNAMIC_MARKER,
    MEMORY_RECALL_MARKER,
    PromptSlot,
    mark,
)
from app.agents.context.text import (
    STABLE_SECTION_JOIN,
    VOLATILE_BLOCK_TRUNC_MARKER,
    VOLATILE_SECTION_JOIN,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


@dataclass(frozen=True)
class AssembledContext:
    """The two system messages a tier's dynamic context becomes.

    ``stable`` holds what changes only when the user edits a preference or
    connects an integration, and sits inside the cacheable prefix. ``volatile``
    holds what was retrieved against this turn and sits at the tail of the system
    block, so it can never shift the bytes ahead of it. ``volatile`` is ``None``
    when there is nothing per-turn to say.
    """

    stable: SystemMessage
    volatile: SystemMessage | None

    def messages(self) -> list[SystemMessage]:
        return [self.stable] if self.volatile is None else [self.stable, self.volatile]


#: Backstop against a pathological volatile block blowing the context window and
#: the bill — a runaway section, not a caching mechanism: nothing here affects
#: the prompt cache, which is decided by slot ORDER (see ``slots``), not size.
#: Sections are otherwise emitted in full. Head and tail are kept — the head is
#: the agenda and journal, the tail the todo and run-binding directives that
#: carry recency value — and the middle goes.
VOLATILE_BLOCK_MAX_CHARS = 8_000
VOLATILE_BLOCK_HEAD_CHARS = 4_000
VOLATILE_BLOCK_TAIL_CHARS = 4_000


def _bounded(volatile_text: str) -> str:
    """The volatile block, clipped to :data:`VOLATILE_BLOCK_MAX_CHARS`."""
    if len(volatile_text) <= VOLATILE_BLOCK_MAX_CHARS:
        return volatile_text
    return (
        volatile_text[:VOLATILE_BLOCK_HEAD_CHARS]
        + VOLATILE_BLOCK_TRUNC_MARKER
        + volatile_text[-VOLATILE_BLOCK_TAIL_CHARS:]
    )


async def _render_section(section: Section, ctx: SectionContext) -> tuple[str, str]:
    """A section's id alongside its rendered text.

    The id travels WITH the result so nothing downstream has to re-derive which
    text belongs to which section. Gathering bare strings and pairing them back
    against the section list by position is the one place a per-turn section can
    silently land in the byte-stable block — the failure this whole package
    exists to prevent — and an off-by-one there is invisible in the output.
    """
    return section.id, await section.fetch(ctx)


async def _gather_sections(ctx: SectionContext) -> AssembledContext:
    """Gather every section that applies to ``ctx.tier`` and slot the results.

    A section that fails returns ``""`` rather than raising (see
    ``fetchers``), so a degraded context never costs the user their turn.
    """
    stable_sections = sections_for(ctx.tier, PromptSlot.DYNAMIC_STABLE)
    volatile_sections = sections_for(ctx.tier, PromptSlot.MEMORY_RECALL)

    rendered = dict(
        await asyncio.gather(
            *(_render_section(section, ctx) for section in (*stable_sections, *volatile_sections))
        )
    )

    stable_text = STABLE_SECTION_JOIN.join(
        text for section in stable_sections if (text := rendered[section.id])
    )
    volatile_text = _bounded(
        VOLATILE_SECTION_JOIN.join(
            text for section in volatile_sections if (text := rendered[section.id])
        )
    )

    log.set(
        dynamic_context={
            "tier": ctx.tier.value,
            "source": ctx.source or "web",
            "has_core_memory": bool(rendered.get("core_memory")),
            "has_memories": bool(rendered.get("memory_recall")),
            "has_gaia_knowledge": bool(rendered.get("gaia_knowledge")),
            "has_skills": bool(rendered.get("skills")),
            "has_active_todo": bool(ctx.active_todo_id),
            "execution_mode": ctx.execution_mode,
            "stable_chars": len(stable_text),
            "memory_recall_chars": len(volatile_text),
            "has_memory_recall": bool(volatile_text),
        }
    )

    return AssembledContext(
        stable=mark(
            SystemMessage(content=stable_text),
            DYNAMIC_CONTEXT_MARKER,
            # Threads checkpointed before the split resolve on this key.
            LEGACY_DYNAMIC_MARKER,
        ),
        volatile=(
            mark(SystemMessage(content=volatile_text), MEMORY_RECALL_MARKER)
            if volatile_text
            else None
        ),
    )


async def assemble_context(ctx: SectionContext) -> AssembledContext:
    """The context ``ctx.tier`` hands its model — the one entry point for it.

    Degrades to an empty stable block if the gather itself fails. That block is
    byte-stable on purpose: a persistent failure here must not produce a
    *different* prompt every minute, which would invalidate the prompt cache on
    every call on top of the original problem.
    """
    try:
        return await _gather_sections(ctx)
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error assembling agent context",
            error=str(e),
            error_type=type(e).__name__,
            tier=ctx.tier.value,
            user_id=ctx.user_id,
        )
        return AssembledContext(
            stable=mark(SystemMessage(content=""), DYNAMIC_CONTEXT_MARKER, LEGACY_DYNAMIC_MARKER),
            volatile=None,
        )
