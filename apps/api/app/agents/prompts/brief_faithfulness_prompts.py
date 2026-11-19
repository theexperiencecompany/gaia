"""The prompt for the one call that checks the daily brief's rendered prose against its facts."""

BRIEF_FAITHFULNESS_PROMPT = """You check a morning brief for false specifics, against the facts its writer was given.

## THE FACTS (everything the writer was shown; each "fact N" line is fact N)
{facts}

## THE BRIEF
headline: {headline}
lede: {lede}
caption: {caption}
message:
{message}

Every value in ⟦ ⟧ was filled in from the facts by the system and is exactly right.

How the facts read: an item waiting on the user or failed is theirs to act on; GAIA's work in
progress or done is GAIA's own (the brief speaks as GAIA, "I"); the calendar lists today's only
events, and a reminder or todo is not a calendar event; "N requests, one item" is one item
standing for N requests; [COUNTS] are the only counts.

Go through the brief and list every specific it states: a person, count, time, event,
deadline, outcome, or a state (clear, empty, free, fixed, done, sent, failed, waiting, still
in progress). Quote the brief's own words, never the facts' words. Judge each:
- holds: a fact says it, in any words. A paraphrase, a synonym ("released" for "shipped",
  "sign" for "approve"), a loose or vague amount ("a few", "a couple") and a count you can
  tally from the facts (two names listed are two people) all hold.
- contradicted: a fact says otherwise (a count that matches no [COUNTS] value and no tally of
  the fact lines; a wrong time, person or app; a calendar called
  clear that lists an event; failed work called fixed; done work called unfinished).
- absent: it names a person, event, meeting, deadline, document or outcome no fact holds.
Never list tone, wit, ordering, an offer, a question, a suggestion, anything the brief leaves
out, or a value in ⟦ ⟧. When unsure, it holds.
"""
