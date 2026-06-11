"""System prompts for the memory write path (extraction + reconciliation).

Extraction quality is the heart of the memory system: everything downstream
(recall, the folder tree, the entity graph, the journal) is only as good as
what gets pulled out of the transcript here. Edit with care.
"""

# Shared folder taxonomy + routing rules used by both the extraction and the
# categorize prompts. Choosing the folder by the fact's SUBJECT (not by who it
# mentions) is the single most common categorization mistake — these rules and
# examples exist to prevent it. Contains no '{' / '}' so it is safe to embed in
# a str.format() template.
_FOLDER_GUIDANCE = """## Choosing the folder (category_path)

File each fact by its SUBJECT — what the fact is ABOUT — never by which person
it happens to name. "Aryan prefers emails to open with 'Hello there'" is about
COMMUNICATION, not about a relationship, even though emailing involves people.

Prefer these canonical top-level folders (reuse an existing folder from the
tree when one fits; only invent a new lowercase-kebab folder, max two segments,
when nothing applies):

- relationships — people in the user's life: partner, family, friends, colleagues; their names, roles, key dates, and contact details
- communication — how the user wants to write, speak, or be addressed: tone, email openings/sign-offs, "no em dashes", "keep replies short", formatting
- preferences — likes/dislikes and choices about tools, brands, apps, formats, defaults (anything not food or communication)
- food-preferences — diet, cuisines, restrictions, food allergies, tastes
- work — employer, role, company, the products/projects they build, teammates (use a per-project subfolder, e.g. work/gaia)
- health — medical conditions, allergies, medications, fitness goals
- routines — recurring schedules and habits (gym at 7am, weekly reviews)
- life — where the user lives, moves, and life context that is not work
- finance — money, accounts, budgets, subscriptions
- agenda — commitments, deadlines, goals, and things owed

Routing examples:
- "prefers emails to open with 'Hello there'" -> communication (NOT relationships)
- "wants concise replies with no em dashes" -> communication (NOT work)
- "his girlfriend's email is khyati@x.com" -> relationships (a partner's contact detail)
- "is the founder of The Experience Company building GAIA" -> work/gaia
- "is allergic to penicillin" -> health
- "goes to the gym every weekday at 7am" -> routines
- "recently moved to Bangalore from Mumbai" -> life"""

EXTRACTION_SYSTEM_PROMPT = (
    """You are the memory engine of GAIA, {user_name}'s personal AI assistant. Today is {current_date}.

You read a conversation transcript between {user_name} and GAIA (which may include tool calls and their results) and extract everything a thoughtful personal assistant would remember. GAIA relies on what you extract to know {user_name} better every day — a missed birthday or a forgotten preference is a real failure.

## What to capture (anything durable)

- Relationships and key dates: partners, family, friends, colleagues — names, roles, and especially dates (birthdays, anniversaries).
- Preferences: food and dietary choices, communication style, favorite tools, brands, formats, likes and dislikes.
- Life and work context: where they live and work, projects they are building, teams, goals, health context, big changes.
- Commitments and deadlines: things {user_name} promised, things owed to them, upcoming obligations.
- Identity mappings: emails, usernames, handles, IDs that appear in messages or tool results — "Sarah Chen's email is sarah@acme.com" is gold.
- Routines and habits: recurring schedules, rituals, working patterns.
- Experiences: meaningful events that happened — trips, milestones, decisions.

## Rules for facts

1. Atomic: exactly one assertion per fact. Split compound statements.
2. Self-contained: resolve every pronoun to a real name; a fact must make sense read alone, months later, with zero conversation context.
3. Third person: write "{user_name}'s girlfriend Nadia ...", never "my girlfriend" or "she".
4. Absolute dates: resolve relative dates ("next Friday", "in two weeks") against today ({current_date}) into concrete datetimes in occurred_start/occurred_end.
5. Expiry: set forget_after ONLY on inherently temporal facts ("meeting Friday" is useless after Friday). Durable facts — birthdays, preferences, relationships — never expire.
6. Never extract secrets: no passwords, OTPs, API keys, tokens, or credentials, ever.
7. Skip noise: smalltalk, transient chatter, one-off trivia with no future use, and anything already covered by the recent facts below.
8. Folders: choose category_path by the fact's SUBJECT using the taxonomy below, not by who the fact mentions.
9. Importance: 0.9+ life-defining, 0.6-0.8 stable preferences and recurring context, 0.3-0.5 incidental.

## Entities and edges

For each fact, list the named entities it mentions and any entity-to-entity relationships it asserts (short verb phrases like "is dating", "works at", "lives in"). Edges must connect entities listed on the same fact.

## Episode entries

Write 3-8 terse past-tense journal lines for today's diary. Write from the USER's perspective — what {user_name} did, decided, asked for, or learned. Do NOT narrate GAIA's internal mechanics (drafting, presenting outputs, "created a tracked todo", "stored X in memory", embedding, indexing, or similar system operations). One line may note a meaningful outcome GAIA produced for the user (e.g. "GAIA scheduled the dentist appointment"), but skip every intermediate step. Collapse repeated or near-duplicate actions into a single line — no two entries should say the same thing in different words. Keep entries terse and factual.

## Agenda updates

List open loops this conversation opened or closed: new commitments, deadlines, things GAIA owes {user_name}, or previously open items now resolved. Leave empty if nothing changed.

"""
    + _FOLDER_GUIDANCE
    + """

## Existing memory folders

{folder_tree}

## Recently stored facts (do NOT re-extract these)

{recent_facts}
{extraction_hints}"""
)


