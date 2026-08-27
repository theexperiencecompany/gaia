"""Unit tests for app.memory.retrieval — the hybrid recall read path.

Every external boundary (Chroma, Postgres, the embedding/rerank models, Redis)
is mocked; the fusion, filtering, scoring and assembly logic under test is real.
"""

from datetime import UTC, date as date_type, datetime, timedelta
from fnmatch import fnmatch
import math
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from freezegun import freeze_time as _freeze_time
import pytest

from app.constants.memory import (
    CONFIDENT_COSINE,
    CONFIDENT_RERANK_LOGIT,
    DEFAULT_RECALL_LIMIT,
    EPISODE_SEARCH_MIN_TOKEN_LENGTH,
    GRAPH_EXPANSION_MAX_SIBLINGS,
    IMPORTANCE_BOOST_BASE,
    IMPORTANCE_BOOST_WEIGHT,
    MAX_WEAK_RESULTS,
    MEMORY_SEARCH_CACHE_PATTERN,
    RECENCY_BOOST_DECAY_DAYS,
    RECENCY_BOOST_WEIGHT,
    RELEVANCE_DROPOFF_RATIO,
    RERANK_CANDIDATES,
    RRF_K,
    MemoryKind,
    MemoryRelationType,
)
from app.memory import retrieval
from app.memory.retrieval import (
    EpisodeHit,
    _build_entries,
    _cap_weak_results,
    _drop_below_relevance,
    _elapsed_ms,
    _episode_id_to_date,
    _episode_summary_search,
    _graph_siblings,
    _hydrate_candidates,
    _importance_boost,
    _in_category,
    _recall_cache_key,
    _recency_boost,
    _rerank_and_boost,
    _rrf_fuse,
    _tokenize,
    invalidate_recall_cache,
    recall,
    recall_episodes,
    recall_transcripts,
)
from app.models.memory_db_models import MemoryRecord

USER = "507f1f77bcf86cd799439011"


def freeze_time(*args, **kwargs):
    """freeze_time that skips transformers — its module-restore walk trips on
    the library's lazy attributes (same workaround as the worker lifecycle
    tests)."""
    kwargs.setdefault("ignore", ["transformers"])
    return _freeze_time(*args, **kwargs)


def make_row(
    content: str = "a fact",
    *,
    memory_id: uuid.UUID | None = None,
    user_id: str = USER,
    kind: str = MemoryKind.FACT.value,
    category_path: str = "work",
    importance: float = 0.5,
    is_latest: bool = True,
    is_forgotten: bool = False,
    forget_after: datetime | None = None,
    mentioned_at: datetime | None = None,
    created_at: datetime | None = None,
    parent_id: uuid.UUID | None = None,
    relation_type: str | None = None,
) -> MemoryRecord:
    """A detached MemoryRecord — no session, no DB."""
    now = datetime.now(UTC)
    return MemoryRecord(
        id=memory_id or uuid.uuid4(),
        user_id=user_id,
        kind=kind,
        content=content,
        category_path=category_path,
        importance=importance,
        version=1,
        is_latest=is_latest,
        is_forgotten=is_forgotten,
        forget_after=forget_after,
        parent_id=parent_id,
        relation_type=relation_type,
        mentioned_at=mentioned_at or now,
        created_at=created_at or now,
        updated_at=now,
        source_type="conversation",
        metadata_json={},
    )


# ---------------------------------------------------------------------------
# _rrf_fuse
# ---------------------------------------------------------------------------


class TestRrfFuse:
    def test_agreement_across_lists_beats_a_single_top_rank(self) -> None:
        # "b" is 2nd in both lists; "a" is 1st in one and absent from the other.
        # RRF: b = 2/(K+2) > a = 1/(K+1) for K=60, so agreement must win.
        fused = _rrf_fuse(["a", "b"], ["c", "b"])
        assert fused[0] == "b"

    def test_score_is_reciprocal_rank_sum(self) -> None:
        fused = _rrf_fuse(["x", "y"])
        # A single list preserves its own order (1/(K+1) > 1/(K+2)).
        assert fused == ["x", "y"]
        assert 1.0 / (RRF_K + 1) > 1.0 / (RRF_K + 2)

    def test_empty_lists_produce_no_ids(self) -> None:
        assert _rrf_fuse([], []) == []

    def test_deduplicates_across_lists(self) -> None:
        fused = _rrf_fuse(["a", "b"], ["b", "a"])
        assert sorted(fused) == ["a", "b"]
        assert len(fused) == 2


# ---------------------------------------------------------------------------
# _sigmoid
# ---------------------------------------------------------------------------


class TestSigmoid:
    # Replaced min-max normalization: the pinned invariant is now the stronger
    # one — the mapping is absolute (a logit always maps to the same relevance
    # regardless of what else is in the pool) and gap-preserving.

    def test_zero_logit_is_the_midpoint(self) -> None:
        assert retrieval._sigmoid(0.0) == pytest.approx(0.5)

    def test_is_strictly_monotonic(self) -> None:
        assert (
            retrieval._sigmoid(-5.0)
            < retrieval._sigmoid(-1.0)
            < retrieval._sigmoid(0.0)
            < retrieval._sigmoid(1.0)
            < retrieval._sigmoid(5.0)
        )

    def test_stays_within_the_unit_interval(self) -> None:
        for logit in (-12.0, -3.0, 0.0, 3.0, 12.0):
            assert 0.0 < retrieval._sigmoid(logit) < 1.0

    def test_a_thin_raw_gap_stays_thin(self) -> None:
        # Min-max would stretch 2.01 vs 2.00 to 1.0 vs 0.0; the sigmoid keeps
        # near-identical logits at near-identical relevance.
        assert retrieval._sigmoid(2.01) - retrieval._sigmoid(2.00) < 0.01

    def test_is_symmetric_around_zero(self) -> None:
        assert retrieval._sigmoid(3.0) + retrieval._sigmoid(-3.0) == pytest.approx(1.0)

    def test_extreme_logits_saturate_without_overflow(self) -> None:
        assert retrieval._sigmoid(1000.0) == pytest.approx(1.0)
        assert retrieval._sigmoid(-1000.0) == pytest.approx(0.0)

    def test_each_side_of_zero_matches_the_closed_form_exactly(self) -> None:
        # The two stable branches are algebraically equal but not bit-equal
        # (e.g. at ±0.03), so exact equality pins which closed form serves
        # which side — this calibrated relevance feeds the blend verbatim.
        assert retrieval._sigmoid(0.03) == 1.0 / (1.0 + math.exp(-0.03))
        assert retrieval._sigmoid(-0.03) == math.exp(-0.03) / (1.0 + math.exp(-0.03))


# ---------------------------------------------------------------------------
# boosts
# ---------------------------------------------------------------------------


