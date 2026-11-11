"""The prompt for the one call that checks a brief's rendered text against its facts."""

BRIEF_FAITHFULNESS_PROMPT = """You check a brief for false specifics, against the facts its writer was given.

## THE FACTS (everything the writer was shown; a "fact N" or "N." line is fact N)
{facts}

## THE BRIEF
{brief}

Every value in ⟦ ⟧ was filled in from the facts by the system and is exactly right.

How the facts read: an item waiting on the user or failed is theirs to act on; GAIA's work in
progress or done is GAIA's own, done for the user (the brief speaks as GAIA, "I", to them); the calendar lists today's only
events, and a reminder or todo is not a calendar event; "N requests, one item" is one item
standing for N requests; [COUNTS] and the series' figures are the only counts; a chart's
title and takeaway speak of the series it draws. Series, quote and goal lines are facts as
much as items are: a goal holds its own words and every todo linked to it, a quote holds its
author's words.

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
out, or a value in ⟦ ⟧. A heading or a chart title names what follows ("Ready when you are",
"Money", "This week's meetings"): one that names no person, count, time, deadline or outcome is
not a specific, so it is never listed. When unsure, it holds.
"""
