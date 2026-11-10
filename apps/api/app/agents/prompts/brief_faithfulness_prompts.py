"""The prompt for the one call that checks the daily brief's rendered prose against its facts."""

BRIEF_FAITHFULNESS_PROMPT = """You check a morning brief against the facts its writer was given.

## THE FACTS (everything the writer was shown, and nothing else is true)
{facts}

## THE BRIEF
headline: {headline}
lede: {lede}
caption: {caption}
message:
{message}

Every value in ⟦ ⟧ was filled in from the facts by the system and is exactly right: never
flag one; judge the words around it.

How the facts read: an item waiting on the user or failed is theirs to act on; GAIA's work in
progress or done is GAIA's own (the brief speaks as GAIA, "I"); the calendar lists today's only
events; "N requests, one item" is one item standing for N requests, so "N requests" is true;
[COUNTS] are the only counts, needs_you counting every item waiting on the user or failed.
Check every number in the brief against them, whether it is written in digits or in words.

List every claim in the brief the facts do not support: a person, event, time, date, number,
document, app, outcome or state the facts do not state, or one they contradict. A claim that
something is clear, empty, finished or on track counts when the facts do not say so. Judge only
what the brief asserts, and only what a reader holding these facts would call false or
misleading: a fact it leaves out is not a claim, nor is a vague amount ("a few", "several")
or a loose word for when ("today", "this morning"). A fact said in other words is supported;
so is an offer, a question, a suggestion, warmth or wit that asserts nothing new.
Write each claim as the brief's words in quotes, then what the facts say instead. Return an
empty list when every claim holds.
"""
