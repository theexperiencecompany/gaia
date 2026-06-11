"""Adversarial recall tests — hybrid retrieval against a real seeded corpus.

The corpus deliberately plants distractors with overlapping vocabulary
("Nadia loves Italian food" / "Aryan ate Italian in SF" / "Marco is Aryan's
Italian colleague") so the rerank stage has to actually discriminate, not
just match keywords. Everything runs against real Postgres FTS, real Chroma
ANN and the real fastembed cross-encoder; only ingestion-time LLM calls are
canned (and none of these tests need one).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import time

import pytest

from app.memory.engine import memory_engine
from app.models.memory_models import MemorySearchResult
from tests.memory.store import (
    MemorySpec,
    chroma_user_vector_ids,
    chroma_vector_metadata,
    fetch_memory_rows,
    seed_memories,
)

pytestmark = pytest.mark.memory

_BIRTHDAY_FACT = "Aryan's girlfriend Nadia's birthday is March 12."
_NADIA_ITALIAN = "Nadia loves Italian food."
_SF_ITALIAN_DISTRACTOR = "Aryan ate Italian food in San Francisco last week."
_MARCO_DISTRACTOR = "Marco is Aryan's Italian colleague on the platform team."
_JIRA_FACT = "Aryan's Jira ticket PROJ-4821 tracks the auth service refactor."

# 60+ memories across 10 folders. Several share vocabulary on purpose.
_CORPUS: list[MemorySpec] = [
    # relationships (7)
    {"content": _BIRTHDAY_FACT, "category": "relationships", "importance": 0.9},
    {"content": _NADIA_ITALIAN, "category": "relationships"},
    {
        "content": "Aryan and Nadia celebrated their second anniversary in October.",
        "category": "relationships",
    },
    {
        "content": "Nadia works as a pediatric nurse at Manipal Hospital.",
        "category": "relationships",
    },
    {"content": "Nadia is allergic to shellfish.", "category": "relationships", "importance": 0.8},
    {"content": "Aryan's sister Priya lives in Toronto.", "category": "relationships"},
    {"content": "Aryan's mother calls him every Sunday evening.", "category": "relationships"},
    # food-preferences (6)
    {"content": "Aryan is vegetarian.", "category": "food-preferences", "importance": 0.9},
    {"content": _SF_ITALIAN_DISTRACTOR, "category": "food-preferences"},
    {"content": "Aryan likes oat-milk lattes.", "category": "food-preferences"},
    {"content": "Aryan dislikes overly sweet desserts.", "category": "food-preferences"},
    {
        "content": "Aryan's favorite restaurant in Bengaluru is Burma Burma.",
        "category": "food-preferences",
    },
    {
        "content": "Aryan drinks two coffees a day, one before standup.",
        "category": "food-preferences",
    },
    # work (7)
    {"content": _MARCO_DISTRACTOR, "category": "work"},
    {"content": _JIRA_FACT, "category": "work"},
    {
        "content": "Aryan works as a software engineer at TechNova.",
        "category": "work",
        "importance": 0.9,
    },
    {"content": "Aryan's manager is Deepika Rao.", "category": "work"},
    {"content": "Aryan presents the quarterly platform review every January.", "category": "work"},
    {"content": "Aryan mentors two junior engineers, Rohan and Sam.", "category": "work"},
    {"content": "Aryan's standup is at 9:30 every weekday morning.", "category": "work"},
    # work/gaia (4)
    {
        "content": "Aryan is building GAIA, a personal AI assistant.",
        "category": "work/gaia",
        "importance": 0.9,
    },
    {"content": "GAIA's backend uses FastAPI and LangGraph.", "category": "work/gaia"},
    {
        "content": "Aryan plans to launch GAIA's mobile app in the third quarter.",
        "category": "work/gaia",
    },
    {"content": "GAIA stores canonical memory records in Postgres.", "category": "work/gaia"},
    # health (6)
    {
        "content": "Aryan goes to the gym at 7am on Mondays, Wednesdays and Fridays.",
        "category": "health",
    },
    {"content": "Aryan is mildly lactose intolerant but tolerates oat milk.", "category": "health"},
    {"content": "Aryan's optometrist appointment is every six months.", "category": "health"},
    {"content": "Aryan takes vitamin D supplements daily.", "category": "health"},
    {"content": "Aryan sleeps around midnight and wakes at 7:30am.", "category": "health"},
    {
        "content": "Aryan had knee surgery in 2021 and avoids running on concrete.",
        "category": "health",
    },
    # travel (6)
    {"content": "Aryan visited Lisbon in May and loved the tram rides.", "category": "travel"},
    {
        "content": "Aryan keeps a travel wishlist topped by Japan in cherry blossom season.",
        "category": "travel",
    },
    {"content": "Aryan prefers window seats on flights.", "category": "travel"},
    {"content": "Aryan has a Global Entry membership expiring in 2027.", "category": "travel"},
    {
        "content": "Aryan's preferred airline is Air India for domestic flights.",
        "category": "travel",
    },
    {"content": "Aryan gets motion sick on long bus rides.", "category": "travel"},
    # hobbies (6)
    {"content": "Aryan plays badminton on Saturday mornings.", "category": "hobbies"},
    {"content": "Aryan is learning to play the guitar.", "category": "hobbies"},
    {"content": "Aryan photographs street markets on weekend walks.", "category": "hobbies"},
    {"content": "Aryan reads science fiction before bed.", "category": "hobbies"},
    {"content": "Aryan maintains a sourdough starter named Doughvid.", "category": "hobbies"},
    {"content": "Aryan collects mechanical keyboards.", "category": "hobbies"},
    # finance (6)
    {"content": "Aryan's rent is due on the 5th of every month.", "category": "finance"},
    {"content": "Aryan invests monthly through a SIP on the 10th.", "category": "finance"},
    {"content": "Aryan splits utility bills with his flatmate Karan.", "category": "finance"},
    {"content": "Aryan's credit card statement closes on the 18th.", "category": "finance"},
    {"content": "Aryan is saving for a Japan trip next spring.", "category": "finance"},
    {"content": "Aryan uses Splitwise to track shared expenses.", "category": "finance"},
    # home (6)
    {
        "content": "Aryan lives in an apartment in Indiranagar, Bengaluru.",
        "category": "home",
        "importance": 0.9,
    },
    {"content": "Aryan's flatmate Karan works night shifts.", "category": "home"},
    {
        "content": "Aryan's apartment has a balcony garden with chillies and basil.",
        "category": "home",
    },
    {"content": "Aryan's landlord prefers rent via bank transfer.", "category": "home"},
    {"content": "Aryan's wifi router is in the living room closet.", "category": "home"},
    {"content": "Aryan's building has a power backup generator.", "category": "home"},
    # education (5)
    {"content": "Aryan graduated from BITS Pilani in computer science.", "category": "education"},
    {
        "content": "Aryan is taking an online course on distributed systems.",
        "category": "education",
    },
    {"content": "Aryan attended a LangGraph workshop in March.", "category": "education"},
    {"content": "Aryan wants to learn Japanese before the Japan trip.", "category": "education"},
    {"content": "Aryan's favorite professor taught compilers.", "category": "education"},
    # routines (5)
    {"content": "Aryan reviews his weekly agenda on Sunday nights.", "category": "routines"},
    {"content": "Aryan batch-cooks meals on Sunday afternoons.", "category": "routines"},
    {
        "content": "Aryan does a no-meetings deep-work block on Thursday mornings.",
        "category": "routines",
    },
    {"content": "Aryan waters the balcony garden every other day.", "category": "routines"},
    {"content": "Aryan journals for ten minutes after breakfast.", "category": "routines"},
]


@pytest.fixture
async def corpus_user(memory_user: str) -> str:
    """The standard adversarial corpus, seeded for a dedicated user."""
    await seed_memories(memory_user, _CORPUS)
    return memory_user


def _contents(result: MemorySearchResult) -> list[str]:
    return [memory.content for memory in result.memories]


async def test_paraphrase_recall_indirect_girlfriend_gift_query(corpus_user: str) -> None:
    result = await memory_engine.recall(corpus_user, "when should I buy a gift for my girlfriend")
    contents = _contents(result)
    assert _BIRTHDAY_FACT in contents, (
        f"indirect paraphrase failed to surface the birthday fact; got: {contents}"
    )


async def test_distractors_do_not_outrank_the_target(corpus_user: str) -> None:
    result = await memory_engine.recall(
        corpus_user, "what food does my girlfriend Nadia like", limit=12
    )
    contents = _contents(result)
    assert _NADIA_ITALIAN in contents
    target_rank = contents.index(_NADIA_ITALIAN)
    for distractor in (_SF_ITALIAN_DISTRACTOR, _MARCO_DISTRACTOR):
        if distractor in contents:
            assert contents.index(distractor) > target_rank, (
                f"distractor outranked the target: {contents}"
            )


async def test_keyword_only_id_token_found_via_fts(corpus_user: str) -> None:
    # "PROJ-4821" appears in exactly one memory; an ID-like token is the
    # FTS plane's job — dense similarity alone has nothing to anchor on.
    result = await memory_engine.recall(corpus_user, "PROJ-4821")
    contents = _contents(result)
    assert _JIRA_FACT in contents, f"keyword token not recalled; got: {contents}"


async def test_category_prefix_filter_scopes_to_subtree(corpus_user: str) -> None:
    result = await memory_engine.recall(corpus_user, "Italian", limit=12, category_prefix="work")
    assert result.memories, "category-scoped recall returned nothing"
    for memory in result.memories:
        assert memory.category_path == "work" or memory.category_path.startswith("work/"), (
            f"memory leaked from outside the prefix: {memory.category_path}"
        )
    assert _NADIA_ITALIAN not in _contents(result)


async def test_expired_forget_after_never_returned_even_with_live_vector(
    memory_user: str,
) -> None:
    now = datetime.now(UTC)
    expired, live = await seed_memories(
        memory_user,
        [
            {
                "content": "Aryan has a dentist appointment on June 5 at 3pm.",
                "category": "health",
                "forget_after": now - timedelta(days=1),
            },
            {
                "content": "Aryan's dentist is Dr. Mehta at Smile Care clinic.",
                "category": "health",
            },
        ],
    )
    # Chroma still holds the expired vector (expiry is read-time only)...
    vector_ids = await chroma_user_vector_ids(memory_user)
    assert str(expired.id) in vector_ids

    # ...but recall must filter it out at hydration.
    result = await memory_engine.recall(memory_user, "dentist appointment")
    contents = _contents(result)
    assert live.content in contents
    assert expired.content not in contents, "expired memory leaked into recall"


async def test_superseded_chain_returns_only_newest_version(memory_user: str) -> None:
    (old,) = await seed_memories(
        memory_user,
        [{"content": "Aryan lives in Bengaluru.", "category": "home"}],
    )
    updated = await memory_engine.update_memory(
        memory_user, str(old.id), "Aryan lives in San Francisco."
    )
    assert updated is not None

    result = await memory_engine.recall(memory_user, "which city does Aryan live in")
    contents = _contents(result)
    assert "Aryan lives in San Francisco." in contents
    assert "Aryan lives in Bengaluru." not in contents, "superseded version leaked into recall"

    old_metadata = await chroma_vector_metadata(str(old.id))
    assert old_metadata is not None and old_metadata["is_latest"] is False


async def test_cross_user_isolation_is_absolute(make_memory_user: Callable[[], str]) -> None:
    user_a = make_memory_user()
    user_b = make_memory_user()
    await seed_memories(
        user_a,
        [
            {"content": "User A's secret project is codenamed BLUEBIRD.", "category": "work"},
            {
                "content": "User A's girlfriend Nadia's birthday is March 12.",
                "category": "relationships",
            },
            {"content": "User A is vegetarian.", "category": "food-preferences"},
        ],
    )
    await seed_memories(
        user_b,
        [
            {"content": "User B's cat is named Whiskers.", "category": "pets"},
            {"content": "User B works at a bakery.", "category": "work"},
        ],
    )
    b_ids = {str(row.id) for row in await fetch_memory_rows(user_b)}
    a_ids = {str(row.id) for row in await fetch_memory_rows(user_a)}

    result_b = await memory_engine.recall(user_b, "secret project codenamed BLUEBIRD")
    assert all(memory.id in b_ids for memory in result_b.memories), (
        f"user B saw foreign memories: {_contents(result_b)}"
    )
    assert all("BLUEBIRD" not in content for content in _contents(result_b))

    result_a = await memory_engine.recall(user_a, "cat named Whiskers")
    assert all(memory.id in a_ids for memory in result_a.memories), (
        f"user A saw foreign memories: {_contents(result_a)}"
    )
    assert all("Whiskers" not in content for content in _contents(result_a))


async def test_graph_expansion_surfaces_relevant_sibling_not_incidental(
    memory_user: str,
) -> None:
    # Both non-relationship facts are excluded by the category filter, so the
    # only path back is the 1-hop entity expansion through "Nadia". Expansion
    # then reranks them against the query: the gift-relevant sibling survives,
    # the incidental work fact (shares only the entity) is dropped as noise.
    relevant_sibling = "Nadia's ideal birthday gift is a vintage film camera."
    incidental_sibling = "Nadia works at Stripe in the payments division."
    await seed_memories(
        memory_user,
        [
            {
                "content": _BIRTHDAY_FACT,
                "category": "relationships",
                "entities": [("Nadia", "person")],
            },
            {
                "content": relevant_sibling,
                "category": "preferences",
                "entities": [("Nadia", "person")],
            },
            {
                "content": incidental_sibling,
                "category": "work",
                "entities": [("Nadia", "person")],
            },
        ],
    )
    without = await memory_engine.recall(
        memory_user,
        "what gift should I get my girlfriend for her birthday",
        category_prefix="relationships",
        include_graph_expansion=False,
    )
    assert _contents(without) == [_BIRTHDAY_FACT]

    with_expansion = await memory_engine.recall(
        memory_user,
        "what gift should I get my girlfriend for her birthday",
        category_prefix="relationships",
        include_graph_expansion=True,
    )
    contents = _contents(with_expansion)
    assert _BIRTHDAY_FACT in contents
    assert relevant_sibling in contents, (
        f"expansion did not surface the gift-relevant sibling; got: {contents}"
    )
    assert incidental_sibling not in contents, (
        f"expansion injected an incidental, off-topic sibling; got: {contents}"
    )


async def test_empty_index_recall_returns_empty_gracefully(memory_user: str) -> None:
    result = await memory_engine.recall(memory_user, "anything at all")
    assert result.memories == []
    assert result.total_count == 0


async def test_warm_recall_latency_under_bound(corpus_user: str) -> None:
    # Models are warmed by the session fixture; this measures the full
    # uncached pipeline (embed + ANN + FTS + RRF + rerank + hydrate).
    started = time.perf_counter()
    result = await memory_engine.recall(corpus_user, "what are Aryan's morning routines")
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert result.memories, "latency probe query returned nothing"
    print(f"\nwarm uncached recall latency: {elapsed_ms:.0f}ms")
    assert elapsed_ms < 500, f"warm recall took {elapsed_ms:.0f}ms (budget 500ms)"


# ---------------------------------------------------------------------------
# Graph expansion correctness
# ---------------------------------------------------------------------------


async def test_graph_expansion_drops_incidental_sibling(
    memory_user: str,
) -> None:
    """An entity sibling unrelated to the query must not be injected.

    Expansion reranks siblings in the same pool as the base results, so a fact
    pulled in only because it shares an entity ("Nadia changed jobs") stays out
    of a birthday-gift recall — the relevance cutoff drops it.
    """
    await seed_memories(
        memory_user,
        [
            {
                "content": "Aryan's girlfriend Nadia has a birthday on March 12.",
                "category": "relationships",
                "entities": [("Nadia", "person")],
                "importance": 0.9,
            },
            {
                "content": "Nadia recently changed jobs at a fintech startup.",
                "category": "work",
                "entities": [("Nadia", "person")],
                "importance": 0.5,
            },
        ],
    )
    result = await memory_engine.recall(
        memory_user,
        "birthday gift for my girlfriend",
        include_graph_expansion=True,
    )
    contents = _contents(result)
    assert "Aryan's girlfriend Nadia has a birthday on March 12." in contents
    assert "Nadia recently changed jobs at a fintech startup." not in contents, (
        f"expansion injected an off-topic sibling; got: {contents}"
    )


async def test_graph_expansion_siblings_respect_kinds_filter(
    memory_user: str,
) -> None:
    """Expansion siblings must obey the kinds filter.

    Graph expansion intentionally crosses category boundaries (that is the
    feature), but it must still honour the ``kinds`` filter so callers that
    request only facts do not receive experience siblings.
    """
    from app.constants.memory import MemoryKind

    await seed_memories(
        memory_user,
        [
            {
                "content": "Aryan's colleague Marco works on the platform team.",
                "category": "work",
                "entities": [("Marco", "person")],
                "importance": 0.9,
            },
            # Same entity, wrong kind — must be blocked by kinds=[FACT].
            {
                "content": "Marco visited Goa last November.",
                "category": "work",
                "kind": MemoryKind.EXPERIENCE,
                "entities": [("Marco", "person")],
                "importance": 0.6,
            },
        ],
    )

    result = await memory_engine.recall(
        memory_user,
        "colleague Marco platform team",
        kinds=[MemoryKind.FACT],
        include_graph_expansion=True,
        limit=10,
    )
    for memory in result.memories:
        assert memory.kind == MemoryKind.FACT, f"expansion leaked a non-FACT kind: {memory.kind!r}"
    assert "Marco visited Goa last November." not in _contents(result), (
        "experience sibling leaked through kinds=[FACT] filter"
    )


async def test_graph_expansion_expired_sibling_never_appears(
    memory_user: str,
) -> None:
    """A sibling whose forget_after is in the past must be excluded even via expansion."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    await seed_memories(
        memory_user,
        [
            {
                "content": "Aryan's friend Priya lives in Toronto.",
                "category": "relationships",
                "entities": [("Priya", "person")],
                "importance": 0.9,
            },
            {
                "content": "Priya's temporary phone number is +1-416-555-0123.",
                "category": "relationships",
                "entities": [("Priya", "person")],
                "importance": 0.6,
                "forget_after": now - timedelta(days=1),  # already expired
            },
        ],
    )
    result = await memory_engine.recall(
        memory_user,
        "friend Priya Toronto",
        include_graph_expansion=True,
        limit=10,
    )
    assert "Priya's temporary phone number is +1-416-555-0123." not in _contents(result), (
        "expired sibling appeared in recall via graph expansion"
    )