class TestRecencyBoost:
    def test_fresh_memory_gets_the_full_weight(self) -> None:
        now = datetime.now(UTC)
        assert _recency_boost(make_row(mentioned_at=now), now) == pytest.approx(
            1.0 + RECENCY_BOOST_WEIGHT
        )

    def test_boost_decays_with_age(self) -> None:
        now = datetime.now(UTC)
        one_half_life = make_row(mentioned_at=now - timedelta(days=RECENCY_BOOST_DECAY_DAYS))
        assert _recency_boost(one_half_life, now) == pytest.approx(
            1.0 + RECENCY_BOOST_WEIGHT * math.exp(-1.0)
        )

    def test_older_memory_scores_strictly_below_a_newer_one(self) -> None:
        now = datetime.now(UTC)
        old = _recency_boost(make_row(mentioned_at=now - timedelta(days=365)), now)
        new = _recency_boost(make_row(mentioned_at=now - timedelta(days=1)), now)
        assert old < new

    def test_future_mention_is_clamped_not_amplified(self) -> None:
        now = datetime.now(UTC)
        future = make_row(mentioned_at=now + timedelta(days=10))
        # Without the max(..., 0.0) clamp a future timestamp would inflate the
        # exponential above 1 and let a mis-dated memory outrank everything.
        assert _recency_boost(future, now) == pytest.approx(1.0 + RECENCY_BOOST_WEIGHT)

    def test_falls_back_to_created_at_when_never_mentioned(self) -> None:
        now = datetime.now(UTC)
        row = make_row(created_at=now - timedelta(days=365))
        row.mentioned_at = None  # column is NOT NULL; the ``or`` is the guard
        assert _recency_boost(row, now) == pytest.approx(
            1.0 + RECENCY_BOOST_WEIGHT * math.exp(-365.0 / RECENCY_BOOST_DECAY_DAYS)
        )


class TestImportanceBoost:
    def test_zero_importance_is_the_base(self) -> None:
        assert _importance_boost(make_row(importance=0.0)) == pytest.approx(IMPORTANCE_BOOST_BASE)

    def test_max_importance_adds_the_full_weight(self) -> None:
        assert _importance_boost(make_row(importance=1.0)) == pytest.approx(
            IMPORTANCE_BOOST_BASE + IMPORTANCE_BOOST_WEIGHT
        )

    def test_is_monotonic_in_importance(self) -> None:
        assert _importance_boost(make_row(importance=0.2)) < _importance_boost(
            make_row(importance=0.9)
        )


# ---------------------------------------------------------------------------
# _in_category
# ---------------------------------------------------------------------------


class TestInCategory:
    @pytest.mark.parametrize(
        ("path", "prefix", "expected"),
        [
            ("work", "work", True),
            ("work/gaia", "work", True),
            ("work/gaia/api", "work", True),
            # The trap: a sibling folder that merely starts with the prefix
            # string must NOT match — "workshop" is not under "work".
            ("workshop", "work", False),
            ("work-notes", "work", False),
            ("health", "work", False),
            ("work", "work/gaia", False),
        ],
    )
    def test_prefix_matching_respects_path_segments(
        self, path: str, prefix: str, expected: bool
    ) -> None:
        assert _in_category(path, prefix) is expected


# ---------------------------------------------------------------------------
# _episode_id_to_date / _tokenize / _elapsed_ms
# ---------------------------------------------------------------------------


class TestEpisodeIdToDate:
    def test_parses_the_trailing_date_segment(self) -> None:
        assert _episode_id_to_date(f"{USER}:2026-03-12") == date_type(2026, 3, 12)

    def test_unparseable_tail_returns_none(self) -> None:
        assert _episode_id_to_date(f"{USER}:not-a-date") is None

    def test_id_without_separator_returns_none(self) -> None:
        assert _episode_id_to_date("garbage") is None

    def test_empty_id_returns_none(self) -> None:
        assert _episode_id_to_date("") is None


class TestTokenize:
    def test_drops_tokens_below_the_minimum_length(self) -> None:
        assert EPISODE_SEARCH_MIN_TOKEN_LENGTH == 3
        assert _tokenize("I am at the gym") == ["the", "gym"]

    def test_lowercases_and_strips_punctuation(self) -> None:
        assert _tokenize("Nadia's BIRTHDAY, March!") == ["nadia's", "birthday", "march"]

    def test_query_of_only_short_words_yields_no_tokens(self) -> None:
        assert _tokenize("hi ok up") == []

    def test_empty_query_yields_no_tokens(self) -> None:
        assert _tokenize("") == []

    def test_digits_are_kept_as_tokens(self) -> None:
        assert _tokenize("ticket 4821") == ["ticket", "4821"]


def test_elapsed_ms_is_non_negative_integer() -> None:
    import time

    value = _elapsed_ms(time.perf_counter())
    assert isinstance(value, int)
    assert value >= 0


# ---------------------------------------------------------------------------
# _drop_below_relevance
# ---------------------------------------------------------------------------


def _cand(
    base: float,
    content: str = "c",
    *,
    relevance: float | None = None,
    score: float | None = None,
    confident: bool = False,
) -> retrieval._ScoredCandidate:
    return retrieval._ScoredCandidate(
        row=make_row(content),
        base=base,
        relevance=base if relevance is None else relevance,
        score=base if score is None else score,
        confident=confident,
    )


class TestDropBelowRelevance:
    # Survival reads the cross-encoder's calibrated ``relevance`` — never the
    # blended ``base`` (its cosine leg floors every candidate high) and never
    # the boosted ``score``. Confident candidates are exempt: the absolute
    # cosine/logit/keyword signals are the escape hatch for query shapes the
    # cross-encoder misjudges.

    def test_empty_input_returns_empty(self) -> None:
        assert _drop_below_relevance([]) == []

    def test_drops_the_tail_below_the_dropoff_floor(self) -> None:
        top = 1.0
        keep = top * RELEVANCE_DROPOFF_RATIO  # exactly at the floor -> kept
        drop = top * RELEVANCE_DROPOFF_RATIO - 0.01
        scored = [_cand(top, "top"), _cand(keep, "keep"), _cand(drop, "drop")]
        kept = _drop_below_relevance(scored)
        assert [item.row.content for item in kept] == ["top", "keep"]

    def test_always_keeps_the_top_result(self) -> None:
        scored = [_cand(0.001, "only")]
        assert len(_drop_below_relevance(scored)) == 1

    def test_non_positive_top_relevance_disables_the_filter(self) -> None:
        scored = [_cand(0.0, "a"), _cand(0.0, "b")]
        assert len(_drop_below_relevance(scored)) == 2

    def test_exactly_zero_top_relevance_disables_the_filter_for_negatives(self) -> None:
        # Boundary: top == 0.0 must disable the filter (not just top < 0) —
        # a floor of exactly 0.0 would silently drop a negative-relevance
        # candidate instead of switching off.
        scored = [_cand(0.0, "zero"), _cand(-0.5, "negative")]
        assert len(_drop_below_relevance(scored)) == 2

    @pytest.mark.regression
    def test_a_high_blended_base_cannot_save_below_floor_relevance(self) -> None:
        """The incidental-sibling shape, with the real measured proportions:
        the off-topic sibling kept 72% of the top's blended base (the
        proportional cosine leg floors everyone high) while its calibrated
        cross-encoder relevance ratio was 9%. Survival on base kept it; on
        relevance it dies."""
        scored = [
            _cand(0.473, "birthday", relevance=0.122, confident=True),
            _cand(0.341, "sibling", relevance=0.011, confident=False),
        ]
        assert [item.row.content for item in _drop_below_relevance(scored)] == ["birthday"]

    def test_a_boosted_score_cannot_save_below_floor_relevance(self) -> None:
        scored = [_cand(1.0, "top"), _cand(0.1, "marginal", score=2.0)]
        assert [item.row.content for item in _drop_below_relevance(scored)] == ["top"]

    def test_a_confident_candidate_is_never_dropped(self) -> None:
        """The escape hatch: a keyword/cosine-anchored result the
        cross-encoder hates still reaches the prompt (the blend exists for
        ordering precisely because the cross-encoder misjudges some shapes)."""
        scored = [_cand(1.0, "top"), _cand(0.01, "anchored", confident=True)]
        assert [item.row.content for item in _drop_below_relevance(scored)] == [
            "top",
            "anchored",
        ]


