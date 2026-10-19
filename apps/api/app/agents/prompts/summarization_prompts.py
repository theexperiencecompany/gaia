"""Prompt for folding older conversation turns into one summary message."""

# The ``{messages}`` placeholder is filled with the summarized turns (XML).
# The work still in progress is NOT in them: it stays in context verbatim after
# the summary, so this prompt asks for a record of the past and nothing else.
CONVERSATION_SUMMARY_PROMPT = """You are condensing the OLDER part of a conversation between a user and GAIA, their personal assistant, so it fits in memory.

The messages below are history. The most recent turns, including whatever is being worked on right now, are NOT included here: they stay in the conversation word for word, right after your summary. Do not summarize, restate or continue that current work.

Write a factual record of what already happened in these messages:
- What the user told GAIA about themselves, their plans and preferences: names, people, dates, places, numbers, decisions.
- What GAIA did: actions taken, tools used and their results, anything created or changed, with exact ids, titles, links and file paths.
- Requests that were finished, and anything explicitly left unresolved, stated as a fact ("not done yet: ..."), never as an instruction.

Rules:
- Past tense, plain statements. No goals, plans, next steps, advice or instructions to anyone.
- Never treat an old request as the current task. If the newest messages here still show something in progress, record only what was asked and what was done so far.
- Leave out GAIA's own operating rules, formatting conventions and persona. Only what happened in the conversation.
- Keep specifics exact. Drop small talk and repetition.
- Write it the way a sharp person takes notes: short, direct sentences or a flat list, plain words, no headings, no filler.

Reply with the summary only.

<messages>
{messages}
</messages>"""
