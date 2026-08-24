"""The AI-ism scorer has to count the tells that actually shipped.

``PROD_REPLIES`` is 20 real assistant replies pulled from the founder's own
production conversation (leading 600 characters of each, email addresses
substituted). They are the reason this module exists, so they are what it is
graded against: a detector that scores a hand-written toy string and misses the
production wording proves nothing.
"""

import pytest

from app.agents.evals.ai_isms import AiIsmScore, score_reply

PROD_REPLIES: tuple[str, ...] = (
    "on it, pinging you in 3 hours.<NEW_MESSAGE_BREAK>",
    "done, will hit you at 8:52am with the castellan free reminder.<NEW_MESSAGE_BREAK>",
    "yeah good catch, that's wrong. it's 2:52am now, so 3 hours is 5:52am, not 8:52. someone scheduled it 6 hours out. fixing it.<NEW_MESSAGE_BREAK>",
    "sorted. reminder now fires at 5:52am IST, exactly 3 hours from now. WhatsApp, once, done.<NEW_MESSAGE_BREAK>",
    "yeah, that was me. my bad. first set got scheduled 6 hours out instead of 3, so i fixed it. it's correct now, fires at 5:52am IST, your 3 hours from now. done.<NEW_MESSAGE_BREAK>",
    "brute force isn't bad in itself, it's just wrong for your stage. here's the blunt version:\n\nspraying 5 channels works when you have a machine behind it, people to run each one, or a funnel that converts whatever you throw at it. you have none of those. you're solo, and your biggest problem isn't getting people in the top, it's that 110 checkout starts become 8 payments. you're leaking 92% before money happens.\n\nso if you brute force marketing, you're paying to fill a bucket with a hole in it. more channels, more noise, more time writing posts nobody converts, and your 7% weekly growth keeps ge",
    "on twitter + youtube: real talk, it's not a bad instinct, but long-form youtube is a huge time sink and you already told me you hate making content. so let's be honest about what that actually costs you.\n\nyoutube long-form only works if you commit to it weekly for like 6 months before it pays off, and that's 10-15 hrs/week of editing you'll resent. you don't need to show 10 use cases, you need ONE demo that runs your real day and makes someone think \"holy shit I want that.\" that's a 4 minute video, shot once, and it's better than 20 polished ones. you can stretch that one video into shorts + t",
    "heyy. you up late again, it's 12:45am. can't sleep or grinding?<NEW_MESSAGE_BREAK><NEW_MESSAGE_BREAK>",
    "ok here's the real breakdown for a solo trip from Ahmedabad, 7 nights covering Srinagar, Gulmarg, Pahalgam, Sonamarg:\n\n**Budget trip: ~₹33,000 total**\n**Comfortable sweet spot: ~₹40,000-45,000**\n**Full comfort: ₹60,000+**\n\nthe big numbers:\n- flight RT AMD→Srinagar: ₹16k budget, up to 20-25k comfortable. book 45-60 days out\n- stay (7 nights): ₹7k budget, ₹18k comfortable\n- transport: ₹3.5k shared cabs, ₹9k private\n- food: ₹3k dhabas, ₹6.5k cafés\n- activities: ₹3k-8k\n\nthings worth knowing:\n- 7 nights covers all 4 towns without rushing, 6 if you drop Sonamarg\n- the big budget killers are the Gulm",
    "fair, trains cheaper and honestly nicer for that route. lemme get you the train numbers<NEW_MESSAGE_B<NEW_MESSAGE_BREAK>",
    "hey. 4:47am, you're up grinding, and you just said it out loud. that's the first honest thing you've said in a while.\n\nyou've got a genuinely insane load on you right now. YC call, SF trip looming, the whole company on your shoulders, and you're solo. anyone would be overwhelmed. that's not weakness, that's just math.\n\ndon't need to fix anything right now. just tell me what's actually eating you the most, the one thing keeping you up. we can deal with that one thing. the rest can wait till morning.<NEW_MESSAGE_BREAK>",
    "you're right, my bad. let me fix that properly.\n\n<NEW_MESSAGE_BREAK>",
    "fixed. 2k signups, 3 paying, barely any daily. 3 months in SF, not 6. that's what i'll use from now on, and i'm sorry i had it wrong.\n\nand honestly, that correction makes your fear make more sense. you're not sitting on 8k users wondering if it's good enough. you have 3 people paying you and a YC call tomorrow. that's a much scarier, much more honest place to be. so let's not pretend it's fine.\n\nhere's the thing about \"how do i tackle everything.\" you don't. that's the trap. you have like 40 open threads in your head right now and you're trying to hold all of them at once at 5am. nobody can do",
    "you're right, i don't actually know that. i pulled it from an old note saying \"YC partner call aug 20\" and just ran with it, which is exactly the kind of thing i keep messing up tonight. my bad. cross it off.\n\nforget the call then. what's actually the one thing on your plate for the next day that needs you? just the one.<NEW_MESSAGE_BREAK>",
    "ok, real talk, and i'm gonna separate the useful from the useless here.\n\n**sam altman is the wrong role model for you.** openai started with billions and the best talent on earth, it's a research lab, not a bootstrap. comparing yourself to him is like a guy with a food cart asking how jeff bezos scaled amazon. different game entirely. drop that comparison, it'll only make you feel worse.\n\nthe people you should actually look at, the ones who grew from zero with no money:\n\n**stripe.** two brothers, 21 and 19, no pedigree, no money. they won on one thing: the best developer experience, so good th",
    "straight answer: don't go fully pro, and don't give unlimited free either. both are traps for where you are.\n\nhere's why fully pro kills you: you have barely any daily users right now. that's your real crisis, not pricing. if you gate everything behind a paywall, you go from \"barely any daily users\" to \"zero daily users.\" and zero daily users means zero word of mouth, zero social proof, and nothing to show an investor. you can't raise on 3 paying users and no one using the product. fully pro is how you end up with 3 users and a dead product.\n\nbut unlimited free is also wrong, because free user",
    "good question, and here's the blunt version.\n\na \"good base\" isn't one magic number, it's the point where your growth stops being noise and starts being signal. and that's different for signups vs paying users vs daily users.\n\nfor a paid product like yours, the base that matters is **paying users and daily active users**, not signups. here's what i'd call a real base:\n\n**paying users:** 50-100. at 50 paying users at $30/mo you're at $1,500 MRR. that's still tiny, but it's a real number. 10% w/w on 50 is 5 new paying users a week, that's meaningful and it compounds. 10% w/w on 3 is 0.3 users, it",
    "yeah, i can set all that up. let me get the tasks created and the two check-ins scheduled.\n\n<NEW_MESSAGE_BREAK>",
    "all set. here's what's locked in:\n\n**8 tasks created** (in your Todoist inbox):\n- buy resend pro\n- email churned subscribers\n- email current subscribers\n- email all old users w/ discount code + the video\n- record the gaia video (separate task)\n- set up all your workflows\n- tweet about self-hosting gaia\n- tweet about the new browser feature\n\n**2 reminders, both on WhatsApp:**\n- **12pm today** — nudge that all this work needs doing\n- **12am tonight** — check-in on how much you got done\n\none heads up: task 4 and task 5 overlap (the video's referenced inside the old-users email AND is its own task",
    "sure, here's the breakdown of what i set up for you:\n\n**8 tasks** (all in your Todoist inbox, no due dates):\n1. buy resend pro\n2. send emails to churned subscribers\n3. send emails to current subscribers\n4. send emails to all old users with a discount code + the video, saying the product's better\n5. record the video of how you use gaia\n6. set up all your workflows\n7. tweet about self-hosting gaia / that you made it better\n8. tweet about the new browser feature\n\n**2 nudges, both on WhatsApp:**\n- **12pm today** — \"all this work needs to be done\" reminder listing the batch\n- **12am tonight** — che",
)