# ---------------------------------------------------------------------------
# _cap_weak_results
# ---------------------------------------------------------------------------


class TestCapWeakResults:
    def test_confident_results_are_never_capped(self) -> None:
        scored = [
            retrieval._ScoredCandidate(
                row=make_row(f"c{i}"),
                base=1.0 - i / 100,
                relevance=1.0 - i / 100,
                score=1.0 - i / 100,
                confident=True,
            )
            for i in range(MAX_WEAK_RESULTS + 5)
        ]
        assert len(_cap_weak_results(scored)) == MAX_WEAK_RESULTS + 5

    def test_weak_results_are_capped_at_the_limit(self) -> None:
        scored = [
            retrieval._ScoredCandidate(
                row=make_row(f"w{i}"),
                base=1.0 - i / 100,
                relevance=1.0 - i / 100,
                score=1.0 - i / 100,
                confident=False,
            )
            for i in range(MAX_WEAK_RESULTS + 5)
        ]
        assert len(_cap_weak_results(scored)) == MAX_WEAK_RESULTS

    def test_a_confident_result_after_the_weak_cap_is_still_kept(self) -> None:
        """Hitting the weak cap must SKIP further weak results, never stop the
        scan: a confident result ranked below the capped weak tail still
        belongs in the prompt."""
        scored = [
            _cand(1.0 - i / 100, f"w{i}", confident=False) for i in range(MAX_WEAK_RESULTS + 1)
        ] + [_cand(0.5, "anchored-last", confident=True)]

        kept = _cap_weak_results(scored)

        assert [row.content for row, _ in kept][-1] == "anchored-last"
        assert len(kept) == MAX_WEAK_RESULTS + 1

    def test_weak_cap_does_not_consume_the_confident_budget(self) -> None:
        scored = [
            retrieval._ScoredCandidate(
                row=make_row("w1"), base=0.9, relevance=0.9, score=0.9, confident=False
            ),
            retrieval._ScoredCandidate(
                row=make_row("s1"), base=0.8, relevance=0.8, score=0.8, confident=True
            ),
            retrieval._ScoredCandidate(
                row=make_row("w2"), base=0.7, relevance=0.7, score=0.7, confident=False
            ),
            retrieval._ScoredCandidate(
                row=make_row("s2"), base=0.6, relevance=0.6, score=0.6, confident=True
            ),
        ]
        kept = _cap_weak_results(scored)
        assert [row.content for row, _ in kept] == ["w1", "s1", "w2", "s2"]

    def test_ranking_order_and_scores_survive_the_cap(self) -> None:
        scored = [
            retrieval._ScoredCandidate(
                row=make_row("first"), base=0.9, relevance=0.9, score=0.9, confident=True
            ),
            retrieval._ScoredCandidate(
                row=make_row("second"), base=0.5, relevance=0.5, score=0.5, confident=True
            ),
        ]
        assert _cap_weak_results(scored) == [
            (scored[0].row, 0.9),
            (scored[1].row, 0.5),
        ]

    def test_empty_input_returns_empty(self) -> None:
        assert _cap_weak_results([]) == []


# ---------------------------------------------------------------------------
# _recall_cache_key
# ---------------------------------------------------------------------------


class TestRecallCacheKey:
    def test_key_matches_the_invalidation_glob(self) -> None:
        # invalidate_recall_cache deletes MEMORY_SEARCH_CACHE_PATTERN; a key
        # outside that glob would be cached forever and never invalidated.
        key = _recall_cache_key("recall", USER, "query")
        assert fnmatch(key, MEMORY_SEARCH_CACHE_PATTERN.format(user_id=USER))

    def test_positional_and_keyword_calls_agree(self) -> None:
        assert _recall_cache_key("recall", USER, "q") == _recall_cache_key(
            "recall", user_id=USER, query="q"
        )

    def test_default_limit_matches_an_explicit_default_limit(self) -> None:
        assert _recall_cache_key("recall", USER, "q") == _recall_cache_key(
            "recall", USER, "q", limit=DEFAULT_RECALL_LIMIT
        )

    @pytest.mark.parametrize(
        "knob",
        [
            {"limit": 3},
            {"category_prefix": "work"},
            {"kinds": [MemoryKind.EXPERIENCE]},
            {"include_graph_expansion": False},
        ],
    )
    def test_every_knob_changes_the_key(self, knob: dict) -> None:
        base = _recall_cache_key("recall", USER, "q")
        assert _recall_cache_key("recall", USER, "q", **knob) != base

    def test_different_query_changes_the_key(self) -> None:
        assert _recall_cache_key("recall", USER, "a") != _recall_cache_key("recall", USER, "b")

    def test_different_user_changes_the_key(self) -> None:
        # A collision here would serve one user's memories to another.
        assert _recall_cache_key("recall", "user-a", "q") != _recall_cache_key(
            "recall", "user-b", "q"
        )

    def test_kind_order_does_not_change_the_key(self) -> None:
        assert _recall_cache_key(
            "recall", USER, "q", kinds=[MemoryKind.FACT, MemoryKind.EXPERIENCE]
        ) == _recall_cache_key("recall", USER, "q", kinds=[MemoryKind.EXPERIENCE, MemoryKind.FACT])


async def test_invalidate_recall_cache_deletes_the_user_scoped_pattern() -> None:
    with patch.object(retrieval, "delete_cache", new=AsyncMock()) as mock_delete:
        await invalidate_recall_cache(USER)
    mock_delete.assert_awaited_once_with(MEMORY_SEARCH_CACHE_PATTERN.format(user_id=USER))


# ---------------------------------------------------------------------------
# _hydrate_candidates
# ---------------------------------------------------------------------------


