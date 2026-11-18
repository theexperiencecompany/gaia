"""Context assembly: how long a turn waits on each section before it goes without."""

#: A section's budget unless it declares its own: a backstop against a hung
#: dependency, not a latency target; tighten from context_assemble_seconds{stage}.
CONTEXT_SECTION_BUDGET_SECONDS = 1.0