#: Counts over ``PROD_REPLIES``, summed. Recompute deliberately if the corpus
#: changes; never loosen one to make a detector edit go green.
EXPECTED_TOTALS = AiIsmScore(
    negation_antithesis=10,
    em_dash=4,
    banned_phrases=6,
    bold_emphasis=30,
    preamble=0,
    bubbles=20,
    chars=7222,
    paragraphs=46,
)


def totals_over(replies: tuple[str, ...]) -> AiIsmScore:
    scores = [score_reply(reply) for reply in replies]
    return AiIsmScore(
        negation_antithesis=sum(s.negation_antithesis for s in scores),
        em_dash=sum(s.em_dash for s in scores),
        banned_phrases=sum(s.banned_phrases for s in scores),
        bold_emphasis=sum(s.bold_emphasis for s in scores),
        preamble=sum(s.preamble for s in scores),
        bubbles=sum(s.bubbles for s in scores),
        chars=sum(s.chars for s in scores),
        paragraphs=sum(s.paragraphs for s in scores),
    )


def test_production_corpus_scores_exactly() -> None:
    assert totals_over(PROD_REPLIES) == EXPECTED_TOTALS


def test_not_one_production_reply_was_split_into_bubbles() -> None:
    """The measured symptom the prompt fix targets: 20 replies, 20 bubbles."""
    assert [score_reply(reply).bubbles for reply in PROD_REPLIES] == [1] * len(PROD_REPLIES)