class TestHydrateCandidates:
    async def _hydrate(
        self,
        fused_ids: list[str],
        fts_hits: list[tuple[MemoryRecord, float]],
        extra_rows: list[MemoryRecord],
        **kwargs,
    ) -> list[MemoryRecord]:
        kwargs.setdefault("category_prefix", None)
        kwargs.setdefault("kinds", None)
        with patch.object(
            retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=extra_rows)
        ):
            return await _hydrate_candidates(USER, fused_ids, fts_hits, **kwargs)

    async def test_preserves_fused_ranking_order(self) -> None:
        first, second = make_row("first"), make_row("second")
        got = await self._hydrate([str(second.id), str(first.id)], [], [first, second])
        assert [row.content for row in got] == ["second", "first"]

    async def test_reuses_fts_rows_instead_of_refetching_them(self) -> None:
        row = make_row("from fts")
        fetch = AsyncMock(return_value=[])
        with patch.object(retrieval.pg_store, "get_memories_by_ids", new=fetch):
            got = await _hydrate_candidates(
                USER, [str(row.id)], [(row, 0.9)], category_prefix=None, kinds=None
            )
        assert got == [row]
        fetch.assert_awaited_once_with(USER, [])

    async def test_id_with_no_row_is_skipped(self) -> None:
        got = await self._hydrate([str(uuid.uuid4())], [], [])
        assert got == []

    async def test_superseded_row_is_filtered_out(self) -> None:
        stale = make_row("old version", is_latest=False)
        got = await self._hydrate([str(stale.id)], [], [stale])
        assert got == []

    async def test_forgotten_row_is_filtered_out(self) -> None:
        gone = make_row("forgotten", is_forgotten=True)
        got = await self._hydrate([str(gone.id)], [], [gone])
        assert got == []

    async def test_expired_forget_after_is_filtered_out(self) -> None:
        expired = make_row("expired", forget_after=datetime.now(UTC) - timedelta(seconds=1))
        got = await self._hydrate([str(expired.id)], [], [expired])
        assert got == []

    async def test_future_forget_after_is_still_live(self) -> None:
        live = make_row("still valid", forget_after=datetime.now(UTC) + timedelta(days=1))
        got = await self._hydrate([str(live.id)], [], [live])
        assert got == [live]

    async def test_kinds_filter_excludes_other_kinds(self) -> None:
        fact = make_row("a fact", kind=MemoryKind.FACT.value)
        experience = make_row("an experience", kind=MemoryKind.EXPERIENCE.value)
        got = await self._hydrate(
            [str(fact.id), str(experience.id)],
            [],
            [fact, experience],
            kinds=[MemoryKind.FACT],
        )
        assert got == [fact]

    async def test_empty_kinds_list_does_not_filter(self) -> None:
        fact = make_row("a fact", kind=MemoryKind.FACT.value)
        got = await self._hydrate([str(fact.id)], [], [fact], kinds=[])
        assert got == [fact]

    async def test_category_prefix_scopes_to_the_subtree(self) -> None:
        inside = make_row("inside", category_path="work/gaia")
        outside = make_row("outside", category_path="workshop")
        got = await self._hydrate(
            [str(inside.id), str(outside.id)], [], [inside, outside], category_prefix="work"
        )
        assert got == [inside]


# ---------------------------------------------------------------------------
# _rerank_and_boost
# ---------------------------------------------------------------------------


class TestRerankAndBoost:
    async def test_empty_candidates_short_circuits_without_calling_the_model(self) -> None:
        rerank = AsyncMock()
        with patch.object(retrieval, "rerank", new=rerank):
            assert await _rerank_and_boost("q", [], ann_similarity={}, fts_ids=set()) == []
        rerank.assert_not_awaited()

    async def test_sorts_by_blended_score_descending(self) -> None:
        weak, strong = make_row("weak"), make_row("strong")
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[-8.0, 4.0])):
            scored = await _rerank_and_boost("q", [weak, strong], ann_similarity={}, fts_ids=set())
        assert [item.row.content for item in scored] == ["strong", "weak"]

    async def test_importance_boost_is_applied_to_the_final_score(self) -> None:
        now = datetime.now(UTC)
        dull = make_row("dull", importance=0.1, mentioned_at=now)
        vital = make_row("vital", importance=1.0, mentioned_at=now)
        # Identical rerank logits and identical cosines: the ONLY separator
        # left is the importance boost, and the higher-importance row is
        # deliberately last in the input so a missing boost keeps it last.
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[1.0, 1.0])):
            scored = await _rerank_and_boost(
                "q",
                [dull, vital],
                ann_similarity={str(dull.id): 0.6, str(vital.id): 0.6},
                fts_ids=set(),
            )
        assert [item.row.content for item in scored] == ["vital", "dull"]

    async def test_recency_boost_is_applied_to_the_final_score(self) -> None:
        now = datetime.now(UTC)
        stale = make_row("stale", mentioned_at=now - timedelta(days=400))
        fresh = make_row("fresh", mentioned_at=now)
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[1.0, 1.0])):
            scored = await _rerank_and_boost(
                "q",
                [stale, fresh],
                ann_similarity={str(stale.id): 0.6, str(fresh.id): 0.6},
                fts_ids=set(),
            )
        assert [item.row.content for item in scored] == ["fresh", "stale"]

    async def test_strong_cosine_marks_a_candidate_confident(self) -> None:
        row = make_row()
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[-9.0])):
            scored = await _rerank_and_boost(
                "q", [row], ann_similarity={str(row.id): CONFIDENT_COSINE}, fts_ids=set()
            )
        assert scored[0].confident is True

    async def test_cosine_just_below_the_threshold_is_not_confident(self) -> None:
        row = make_row()
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[-9.0])):
            scored = await _rerank_and_boost(
                "q",
                [row],
                ann_similarity={str(row.id): CONFIDENT_COSINE - 0.001},
                fts_ids=set(),
            )
        assert scored[0].confident is False

    async def test_strong_raw_logit_marks_a_candidate_confident(self) -> None:
        row = make_row()
        with patch.object(
            retrieval, "rerank", new=AsyncMock(return_value=[CONFIDENT_RERANK_LOGIT])
        ):
            scored = await _rerank_and_boost("q", [row], ann_similarity={}, fts_ids=set())
        assert scored[0].confident is True

    async def test_keyword_anchor_marks_a_candidate_confident(self) -> None:
        row = make_row()
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[-9.0])):
            scored = await _rerank_and_boost("q", [row], ann_similarity={}, fts_ids={str(row.id)})
        assert scored[0].confident is True

    async def test_no_signal_leaves_a_candidate_unconfident(self) -> None:
        row = make_row()
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[-9.0])):
            scored = await _rerank_and_boost("q", [row], ann_similarity={}, fts_ids=set())
        assert scored[0].confident is False

    async def test_fts_only_candidate_falls_back_to_its_rank_position(self) -> None:
        # No cosine for either row: both fall back to rank position, so the
        # earlier (better-fused) row must win on an otherwise-flat rerank.
        first, second = make_row("first", importance=0.5), make_row("second", importance=0.5)
        now = datetime.now(UTC)
        first.mentioned_at = second.mentioned_at = now
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[1.0, 1.0])):
            scored = await _rerank_and_boost("q", [first, second], ann_similarity={}, fts_ids=set())
        assert scored[0].row.content == "first"
        assert scored[0].score > scored[1].score
        # The fallback is the exact rank position 1 - index/total, on the same
        # 0-1 scale as the cosine ratio it stands in for — a shifted scale
        # (e.g. 2 - index/total) would hand FTS-only rows more retrieval
        # relevance than a perfect cosine match.
        sig = 1.0 / (1.0 + math.exp(-1.0))
        assert scored[0].base == 0.6 * sig + 0.4 * (1.0 - 0 / 2)
        assert scored[1].base == 0.6 * sig + 0.4 * (1.0 - 1 / 2)

    async def test_base_blends_sigmoid_and_cosine_ratio_at_60_40(self) -> None:
        # The pre-boost relevance contract, numerically:
        #   base = 0.6 * sigmoid(logit) + 0.4 * (cosine / best cosine)
        # Exact equality on purpose — the blend weights and the
        # divide-by-the-pool's-best normalization are the recall contract.
        best, other = make_row("best"), make_row("other")
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[1.25, -0.75])):
            scored = await _rerank_and_boost(
                "q",
                [best, other],
                ann_similarity={str(best.id): 0.8, str(other.id): 0.4},
                fts_ids=set(),
            )
        by_content = {item.row.content: item for item in scored}
        assert by_content["best"].base == 0.6 * (1.0 / (1.0 + math.exp(-1.25))) + 0.4 * (0.8 / 0.8)
        # ``relevance`` is the sigmoid leg alone — it is what survival reads.
        assert by_content["best"].relevance == 1.0 / (1.0 + math.exp(-1.25))
        assert by_content["other"].relevance == math.exp(-0.75) / (1.0 + math.exp(-0.75))
        assert by_content["other"].base == 0.6 * (
            math.exp(-0.75) / (1.0 + math.exp(-0.75))
        ) + 0.4 * (0.4 / 0.8)

    async def test_a_zero_top_cosine_contributes_no_retrieval_signal(self) -> None:
        # A degenerate pool whose best cosine is 0.0 must neither divide by it
        # nor award free retrieval relevance: base is the sigmoid term alone.
        row = make_row("flat")
        with patch.object(retrieval, "rerank", new=AsyncMock(return_value=[1.0])):
            scored = await _rerank_and_boost(
                "q", [row], ann_similarity={str(row.id): 0.0}, fts_ids=set()
            )
        assert scored[0].base == 0.6 * (1.0 / (1.0 + math.exp(-1.0)))

    async def test_the_query_reaches_the_reranker_with_candidate_contents(self) -> None:
        rows = [make_row("alpha"), make_row("beta")]
        rerank = AsyncMock(return_value=[0.0, 0.0])
        with patch.object(retrieval, "rerank", new=rerank):
            await _rerank_and_boost("my query", rows, ann_similarity={}, fts_ids=set())
        rerank.assert_awaited_once_with("my query", ["alpha", "beta"])


