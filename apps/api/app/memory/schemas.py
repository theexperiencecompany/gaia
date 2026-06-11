"""Structured-output schemas for the memory extraction and reconcile LLM calls.

These models are internal to the write path (``app.memory.extraction``).
Their Field descriptions are part of the prompt — the LLM reads them when
filling the schema, so they are written to steer extraction quality, not
just to document the code. The public API contract lives in
``app.models.memory_models``.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.constants.memory import MemoryEntityType, MemoryKind, ReconcileOutcome


class ExtractedEntity(BaseModel):
    """A named entity mentioned by a fact (person, place, project, ...)."""

    name: str = Field(
        description=(
            "Canonical name of the entity exactly as the user refers to it, "
            "e.g. 'Nadia', 'Acme Corp', 'San Francisco', 'GAIA'. Use the most "
            "complete form seen in the conversation (prefer 'Sarah Chen' over 'Sarah')."
        )
    )
    entity_type: MemoryEntityType = Field(
        description="What kind of thing this entity is: person, place, organization, project, topic, or other."
    )


class ExtractedEdge(BaseModel):
    """A directed relationship between two entities, with provenance in the fact."""

    source: str = Field(
        description="Name of the source entity. Must match the name of an entity listed on the same fact."
    )
    relationship: str = Field(
        description=(
            "Short lowercase verb phrase describing how source relates to target, "
            "e.g. 'is dating', 'works at', 'lives in', 'is building', 'manages'."
        )
    )
    target: str = Field(
        description="Name of the target entity. Must match the name of an entity listed on the same fact."
    )


class ExtractedFact(BaseModel):
    """One atomic, durable fact extracted from the conversation."""

    content: str = Field(
        description=(
            "The fact as a single atomic assertion: one claim only, fully "
            "self-contained, written in third person with all pronouns resolved "
            "to real names, and including concrete names and absolute dates. "
            "Example: \"Aryan's girlfriend Nadia's birthday is March 12.\" "
            "Never write vague fragments like 'likes it' or 'her birthday is soon'."
        )
    )
    kind: MemoryKind = Field(
        description=(
            "'fact' for stable knowledge about the user and their world "
            "(preferences, relationships, identity mappings, context); "
            "'experience' for something that happened (an event, a trip, a decision made)."
        )
    )
    category_path: str = Field(
        description=(
            "Folder this fact files under, lowercase-kebab-case, at most two "
            "segments separated by '/', e.g. 'relationships', 'food-preferences', "
            "'work/gaia'. You MUST reuse an existing folder from the provided "
            "folder tree whenever one fits; only create a new folder when nothing "
            "existing is appropriate."
        )
    )
    entities: list[ExtractedEntity] = Field(
        default_factory=list,
        description="Named entities this fact mentions. Empty if the fact mentions none.",
    )
    edges: list[ExtractedEdge] = Field(
        default_factory=list,
        description=(
            "Entity-to-entity relationships this fact asserts, using names from "
            "'entities'. Empty if the fact asserts no relationship."
        ),
    )
    occurred_start: datetime | None = Field(
        default=None,
        description=(
            "When the described event starts/started, as an absolute datetime "
            "resolved against today's date. Null for timeless facts like preferences."
        ),
    )
    occurred_end: datetime | None = Field(
        default=None,
        description="When the described event ends/ended, if it spans time. Usually null.",
    )
    forget_after: datetime | None = Field(
        default=None,
        description=(
            "Set ONLY for inherently temporal facts that become useless after a "
            "point in time (e.g. 'has a dentist appointment Friday' expires after "
            "Friday). Null for everything durable — birthdays, preferences, and "
            "relationships never expire."
        ),
    )
    importance: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How much this fact matters long-term: 0.9-1.0 life-defining "
            "(partner, job, home city, health), 0.6-0.8 stable preferences and "
            "recurring context, 0.3-0.5 incidental but worth keeping."
        ),
    )


class ExtractedMemoryBatch(BaseModel):
    """Everything the extractor pulls out of one conversation."""

    facts: list[ExtractedFact] = Field(
        default_factory=list,
        description="All durable atomic facts extracted from the conversation. Empty if nothing is worth remembering.",
    )
    episode_entries: list[str] = Field(
        default_factory=list,
        description=(
            "3-8 terse past-tense journal lines covering what the user did or "
            "discussed AND what GAIA did for them, e.g. 'Asked GAIA to draft a "
            "birthday email for Nadia' / 'GAIA scheduled the dentist appointment "
            "for Friday 3pm'."
        ),
    )
    agenda_updates: list[str] = Field(
        default_factory=list,
        description=(
            "Open loops opened or closed in this conversation — new commitments, "
            "deadlines, things GAIA owes the user, or previously open items now "
            "resolved. Empty if the conversation changed no open loops."
        ),
    )


class ReconcileDecision(BaseModel):
    """How one newly extracted fact relates to the existing memory store."""

    new_fact_index: int = Field(
        description="Zero-based index of the new fact this decision is about."
    )
    decision: ReconcileOutcome = Field(
        description=(
            "DUPLICATE if an existing memory already makes the same assertion; "
            "UPDATES if the new fact contradicts or replaces an existing memory "
            "(e.g. moved cities, changed preference); EXTENDS if it adds detail "
            "to the same subject without contradicting; NEW if it is a different "
            "assertion. When uncertain between EXTENDS and NEW, choose NEW."
        )
    )
    target_memory_id: str | None = Field(
        default=None,
        description=(
            "ID of the existing memory this decision targets. Required for "
            "DUPLICATE, UPDATES and EXTENDS; null for NEW."
        ),
    )

    @model_validator(mode="after")
    def _require_target_unless_new(self) -> "ReconcileDecision":
        """Downgrade to NEW if the LLM picked a relation but omitted the target."""
        if self.decision is not ReconcileOutcome.NEW and self.target_memory_id is None:
            self.decision = ReconcileOutcome.NEW
        return self


class ReconcileBatchResult(BaseModel):
    """One reconcile decision per new fact, in fact order."""

    decisions: list[ReconcileDecision] = Field(
        default_factory=list,
        description="Exactly one decision for every new fact, ordered by new_fact_index.",
    )