@pytest.mark.parametrize(
    "text",
    [
        "it's not a reminder, it's a whole system",
        "this isn't just a busy week, it's your busiest one yet",
        "that's not weakness, that's just math",
        "not because it's hard, but because nobody asked",
        "hypergrowth is a result, not a strategy",
        "we ship on friday, not monday",
    ],
)
def test_counts_the_negation_antithesis_in_both_orders(text: str) -> None:
    assert score_reply(text).negation_antithesis >= 1


@pytest.mark.parametrize(
    "text",
    [
        "it's a whole system",
        "this is your busiest week yet",
        "we ship on friday",
        "there is no comma clause here at all",
    ],
)
def test_leaves_a_plain_sentence_alone(text: str) -> None:
    assert score_reply(text).negation_antithesis == 0


def test_counts_em_dashes() -> None:
    assert score_reply("one — two — three").em_dash == 2


@pytest.mark.parametrize(
    "text",
    [
        "here's the thing, you're solo",
        "the real question is whether anyone pays",
        "honestly, that's rough",
        "real talk, drop the comparison",
        "ok, brutally honest: it won't work",
        "good question, and here's the blunt version",
        "How can I help you today?",
        "let me know if you need anything else",
        "let me pull that up for you",
    ],
)
def test_counts_banned_phrases(text: str) -> None:
    assert score_reply(text).banned_phrases >= 1


def test_let_me_know_is_counted_once_not_twice() -> None:
    """The opener rule and the phrase list overlap on 'let me know if'; the
    exclusion in the opener pattern is what keeps one tell from scoring two."""
    assert score_reply("let me know if that works").banned_phrases == 1


def test_counts_bold_emphasis_markers() -> None:
    assert score_reply("you have a **business**, not a product").bold_emphasis == 2


@pytest.mark.parametrize(
    "text",
    [
        "Here's what I found:\n- one\n- two",
        "here is what i got for you",
        "so you're asking about your calendar tomorrow",
        "To answer your question: yes.",
    ],
)
def test_counts_preamble(text: str) -> None:
    assert score_reply(text).preamble >= 1


def test_counts_bubbles_and_ignores_empty_segments() -> None:
    assert score_reply("first<NEW_MESSAGE_BREAK>second").bubbles == 2
    assert score_reply("<NEW_MESSAGE_BREAK>").bubbles == 0
    assert score_reply("only one, no sentinel").bubbles == 1


def test_counts_a_truncated_sentinel_as_a_split() -> None:
    """Production replies get cut mid-sentinel; the intent to split is still there."""
    assert score_reply("lemme get the numbers<NEW_MESSAGE_B<NEW_MESSAGE_BREAK>ok").bubbles == 2


def test_counts_chars_and_paragraphs() -> None:
    score = score_reply("first para\n\nsecond para\n\n\nthird")
    assert score.paragraphs == 3
    assert score.chars == len("first para\n\nsecond para\n\n\nthird")


def test_total_violations_sums_the_tells_and_not_the_shape() -> None:
    score = score_reply("here's the thing — it's not a bug, it's a **feature**")
    assert score.total_violations == (
        score.negation_antithesis
        + score.em_dash
        + score.banned_phrases
        + score.bold_emphasis
        + score.preamble
    )
    assert score.total_violations > 0
