"""What a brief's composition and voice are told when a check sends their answer back.

Each problem names where it is and what to change, so the retry can act on it alone.
"""

#: Where a problem is: one block of the composition, and one item in it.
BLOCK_AT = "block {number} ({kind})"
ITEM_AT = "{where}, item {id}"
#: The prose field a slot problem is in: a block's own field, or one item's.
BLOCK_FIELD = "{where} {name}"
ITEM_FIELD = "{where} item {id} {name}"

NO_TEXT = "{where}: no {name}"
TEXT_TOO_LONG = "{where}: a {name} of {length} characters, over {limit}"

NO_POOL_ITEM = "{at}: no item {id} in the pool"
DETAIL_TOO_LONG = "{at}: a detail over {limit} characters"
ACTION_OR_OUTCOME = (
    "{at}: give exactly one of action (it needs the user) or outcome (it got somewhere)"
)
LINE_GIVES_OUTCOME = "{at}: its line gives outcome {outcome}, so it is placed as that outcome"
LINE_GIVES_ACTION = "{at}: its line gives action {action}, so it is placed as that action"
EVENT_ONLY_LEADS = "{at}: a calendar event can only lead; the edition draws the day's calendar"

TREND_TOO_SHORT = "a {chart} needs a time series of at least {days} days"
SPARK_ONE_SERIES = "a spark draws one series"
LINE_TOO_MANY_SERIES = "a line draws at most {limit} series"
LINE_UNSHARED_DAYS = "a line over several series needs them to share their days"
LINE_ONE_UNIT = "a line draws one unit"
MIXED_UNITS = "{subject}, not {units}"
NO_UNIT = "no unit"
TOO_MANY_BARS = "a {chart} draws at most {limit} bars, not {bars}"
BAR_ONE_SERIES = "a bar draws one series; stack several"
STACK_NEEDS_SHARED_SERIES = (
    "a stacked_bar needs two or more series sharing their days or categories"
)
STACK_ONE_UNIT = "a stacked_bar stacks one unit"

NO_POOL_SERIES = "{where}: no series {ids} in the pool"
NO_SERIES_IDS = "{where}: no series_ids"
CHART_MISFIT = "{where}: {misfit}"

LEAD_NOT_FIRST = "{where}: a lead opens the brief, so it is block 1"
LEAD_WITHOUT_ACTION = "{where}: a lead is something to act on, so its item has an action"
LEAD_GAIA_CANNOT_ACT = (
    "{where}: GAIA can only read {app}, so it cannot help with item {id}; lead with "
    "something GAIA can act on, or with nothing"
)
LEAD_IS_BACKLOG = (
    "{where}: item {id} is an undated todo on their list, background that never leads; "
    "lead with something that needs them today, or with nothing"
)

ITEM_IN_WRONG_GROUP = "{at} has {said}, which {group} group does not hold; {home}"
ITEM_SIDE = "{side} {value}"
#: A group state with its article, as "which a done group does not hold" says it.
A_STATE = "a {state}"
AN_STATE = "an {state}"
MOVE_TO_GROUP = "move it to {group} group"
FAILED_NEEDS_RETRY = "a failed item needs the user: give it action retry in a needs_you group"

NO_POOL_QUOTE = "{where}: no quote {id} in the pool"
NO_POOL_GOAL = "{where}: no goal {id} in the pool"

#: How a placed id is named when a composition places it twice.
PLACED_ITEM = "item {id}"
PLACED_SERIES = "series {id}"
PLACED_QUOTE = "quote {id}"
PLACED_GOAL = "goal {id}"
PLACED_TWICE = "placed more than once: {ids}"
SHARED_HEADING = (
    "blocks {blocks} share the heading {heading!r}; a heading names one section, so give each "
    "group one that says what sets it apart"
)

TOO_MANY_ITEMS = "{count} items in all; a brief holds at most {limit}"
TOO_MANY_CHARTS = "{count} charts; a brief holds at most {limit}"
TOO_MANY_LEADS = "{count} leads; a brief has at most one"

NO_SUCH_FACT = "{slot} is no fact shown today"
COUNT_HAS_NO_FIELD = "{written}: a count slot has no field"
NO_SUCH_COUNT = "{slot} is not a count the facts list (offered: {offered})"
NO_COUNTS_OFFERED = "none today"
NO_SUCH_SERIES = "{written}: {id} is no series shown today"
SERIES_FIELDS = "{written}: series {id} offers {fields}, as {form}"
FACT_HAS_NO_FIELD = "{written}: fact {id} has no {field}"
FACT_SLOT_FORMS = "{written}: a fact slot is {forms}"

SLOT_PROBLEM = "the {field}: {problem}"
TYPED_SLOT_FIGURE = (
    "the {field} types {word!r} itself; write {slots} where it says {word}, with nothing of "
    "{rendered} beside it"
)
TYPED_LOOSE_FIGURE = (
    "the {field} types {word!r}, a figure no fact carries; say it in words, from the "
    "facts, or leave it out"
)
ECHOED_FIGURE = (
    "the {field} writes {echoed!r} after {slot}, which already renders {value!r}; drop it"
)
COUNT_OF_ONE_PLURAL = (
    "the {field} says {slot} (1) with {verb!r}; a count of one takes the singular: {singular!r}"
)
DAY_AT_TIME = (
    "the {field} says 'at' before {slot}, which renders the day {day!r}; a day takes no 'at': "
    "drop it"
)
ECHOED_TITLE = "the {field} names {title!r} in words and again with {slot}; keep one"
MALFORMED_SLOT = "the {field} has a malformed slot {written!r}; write {forms} exactly"
TYPED_ADDRESS = "the {field} writes the address {address!r}; link a phrase with ({fact}:N)"