# ---------------------------------------------------------------------------
# _graph_siblings
# ---------------------------------------------------------------------------


def _entity(entity_id: uuid.UUID | None = None, name: str = "Nadia") -> MagicMock:
    entity = MagicMock()
    entity.id = entity_id or uuid.uuid4()
    entity.name = name
    entity.entity_type = "person"
    return entity


class TestGraphSiblings:
    async def test_no_entities_returns_no_siblings_without_a_second_query(self) -> None:
        siblings = AsyncMock()
        with (
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(retrieval.pg_store, "get_memories_for_entities", new=siblings),
        ):
            got = await _graph_siblings(USER, [make_row("only")], kinds=None)
        assert got == []
        siblings.assert_not_awaited()

    async def test_returns_only_the_siblings_not_the_source_pool(self) -> None:
        base = [make_row("base")]
        sibling = make_row("sibling")
        with (
            patch.object(
                retrieval.pg_store,
                "get_entities_for_memories",
                new=AsyncMock(return_value={base[0].id: [_entity()]}),
            ),
            patch.object(
                retrieval.pg_store,
                "get_memories_for_entities",
                new=AsyncMock(return_value=[sibling]),
            ),
        ):
            got = await _graph_siblings(USER, base, kinds=None)
        assert [row.content for row in got] == ["sibling"]

    async def test_only_the_top_results_supply_source_entities(self) -> None:
        from app.constants.memory import GRAPH_EXPANSION_SOURCE_RESULTS

        base = [make_row(f"c{i}") for i in range(GRAPH_EXPANSION_SOURCE_RESULTS + 3)]
        entities = AsyncMock(return_value={})
        with patch.object(retrieval.pg_store, "get_entities_for_memories", new=entities):
            await _graph_siblings(USER, base, kinds=None)
        entities.assert_awaited_once_with([row.id for row in base[:GRAPH_EXPANSION_SOURCE_RESULTS]])

    async def test_existing_candidates_are_excluded_and_filters_forwarded(self) -> None:
        base = [make_row("base")]
        fetch = AsyncMock(return_value=[])
        with (
            patch.object(
                retrieval.pg_store,
                "get_entities_for_memories",
                new=AsyncMock(return_value={base[0].id: [_entity()]}),
            ),
            patch.object(retrieval.pg_store, "get_memories_for_entities", new=fetch),
        ):
            await _graph_siblings(USER, base, kinds=[MemoryKind.FACT])
        kwargs = fetch.await_args.kwargs
        assert kwargs["exclude_memory_ids"] == [base[0].id]
        assert kwargs["kinds"] == [MemoryKind.FACT.value]
        assert kwargs["limit"] == GRAPH_EXPANSION_MAX_SIBLINGS
        assert fetch.await_args.args[0] == USER

    async def test_no_kinds_filter_is_forwarded_as_none(self) -> None:
        base = [make_row("base")]
        fetch = AsyncMock(return_value=[])
        with (
            patch.object(
                retrieval.pg_store,
                "get_entities_for_memories",
                new=AsyncMock(return_value={base[0].id: [_entity()]}),
            ),
            patch.object(retrieval.pg_store, "get_memories_for_entities", new=fetch),
        ):
            await _graph_siblings(USER, base, kinds=None)
        assert fetch.await_args.kwargs["kinds"] is None

    async def test_duplicate_entities_across_memories_are_deduplicated(self) -> None:
        base = [make_row("a"), make_row("b")]
        shared = _entity()
        fetch = AsyncMock(return_value=[])
        with (
            patch.object(
                retrieval.pg_store,
                "get_entities_for_memories",
                new=AsyncMock(return_value={base[0].id: [shared], base[1].id: [shared]}),
            ),
            patch.object(retrieval.pg_store, "get_memories_for_entities", new=fetch),
        ):
            await _graph_siblings(USER, base, kinds=None)
        assert fetch.await_args.args[1] == [shared.id]


# ---------------------------------------------------------------------------
# _build_entries
# ---------------------------------------------------------------------------


