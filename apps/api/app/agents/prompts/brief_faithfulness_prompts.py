"""The prompt for the one call that checks a brief's rendered text against its facts."""

BRIEF_FAITHFULNESS_PROMPT = """You check a brief for false specifics, against the facts its writer was given.

## THE FACTS (everything the writer was shown; a "fact N" or "N." line is fact N)
{facts}

## THE BRIEF
{brief}

Every value in ⟦ ⟧ was filled in from the facts by the system and is exactly right.

How the facts read: an item waiting on the user or failed is theirs to act on; GAIA's work in
progress or done is GAIA's own, done for the user (the brief speaks as GAIA, "I", to them), and
done work is ready for them; the calendar lists today's only
events, and a reminder or todo is not a calendar event; "N requests, one item" is one item
standing for N requests; [COUNTS] and the series' figures are the only counts; a chart's
title and takeaway speak of the series it draws. Series, quote and goal lines are facts as
much as items are: a goal holds its own words and every todo linked to it, a quote holds its
author's words.

Go through the brief one sentence at a time, and judge only the sentences that state a fact:
a name, a number, a time or date, a state (done, sent, failed, waiting, clear, still running)
or who owns or did something. Skip every other sentence whole, without listing it: a question,
advice or a judgement of what matters, a joke, an idiom or any figure of speech, tone, an
offer, a suggestion, and the user's own things named as theirs ("your dentist"). In a sentence
that states a fact, a joke or idiom around it is still skipped, and only the fact is judged.

For each fact a sentence states, quote the brief's own words, never the facts' words, and judge:
- holds: a fact says it, in any words. A paraphrase, a synonym ("released" for "shipped",
  "sign" for "approve"), a loose or vague amount ("a few", "a couple") and a count you can
  tally from the facts (two names listed are two people) all hold.
- contradicted: a fact says otherwise (a count that matches no [COUNTS] value and no tally of
  the fact lines; a wrong time, person or app; a calendar called clear that lists an event;
  failed work called fixed; done work called unfinished).
- absent: it names a person, event, meeting, deadline, document or outcome no fact holds.
A pattern a series shows (a spike, a peak, the heaviest day, a backlog building, a drop) holds
when that series' points show it. A part of the day holds against the events' clock times:
morning is before noon, so an event at 4:00 PM leaves the morning clear. A value in ⟦ ⟧, the
ordering, and anything the brief leaves out are never judged; nor is a heading or chart title
that names no person, count, time, deadline or outcome. When unsure, it holds.
"""
