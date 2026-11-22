"""Turn prep: work a chat turn starts the moment its caller is known.

Every chat endpoint calls start_turn_prep before its own lookups, so anything
here runs alongside ingress instead of after it. It must not block: each step
only starts background work that a later stage of the turn picks up.
"""

from app.memory.fast_recall import start_query_embedding


def start_turn_prep(message: str) -> None:
    """Start the turn's background prep: today, the memory lane's query embedding."""
    start_query_embedding(message)