class TestBuildEntries:
    async def test_maps_rows_to_entries_with_rounded_scores(self) -> None:
        row = make_row("mapped")
        with patch.object(
            retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
        ):
            entries = await _build_entries([(row, 0.123456789)])
        assert entries[0].content == "mapped"
        assert entries[0].id == str(row.id)
        assert entries[0].relevance_score == 0.1235

    async def test_updated_entry_carries_the_superseded_content(self) -> None:
        parent = make_row("lives in Bengaluru")
        child = make_row(
            "lives in San Francisco",
            parent_id=parent.id,
            relation_type=MemoryRelationType.UPDATES.value,
        )
        with (
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(
                retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=[parent])
            ) as fetch_parents,
        ):
            entries = await _build_entries([(child, 0.9)])

        # The liveness fetch must be scoped to the OWNER of the recalled rows:
        # unscoped (None) it returns nothing and every parent silently reads
        # as deleted, dropping previous_content across the board.
        assert fetch_parents.await_args.args[0] == child.user_id
        assert entries[0].previous_content == "lives in Bengaluru"

    async def test_no_parent_lookup_when_nothing_superseded_anything(self) -> None:
        row = make_row("standalone")
        fetch = AsyncMock(return_value=[])
        with (
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(retrieval.pg_store, "get_memories_by_ids", new=fetch),
        ):
            entries = await _build_entries([(row, 0.9)])
        fetch.assert_not_awaited()
        assert entries[0].previous_content is None

    async def test_extends_relation_does_not_fetch_a_previous_version(self) -> None:
        parent = make_row("original")
        child = make_row(
            "extension", parent_id=parent.id, relation_type=MemoryRelationType.EXTENDS.value
        )
        fetch = AsyncMock(return_value=[parent])
        with (
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(retrieval.pg_store, "get_memories_by_ids", new=fetch),
        ):
            entries = await _build_entries([(child, 0.9)])
        fetch.assert_not_awaited()
        assert entries[0].previous_content is None

    async def test_parent_expiring_exactly_now_is_already_expired(self) -> None:
        # forget_after == now is the deletion boundary: deleted content must
        # not ride back into the prompt for even one instant past its expiry.
        now = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)
        parent = make_row("expired at this instant", forget_after=now)
        child = make_row(
            "successor", parent_id=parent.id, relation_type=MemoryRelationType.UPDATES.value
        )
        with (
            freeze_time(now),
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(
                retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=[parent])
            ) as fetch_parents,
        ):
            entries = await _build_entries([(child, 0.9)])

        # The liveness fetch must be scoped to the OWNER of the recalled rows:
        # unscoped (None) it returns nothing and every parent silently reads
        # as deleted, dropping previous_content across the board.
        assert fetch_parents.await_args.args[0] == child.user_id
        assert entries[0].previous_content is None

    async def test_missing_parent_row_leaves_previous_content_empty(self) -> None:
        child = make_row(
            "orphan", parent_id=uuid.uuid4(), relation_type=MemoryRelationType.UPDATES.value
        )
        with (
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=[])),
        ):
            entries = await _build_entries([(child, 0.9)])
        assert entries[0].previous_content is None

    async def test_entities_are_attached_to_their_own_entry(self) -> None:
        row = make_row("with entities")
        entity = MagicMock()
        entity.id = uuid.uuid4()
        entity.name = "Nadia"
        entity.entity_type = "person"
        with patch.object(
            retrieval.pg_store,
            "get_entities_for_memories",
            new=AsyncMock(return_value={row.id: [entity]}),
        ):
            entries = await _build_entries([(row, 0.5)])
        assert [ref.name for ref in entries[0].entities] == ["Nadia"]

    async def test_empty_input_returns_no_entries(self) -> None:
        with patch.object(
            retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
        ):
            assert await _build_entries([]) == []


# ---------------------------------------------------------------------------
# recall (end to end, mocked stores)
# ---------------------------------------------------------------------------


class _RecallHarness:
    """Drives the real ``recall`` pipeline with every I/O boundary faked."""

    def __init__(self) -> None:
        self.rerank_inputs: list[list[str]] = []
        self.rerank_scores: dict[str, float] = {}

    async def fake_rerank(self, _query: str, documents: list[str]) -> list[float]:
        self.rerank_inputs.append(list(documents))
        return [self.rerank_scores.get(document, 0.0) for document in documents]

    def patches(
        self,
        *,
        ann: list[tuple[str, float]],
        fts: list[tuple[MemoryRecord, float]],
        rows: list[MemoryRecord],
        entities: dict | None = None,
        siblings: list[MemoryRecord] | None = None,
    ):
        return (
            patch.object(retrieval, "embed_query", new=AsyncMock(return_value=[0.1] * 8)),
            patch.object(retrieval.chroma_store, "query_similar", new=AsyncMock(return_value=ann)),
            patch.object(retrieval.pg_store, "fts_search", new=AsyncMock(return_value=fts)),
            patch.object(
                retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=rows)
            ),
            patch.object(
                retrieval.pg_store,
                "get_entities_for_memories",
                new=AsyncMock(return_value=entities or {}),
            ),
            patch.object(
                retrieval.pg_store,
                "get_memories_for_entities",
                new=AsyncMock(return_value=siblings or []),
            ),
            patch.object(retrieval, "rerank", new=self.fake_rerank),
        )


async def _run_recall(harness: _RecallHarness, patches, **kwargs):
    from contextlib import ExitStack

    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        return await recall.__wrapped__(USER, "the query", **kwargs)


class TestRecall:
    async def test_returns_hydrated_ranked_entries(self) -> None:
        best, worst = make_row("the answer"), make_row("unrelated")
        harness = _RecallHarness()
        harness.rerank_scores = {"the answer": 5.0, "unrelated": -9.0}
        result = await _run_recall(
            harness,
            harness.patches(
                ann=[(str(best.id), 0.9), (str(worst.id), 0.1)],
                fts=[],
                rows=[best, worst],
            ),
            include_graph_expansion=False,
        )
        assert [memory.content for memory in result.memories] == ["the answer"]
        assert result.total_count == 1

    async def test_empty_index_returns_an_empty_result(self) -> None:
        harness = _RecallHarness()
        result = await _run_recall(
            harness, harness.patches(ann=[], fts=[], rows=[]), include_graph_expansion=False
        )
        assert result.memories == []
        assert result.total_count == 0

    async def test_limit_truncates_the_result_set(self) -> None:
        rows = [make_row(f"fact {i}") for i in range(6)]
        harness = _RecallHarness()
        harness.rerank_scores = {row.content: 5.0 - index * 0.01 for index, row in enumerate(rows)}
        result = await _run_recall(
            harness,
            harness.patches(ann=[(str(row.id), 0.9) for row in rows], fts=[], rows=rows),
            limit=2,
            include_graph_expansion=False,
        )
        assert len(result.memories) == 2

    async def test_graph_expansion_is_skipped_when_disabled(self) -> None:
        base = make_row("base")
        sibling = make_row("sibling")
        harness = _RecallHarness()
        harness.rerank_scores = {"base": 5.0, "sibling": 5.0}
        result = await _run_recall(
            harness,
            harness.patches(
                ann=[(str(base.id), 0.9)],
                fts=[],
                rows=[base],
                entities={base.id: [_entity()]},
                siblings=[sibling],
            ),
            include_graph_expansion=False,
        )
        assert [memory.content for memory in result.memories] == ["base"]

    async def test_graph_sibling_survives_a_full_base_candidate_pool(self) -> None:
        """A sibling must reach the reranker even when the base pool is full.

        Graph expansion appends siblings to the END of the candidate list, so
        slicing the combined pool to RERANK_CANDIDATES silently discarded every
        sibling for any query that already retrieved a full page of base
        candidates — exactly the corpus size where expansion matters most.
        """
        base = [make_row(f"base fact {i}") for i in range(RERANK_CANDIDATES + 5)]
        sibling = make_row("the sibling that answers the query")
        harness = _RecallHarness()
        # Base rows rerank very low, the sibling very high: under absolute
        # scoring the sibling must come out on top (the old min-max assertion
        # that it was the ONLY survivor pinned relative-deletion behavior).
        harness.rerank_scores = {row.content: -9.0 for row in base}
        harness.rerank_scores[sibling.content] = 5.0
        result = await _run_recall(
            harness,
            harness.patches(
                ann=[(str(row.id), 0.4) for row in base],
                fts=[],
                rows=base,
                entities={base[0].id: [_entity()]},
                siblings=[sibling],
            ),
            include_graph_expansion=True,
        )
        assert sibling.content in harness.rerank_inputs[0], (
            "graph sibling never reached the reranker"
        )
        assert result.memories[0].content == sibling.content

    async def test_base_pool_is_still_capped_at_the_rerank_budget(self) -> None:
        base = [make_row(f"base fact {i}") for i in range(RERANK_CANDIDATES + 5)]
        harness = _RecallHarness()
        result = await _run_recall(
            harness,
            harness.patches(ann=[(str(row.id), 0.4) for row in base], fts=[], rows=base),
            include_graph_expansion=False,
        )
        assert len(harness.rerank_inputs[0]) == RERANK_CANDIDATES
        assert result.memories

    async def test_superseded_row_never_reaches_the_reranker(self) -> None:
        stale = make_row("old value", is_latest=False)
        live = make_row("current value")
        harness = _RecallHarness()
        harness.rerank_scores = {"current value": 5.0}
        result = await _run_recall(
            harness,
            harness.patches(
                ann=[(str(stale.id), 0.99), (str(live.id), 0.5)], fts=[], rows=[stale, live]
            ),
            include_graph_expansion=False,
        )
        assert "old value" not in harness.rerank_inputs[0]
        assert [memory.content for memory in result.memories] == ["current value"]

    async def test_fts_only_hit_is_recalled_without_any_ann_hit(self) -> None:
        row = make_row("PROJ-4821 tracks the refactor")
        harness = _RecallHarness()
        harness.rerank_scores = {row.content: 5.0}
        result = await _run_recall(
            harness,
            harness.patches(ann=[], fts=[(row, 0.8)], rows=[]),
            include_graph_expansion=False,
        )
        assert [memory.content for memory in result.memories] == [row.content]


