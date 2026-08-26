"""Thresholds and copy for the comms style guard.

A 60-vs-60 A/B of the old and new static comms prompt on real production
queries was a null result: by turn 40 the model's own tell-laden replies fill
the context and outvote any instruction in the system prompt. The lever that
does move is code — score the draft against ``app.agents.evals.ai_isms`` and
make the model rewrite it, naming the fragments it has to drop.
"""

#: A comms reply is regenerated above this many scored tells. Zero: every
#: detector in ``ai_isms`` was measured on production replies before it was
#: coded, so a single hit is a real one, and the cost of being wrong is one
#: extra model call rather than a wrong answer.
STYLE_GUARD_MAX_VIOLATIONS = 0

#: Quoted fragments per detector in the correction note. Three is enough to
#: show the model the shape; the whole list would just re-send the draft.
STYLE_GUARD_MAX_SNIPPETS_PER_DETECTOR = 3

#: How each detector is described to the model. Keyed by the ``AiIsmScore``
#: field, so the note names the rule rather than the field name.
STYLE_GUARD_RULES: dict[str, str] = {
    "negation_antithesis": 'the "not X, it\'s Y" antithesis',
    "em_dash": "em dashes",
    "banned_phrases": "stock filler phrases",
    "bold_emphasis": "bold emphasis",
    "preamble": "a preamble announcing the answer instead of giving it",
    "closing_hook": "a closing offer to do the next thing",
    "template_shape": "the bold-led listicle template",
}

#: Closes the note. Rewriting is the ONLY instruction: a model told to "improve"
#: a reply also shortens it, and the facts are what must survive verbatim.
STYLE_GUARD_CORRECTION_INSTRUCTION = (
    "Rewrite the same reply without them. Keep every fact, id, link and number. "
    "Keep the bubble breaks."
)
