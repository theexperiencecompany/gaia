"""Docstrings for memory-related tools."""

ADD_MEMORY = """
Store a new long-term memory about the user.

Use when the user explicitly asks you to remember something, or when a durable
fact surfaces that future conversations will need (preferences, relationships,
identity, commitments). The memory engine deduplicates against existing
memories and files the fact into the right folder automatically; pass `folder`
only when the user names one.

Do NOT use for one-off context that only matters this turn, or for tasks
(use todo tools for those). Memory also learns from conversations in the
background — store only what the user explicitly wants remembered.

Args:
    content: The fact to remember, written as one self-contained assertion
    folder: Optional folder path to file under (e.g. 'work/gaia'); omit to auto-categorize
    config: Runtime configuration containing user context

Returns:
    Confirmation with the memory ID, the folder it was filed under, and
    whether it was stored new, merged into a duplicate, or updated a prior fact
"""

SEARCH_MEMORY = """
Search stored memories using a natural language query.

Fast indexed recall over everything remembered about the user — semantically
similar facts rank first. Use it to recall preferences, people, plans, or any
context from past interactions. Pass `folder` to scope the search to one
folder of the memory tree (and its subfolders).

Args:
    query: The search query text
    limit: Maximum number of results to return
    folder: Optional folder path to search within (e.g. 'relationships')
    config: Runtime configuration containing user context

Returns:
    Matching memories with their IDs, folders, dates, and relevance scores.
    Use the IDs with update_memory / forget_memory.
"""

UPDATE_MEMORY = """
Correct an existing memory by ID.

Chains a new version onto the memory (the old version is kept as history but
leaves recall). Use when the user corrects a remembered fact ("actually her
birthday is March 13"). Get the ID from search_memory results.

Args:
    memory_id: ID of the memory to correct
    new_content: The corrected fact, written as one self-contained assertion
    config: Runtime configuration containing user context

Returns:
    Confirmation with the new version's ID and folder
"""

FORGET_MEMORY = """
Forget a memory by ID (soft delete).

The memory is hidden from all recall but kept internally for history. Use when
the user asks you to forget something or a fact is confirmed wrong with no
replacement. Get the ID from search_memory results.

Args:
    memory_id: ID of the memory to forget
    reason: Short reason why it is being forgotten
    config: Runtime configuration containing user context

Returns:
    Confirmation that the memory was forgotten
"""

SEARCH_JOURNAL = """
Search the episodic journal — the day-by-day log of what the user did and
what you did for them.

Answers "when did we last talk about X" or "have I worked on Y before":
recent journal lines are matched verbatim, older days through their
summaries. For a specific date, use get_journal instead.

Args:
    query: What to look for in past activity
    config: Runtime configuration containing user context

Returns:
    Matching journal lines/day summaries with their dates
"""

GET_JOURNAL = """
Read the journal page for one specific date.

Returns everything logged that day: what the user did and discussed, what you
did for them, plus the day summary if the day is over. Use for questions like
"what did we do three weeks ago?" or "what happened on May 21?" — compute the
date first, then call this.

Args:
    date: The day to read, as YYYY-MM-DD
    config: Runtime configuration containing user context

Returns:
    That day's timestamped journal entries and summary, or a note that the
    day has no entries
"""

READ_MEMORY_DOCUMENT = """
Read one of the core memory documents maintained about the user.

Documents: 'user' (identity & life context), 'memory' (how to assist them:
tone, conventions, preferences), 'agenda' (open loops: projects, commitments,
deadlines), 'people' (relationship register incl. key dates), 'insights'
(observed patterns and routines). user/memory/agenda are already injected
into your context every turn — read 'people' and 'insights' when you need
depth.

Args:
    doc_type: Which document: 'user', 'memory', 'agenda', 'people', or 'insights'
    config: Runtime configuration containing user context

Returns:
    The document's full markdown content
"""

UPDATE_MEMORY_DOCUMENT = """
Rewrite one of the core memory documents (full replace, versioned).

Replaces the entire document with the provided markdown and bumps its
version (prior versions are kept as history). Read the current document
first and carry over everything still true — this is a rewrite, not an
append. The documents are also maintained automatically in the background;
use this only when the user asks for a change or a document is clearly wrong.

Args:
    doc_type: Which document: 'user', 'memory', 'agenda', 'people', or 'insights'
    content: The complete new markdown content for the document
    config: Runtime configuration containing user context

Returns:
    Confirmation with the document's new version number
"""