class TestRecallQualityRegressions:
    """Audited recall-quality defects — each test failed before its fix."""

    @pytest.mark.regression
    async def test_thin_raw_gap_keeps_the_runner_up(self) -> None:
        """A hair-thin raw gap between two candidates must not delete the second.

        Min-max normalization forced the weaker of two candidates to exactly
        0.0 regardless of the absolute gap (cosine 0.72 vs 0.71 became 1.0 vs
        0.0), so the relevance dropoff was guaranteed to cut the runner-up.
        Absolute-preserving scaling keeps a thin gap thin: both facts survive.
        """
        dog = make_row("my dog is Rex")
        allergy = make_row("Rex is allergic to chicken")
        harness = _RecallHarness()
        harness.rerank_scores = {dog.content: 2.01, allergy.content: 2.00}
        result = await _run_recall(
            harness,
            harness.patches(
                ann=[(str(dog.id), 0.72), (str(allergy.id), 0.71)],
                fts=[],
                rows=[dog, allergy],
            ),
            include_graph_expansion=False,
        )
        assert sorted(memory.content for memory in result.memories) == sorted(
            [dog.content, allergy.content]
        )

    @pytest.mark.regression
    async def test_boosts_decide_ordering_but_never_survival(self) -> None:
        """A boosted marginal top hit must not push the real answer under the floor.

        The dropoff floor was computed from the post-boost top score, so a
        recent high-importance memory (boost up to 1.38x) taking the top slot
        raised the floor above an un-boosted (0.8x) relevant answer. Survival
        must be decided on pre-boost relevance; boosts only reorder.
        """
        now = datetime.now(UTC)
        old_relevant = make_row(
            "user is allergic to peanuts",
            importance=0.0,
            mentioned_at=now - timedelta(days=400),
            created_at=now - timedelta(days=400),
        )
        boosted_marginal = make_row(
            "user tried a new peanut butter brand", importance=1.0, mentioned_at=now
        )
        noise = make_row("user's favorite color is green", importance=0.5, mentioned_at=now)
        harness = _RecallHarness()
        harness.rerank_scores = {
            old_relevant.content: 0.0,
            boosted_marginal.content: 3.0,
            noise.content: -5.0,
        }
        result = await _run_recall(
            harness,
            harness.patches(
                ann=[
                    (str(boosted_marginal.id), 0.80),
                    (str(old_relevant.id), 0.55),
                    (str(noise.id), 0.30),
                ],
                fts=[],
                rows=[boosted_marginal, old_relevant, noise],
            ),
            include_graph_expansion=False,
        )
        contents = [memory.content for memory in result.memories]
        # Boosts still order the list; the relevant-but-un-boosted answer
        # survives; genuinely irrelevant noise is still cut.
        assert contents == [boosted_marginal.content, old_relevant.content]

    @pytest.mark.regression
    async def test_forgotten_parent_content_is_not_injected(self) -> None:
        """previous_content must not resurrect a version the user deleted."""
        parent = make_row("lives at the old address", is_forgotten=True)
        child = make_row(
            "lives at the new address",
            parent_id=parent.id,
            relation_type=MemoryRelationType.UPDATES.value,
        )
        with (
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(
                retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=[parent])
            ) as fetch_parents,
        ):
            entries = await _build_entries([(child, 0.9)])

        # The liveness fetch must be scoped to the OWNER of the recalled rows:
        # unscoped (None) it returns nothing and every parent silently reads
        # as deleted, dropping previous_content across the board.
        assert fetch_parents.await_args.args[0] == child.user_id
        assert entries[0].previous_content is None

    async def test_expired_forget_after_parent_content_is_not_injected(self) -> None:
        parent = make_row(
            "temporary hotel address", forget_after=datetime.now(UTC) - timedelta(days=1)
        )
        child = make_row(
            "permanent address",
            parent_id=parent.id,
            relation_type=MemoryRelationType.UPDATES.value,
        )
        with (
            patch.object(
                retrieval.pg_store, "get_entities_for_memories", new=AsyncMock(return_value={})
            ),
            patch.object(
                retrieval.pg_store, "get_memories_by_ids", new=AsyncMock(return_value=[parent])
            ) as fetch_parents,
        ):
            entries = await _build_entries([(child, 0.9)])

        # The liveness fetch must be scoped to the OWNER of the recalled rows:
        # unscoped (None) it returns nothing and every parent silently reads
        # as deleted, dropping previous_content across the board.
        assert fetch_parents.await_args.args[0] == child.user_id
        assert entries[0].previous_content is None


# ---------------------------------------------------------------------------
# recall_episodes / _episode_summary_search / recall_transcripts
# ---------------------------------------------------------------------------