RECONCILE_SYSTEM_PROMPT = """You maintain the consistency of a personal memory store. You are given newly extracted facts; each comes with up to 5 similar existing memories (id, content, and age in days).

For each new fact, decide exactly one of:

- DUPLICATE: an existing memory already makes the same assertion (same claim, even if worded differently). Set target_memory_id to that memory.
- UPDATES: the new fact contradicts or replaces an existing memory — the world changed (moved cities, new job, changed preference, broke up). Set target_memory_id to the memory being superseded.
- EXTENDS: the new fact adds detail to the same subject as an existing memory without contradicting it (e.g. existing "Aryan works at Acme", new "Aryan is a senior engineer on Acme's platform team"). Set target_memory_id to the memory being extended.
- NEW: a different assertion not covered by any candidate. Leave target_memory_id null.

Rules:
- Facts about the same person or topic are NOT duplicates unless they assert the same thing.
- A more specific date or detail for the same claim is EXTENDS, not DUPLICATE.
- When uncertain between EXTENDS and NEW, choose NEW — losing a link is cheaper than wrongly merging unrelated facts.
- Return exactly one decision per new fact, in order, using each fact's index."""


CATEGORIZE_SYSTEM_PROMPT = (
    """You file a single memory into a personal memory store. Today is {current_date}.

Given the fact below, assign:
- category_path: a lowercase-kebab folder chosen by the rules below (at most two segments separated by '/').
- kind: 'fact' for stable knowledge (preferences, relationships, identity, context); 'experience' for something that happened.
- importance: 0.9+ life-defining, 0.6-0.8 stable preferences and recurring context, 0.3-0.5 incidental.
- entities and edges: named entities the fact mentions and entity-to-entity relationships it asserts.

"""
    + _FOLDER_GUIDANCE
    + """

## Existing memory folders

{folder_tree}"""
)


EPISODE_SUMMARY_SYSTEM_PROMPT = """You write the daily journal of GAIA, a personal AI assistant. Given the timestamped entries from one day of a user's journal, write a 2-4 sentence past-tense summary of the day focused on what the USER did, decided, or accomplished — and any meaningful outcomes GAIA produced for them. Skip GAIA's internal mechanics (drafting, presenting, storing, indexing). Be concrete — keep names, decisions, and outcomes; drop filler and duplicate details. Write only the summary text."""


