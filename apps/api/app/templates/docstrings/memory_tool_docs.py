"""Docstrings for memory-related tools."""

ADD_MEMORY = """
Store a new long-term memory about the user. Use when the user explicitly asks
to remember something, or a durable fact surfaces (preferences, relationships,
identity, commitments). The engine deduplicates and files automatically; pass
folder only when the user names one.
"""

SEARCH_MEMORY = """
Search stored memories by natural-language query. Recall preferences, people,
plans, or past context. Returns matching memories with IDs (use with
update_memory / forget_memory).
"""

UPDATE_MEMORY = """
Correct an existing memory by ID (from search_memory). Chains a new version on;
the old leaves recall.
"""

FORGET_MEMORY = """
Forget a memory by ID (soft delete — hidden from recall, kept for history).
"""

SEARCH_JOURNAL = """
Search the episodic journal (the day-by-day activity log). For a specific
date use get_journal.
"""

GET_JOURNAL = """
Read one day's journal page (timestamped entries + summary). date as YYYY-MM-DD.
"""

READ_MEMORY_DOCUMENT = """
Read a core memory document. Types: user (identity), memory (how to assist),
agenda (open loops), people (relationships), insights (patterns).
"""

UPDATE_MEMORY_DOCUMENT = """
Rewrite a core memory document (full replace, versioned). Read it first and
carry over everything still true.
"""