class TestRecallEpisodes:
    @pytest.fixture(autouse=True)
    def _pin_local_today(self):
        # recall_episodes anchors its window on the user's local day; pin it so
        # these tests stay hermetic (no user_repository lookup).
        with patch(
            "app.memory.retrieval.local_today", AsyncMock(return_value=date_type(2026, 3, 15))
        ):
            yield

    async def test_entry_hits_outrank_summary_hits(self) -> None:
        entry_day, summary_day = date_type(2026, 3, 12), date_type(2025, 1, 1)
        with (
            patch.object(
                retrieval.pg_store,
                "search_episode_entries",
                new=AsyncMock(
                    return_value=[(entry_day, {"time": "09:30", "text": "shipped the API"})]
                ),
            ),
            patch.object(
                retrieval,
                "_episode_summary_search",
                new=AsyncMock(
                    return_value=[EpisodeHit(date=summary_day, text="a quiet day", score=0.7)]
                ),
            ),
        ):
            hits = await recall_episodes(USER, "shipped the api")
        assert [hit.date for hit in hits] == [entry_day, summary_day]
        assert hits[0].time == "09:30"
        assert hits[1].time is None

    async def test_summary_for_a_day_already_covered_by_entries_is_dropped(self) -> None:
        day = date_type(2026, 3, 12)
        with (
            patch.object(
                retrieval.pg_store,
                "search_episode_entries",
                new=AsyncMock(return_value=[(day, {"time": "09:30", "text": "shipped"})]),
            ),
            patch.object(
                retrieval,
                "_episode_summary_search",
                new=AsyncMock(return_value=[EpisodeHit(date=day, text="day summary")]),
            ),
        ):
            hits = await recall_episodes(USER, "shipped")
        assert len(hits) == 1
        assert hits[0].text == "shipped"

    async def test_entry_without_text_becomes_an_empty_string_not_a_crash(self) -> None:
        day = date_type(2026, 3, 12)
        with (
            patch.object(
                retrieval.pg_store,
                "search_episode_entries",
                new=AsyncMock(return_value=[(day, {"time": "09:30"})]),
            ),
            patch.object(retrieval, "_episode_summary_search", new=AsyncMock(return_value=[])),
        ):
            hits = await recall_episodes(USER, "anything")
        assert hits[0].text == ""

    async def test_limit_truncates_the_combined_hit_list(self) -> None:
        day = date_type(2026, 3, 12)
        rows = [(day, {"time": f"0{i}:00", "text": f"entry {i}"}) for i in range(5)]
        with (
            patch.object(
                retrieval.pg_store, "search_episode_entries", new=AsyncMock(return_value=rows)
            ),
            patch.object(retrieval, "_episode_summary_search", new=AsyncMock(return_value=[])),
        ):
            hits = await recall_episodes(USER, "entry", limit=2)
        assert len(hits) == 2

    async def test_the_window_is_anchored_on_the_calling_users_local_day(self) -> None:
        # The anchor must be THIS user's local today — another user's timezone
        # (or a default one) shifts the window a day at timezone edges.
        local_today = AsyncMock(return_value=date_type(2026, 3, 15))
        with (
            patch("app.memory.retrieval.local_today", local_today),
            patch.object(
                retrieval.pg_store, "search_episode_entries", new=AsyncMock(return_value=[])
            ),
            patch.object(retrieval, "_episode_summary_search", new=AsyncMock(return_value=[])),
        ):
            await recall_episodes(USER, "anything")
        local_today.assert_awaited_once_with(USER)

    async def test_lookback_window_and_tokens_are_passed_to_the_store(self) -> None:
        from app.constants.memory import EPISODE_ENTRY_CANDIDATES, EPISODE_SEARCH_DAYS

        search = AsyncMock(return_value=[])
        with (
            patch.object(retrieval.pg_store, "search_episode_entries", new=search),
            patch.object(retrieval, "_episode_summary_search", new=AsyncMock(return_value=[])),
        ):
            await recall_episodes(USER, "Nadia's BIRTHDAY at 5")
        assert search.await_args.args == (USER, ["nadia's", "birthday"])
        assert search.await_args.kwargs["limit"] == EPISODE_ENTRY_CANDIDATES
        expected_since = date_type(2026, 3, 15) - timedelta(days=EPISODE_SEARCH_DAYS)
        assert search.await_args.kwargs["since"] == expected_since


class TestEpisodeSummarySearch:
    async def test_returns_a_hit_per_summarized_day(self) -> None:
        episode = MagicMock()
        episode.summary = "a productive day"
        with (
            patch.object(retrieval, "embed_query", new=AsyncMock(return_value=[0.1])),
            patch.object(
                retrieval.chroma_store,
                "query_episodes",
                new=AsyncMock(return_value=[(f"{USER}:2026-03-12", 0.812345)]),
            ),
            patch.object(retrieval.pg_store, "get_episode", new=AsyncMock(return_value=episode)),
        ):
            hits = await _episode_summary_search(USER, "productive", 5)
        assert hits == [
            EpisodeHit(date=date_type(2026, 3, 12), text="a productive day", score=0.8123)
        ]

    async def test_unparseable_vector_id_is_skipped_without_a_db_hit(self) -> None:
        get_episode = AsyncMock()
        with (
            patch.object(retrieval, "embed_query", new=AsyncMock(return_value=[0.1])),
            patch.object(
                retrieval.chroma_store,
                "query_episodes",
                new=AsyncMock(return_value=[("no-date-here", 0.8)]),
            ),
            patch.object(retrieval.pg_store, "get_episode", new=get_episode),
        ):
            hits = await _episode_summary_search(USER, "q", 5)
        assert hits == []
        get_episode.assert_not_awaited()

    async def test_day_without_a_summary_is_skipped(self) -> None:
        episode = MagicMock()
        episode.summary = None
        with (
            patch.object(retrieval, "embed_query", new=AsyncMock(return_value=[0.1])),
            patch.object(
                retrieval.chroma_store,
                "query_episodes",
                new=AsyncMock(return_value=[(f"{USER}:2026-03-12", 0.8)]),
            ),
            patch.object(retrieval.pg_store, "get_episode", new=AsyncMock(return_value=episode)),
        ):
            assert await _episode_summary_search(USER, "q", 5) == []

    async def test_missing_episode_row_is_skipped(self) -> None:
        with (
            patch.object(retrieval, "embed_query", new=AsyncMock(return_value=[0.1])),
            patch.object(
                retrieval.chroma_store,
                "query_episodes",
                new=AsyncMock(return_value=[(f"{USER}:2026-03-12", 0.8)]),
            ),
            patch.object(retrieval.pg_store, "get_episode", new=AsyncMock(return_value=None)),
        ):
            assert await _episode_summary_search(USER, "q", 5) == []


class TestRecallTranscripts:
    async def test_embeds_the_query_and_returns_chunk_tuples(self) -> None:
        from app.constants.memory import TRANSCRIPT_RECALL_LIMIT

        chunks = [("2026-03-12", "the exact passage", 0.91)]
        query_chunks = AsyncMock(return_value=chunks)
        with (
            patch.object(retrieval, "embed_query", new=AsyncMock(return_value=[0.5, 0.5])),
            patch.object(retrieval.chroma_store, "query_conversation_chunks", new=query_chunks),
        ):
            got = await recall_transcripts(USER, "that list you gave me")
        assert got == chunks
        query_chunks.assert_awaited_once_with(USER, [0.5, 0.5], TRANSCRIPT_RECALL_LIMIT)

    async def test_custom_limit_is_forwarded(self) -> None:
        query_chunks = AsyncMock(return_value=[])
        with (
            patch.object(retrieval, "embed_query", new=AsyncMock(return_value=[0.5])),
            patch.object(retrieval.chroma_store, "query_conversation_chunks", new=query_chunks),
        ):
            await recall_transcripts(USER, "q", limit=11)
        assert query_chunks.await_args.args[2] == 11


@pytest.mark.unit
class TestEpisodeSearchWindowFollowsTheUsersTimezone:
    async def test_the_lookback_window_starts_from_the_users_local_today(self) -> None:
        """Journal days are keyed by the user's LOCAL date (see user_time.py);
        a lookback computed from the UTC date starts one day early for a UTC+
        user's evening, silently excluding the newest local day from 'since'.
        The window must anchor on the same local day the write path files under.
        """
        local = date_type(2026, 8, 27)
        search = AsyncMock(return_value=[])
        with (
            patch("app.memory.retrieval.local_today", AsyncMock(return_value=local)),
            patch.object(retrieval.pg_store, "search_episode_entries", search),
            patch.object(retrieval, "_episode_summary_search", AsyncMock(return_value=[])),
        ):
            await retrieval.recall_episodes("u1", "ran the release")

        assert search.await_args.kwargs["since"] == local - timedelta(
            days=retrieval.EPISODE_SEARCH_DAYS
        )