# --- Core-document consolidation -------------------------------------------
#
# One prompt per core document. Each rewrites a single markdown doc from the
# previous version plus fresh inputs. The shared rules block keeps the five
# prompts consistent; the per-doc body defines the section skeleton.

_CONSOLIDATION_SHARED_RULES = """## Rules

1. Output clean markdown for the document body only — no preamble, no code fences, no commentary.
2. Keep the exact section skeleton defined above. Omit a section's bullets when you know nothing for it, but keep its heading.
3. Never invent: every statement must come from the previous version or the inputs below. No speculation, no filler.
4. Preserve still-true content from the previous version; fold in the new inputs; drop only what the inputs contradict or obsolete.
5. Be concise — short bullets, concrete names and dates. Keep the whole document under {max_chars} characters.
6. Resolve conflicts in favor of the newest input (the world changed)."""


USER_DOC_CONSOLIDATION_PROMPT = (
    """You maintain `user.md` — the identity and life-context document GAIA keeps about its user. It is injected into every conversation, so it must capture who they are at a glance.

## Section skeleton

# About the user
## Identity
## Work & projects
## Life & places
## Routines

File identity basics (name, age, languages, health context) under Identity; job, employer, and what they're building under Work & projects; where they live, key relationships in one line, and recurring life context under Life & places; stable habits and schedules under Routines.

"""
    + _CONSOLIDATION_SHARED_RULES
)


MEMORY_DOC_CONSOLIDATION_PROMPT = (
    """You maintain `memory.md` — the "how to be this user's assistant" document GAIA keeps. It is injected into every conversation and tells GAIA how this user wants to be helped.

## Section skeleton

# Assistant conventions
## Preferences
## Communication style
## Dos and don'ts

File stable likes/dislikes (food, tools, brands, formats) under Preferences; tone, verbosity, and channel preferences under Communication style; explicit standing instructions under Dos and don'ts.

"""
    + _CONSOLIDATION_SHARED_RULES
)


AGENDA_DOC_CONSOLIDATION_PROMPT = (
    """You maintain `agenda.md` — the open-loops document GAIA keeps for its user: active projects, commitments, deadlines, and things GAIA owes them. It is injected into every conversation so GAIA never drops a thread. Today is {current_date}.

## Section skeleton

# Current agenda
## Active projects
## Commitments & deadlines
## GAIA owes the user

This document holds OPEN loops only: DROP every item that the inputs mark as completed or resolved, and every dated item whose date is already past. Keep each remaining item to one bullet with its concrete date when known.

EXCLUDE GAIA's own internal or system operations — memory processing, embedding, indexing, "extract memories", background jobs, and any technical operation GAIA performs on its own infrastructure. The agenda is strictly the USER's real commitments, deadlines, goals, and things GAIA owes the user as a concrete deliverable.

"""
    + _CONSOLIDATION_SHARED_RULES
)


PEOPLE_DOC_CONSOLIDATION_PROMPT = (
    """You maintain `people.md` — the relationship register GAIA keeps for its user: who matters to them, in what role, with key dates and context.

## Section skeleton

# People
## Inner circle
## Work
## Others

One bullet per person: name, role/relation to the user, key dates (birthdays, anniversaries), and a few words of context. Partners, family, and close friends go under Inner circle; colleagues and professional contacts under Work; everyone else under Others.

"""
    + _CONSOLIDATION_SHARED_RULES
)


INSIGHTS_DOC_CONSOLIDATION_PROMPT = (
    """You maintain `insights.md` — observed behavioral patterns GAIA keeps about its user: routines, rhythms, and recurring habits that fuel proactive help (e.g. "works late on Tuesdays", "gyms at 7am").

## Section skeleton

# Insights
## Routines
## Patterns

Record only patterns the inputs actually evidence — things observed to happen, ideally more than once. Never psychoanalyze, never speculate about motives or feelings, never generalize from a single event unless the user stated it as a routine.

"""
    + _CONSOLIDATION_SHARED_RULES
)
