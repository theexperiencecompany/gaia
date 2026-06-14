"""LongMemEval benchmark runner against the real GAIA memory pipeline.

Replays each question's haystack sessions through ``memory_engine.retain``
(real extraction + reconciliation, timestamped via the ``now`` seam), answers
the question from ``recall`` + journal results only, and grades with an
LLM judge. Reference points on this benchmark (full 500, GPT-4o judge):
Hindsight 94.6%, mem0 ~68%.

    uv run python -m scripts.memory_benchmark.longmemeval --dataset /tmp/longmemeval_oracle.json --num 50

Notes vs the official setup: oracle variant (evidence sessions only), a
stratified subset, and the judge runs on the free LLM chain rather than
GPT-4o — directional, not a leaderboard submission.
"""

import argparse
import asyncio
from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.outputs import LLMResult  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.agents.llm.client import register_llm_providers  # noqa: E402
from app.constants.memory import MemorySourceType  # noqa: E402
from app.db.chroma.chromadb import init_chroma  # noqa: E402
from app.db.postgresql import init_postgresql_engine  # noqa: E402
from app.memory.engine import memory_engine  # noqa: E402
from app.memory.extraction import _invoke_structured  # noqa: E402
from app.memory.mappers import entry_to_note  # noqa: E402

_DATE_FORMAT = "%Y/%m/%d %H:%M"

# Conservative flash-lite pricing (deliberately HIGH so the cap trips early and
# never overshoots the user's budget): $/1M tokens.
_USD_PER_1M_INPUT = 0.15
_USD_PER_1M_OUTPUT = 0.60


class CostMeter(BaseCallbackHandler):
    """Accumulates token spend across every memory LLM call and trips a budget.

    Attached to the memory module's silent config so it captures all four call
    types (extraction, reconcile, answer, judge). When projected cost crosses
    ``max_usd`` it flips ``exceeded`` — the run loop checks this between
    questions and stops, so the run can never blow past the budget.
    """

    def __init__(self, max_usd: float) -> None:
        self.max_usd = max_usd
        self.input_tokens = 0
        self.output_tokens = 0
        self.exceeded = False

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * _USD_PER_1M_INPUT
            + self.output_tokens / 1_000_000 * _USD_PER_1M_OUTPUT
        )

    def on_llm_end(self, response: LLMResult, **kwargs: object) -> None:
        usage = (response.llm_output or {}).get("usage_metadata") or (
            response.llm_output or {}
        ).get("token_usage")
        for generations in response.generations:
            for gen in generations:
                message = getattr(gen, "message", None)
                meta = getattr(message, "usage_metadata", None)
                if meta:
                    self.input_tokens += meta.get("input_tokens", 0)
                    self.output_tokens += meta.get("output_tokens", 0)
                    usage = None  # counted from message; skip llm_output fallback
        if usage:
            self.input_tokens += usage.get("input_tokens", usage.get("prompt_tokens", 0))
            self.output_tokens += usage.get("output_tokens", usage.get("completion_tokens", 0))
        if self.cost_usd >= self.max_usd:
            self.exceeded = True


class _Answer(BaseModel):
    # Field order is the generation order — the model reasons BEFORE answering.
    # Forced chain-of-thought is the single biggest lever for a small model on
    # multi-fact ordering, date comparison, and turning preferences into picks.
    relevant_notes: str = Field(
        description=(
            "List the specific memory notes (with their dates) that bear on this "
            "question. For ordering/'which came first' questions, write them out "
            "sorted by the date the event actually happened. For 'how long ago / "
            "how many days/weeks ago' questions, write the explicit subtraction: "
            "today's date minus the event's date = N days (and N/7 weeks), using the "
            "date the EVENT happened, not when it was mentioned or published."
        )
    )
    answer: str = Field(
        description=(
            "The final answer, derived from relevant_notes. Be concise and concrete. "
            "If the question wants a suggestion, commit to one grounded in the notes. "
            "Use 'I don't know' ONLY if relevant_notes is genuinely empty."
        )
    )


class _Verdict(BaseModel):
    # Reason first, decide second — stops flash-lite from snap literal-matching.
    gold_asserts: str = Field(
        description="In one phrase, the core fact, value, or preference the gold answer asserts."
    )
    model_conveys_it: str = Field(
        description=(
            "Does the model answer convey that same thing (possibly worded differently, "
            "or naming the same entity/event by another description)? Explain briefly."
        )
    )
    correct: bool = Field(description="True if the model answer conveys the gold's core meaning.")


def _parse_date(raw: str) -> datetime:
    cleaned = " ".join(part for part in raw.split() if not part.startswith("("))
    return datetime.strptime(cleaned, _DATE_FORMAT).replace(tzinfo=UTC)


async def _answer(question: str, question_date: str, memories: list[str]) -> str:
    context = "\n".join(f"- {m}" for m in memories) or "(no memories found)"
    result = await _invoke_structured(
        _Answer,
        [
            # Static system prompt — all benchmark-derived data (date, memory
            # notes, question) travels in the human message so the privileged
            # prompt is never built from dataset content.
            SystemMessage(
                content=(
                    "Answer the user's question using ONLY the memory notes in the "
                    "user message (extracted from past conversations; bracketed "
                    "dates say when something happened / was mentioned). The user "
                    "message also states today's date. Be concise.\n"
                    "- Use the dates for any 'when / how long ago / which came first' "
                    "arithmetic, and sum or compare quantities across notes for any "
                    "'total / most / higher' question. For dates, use when the event "
                    "actually happened (an [occurred] date or a purchase/booking date), "
                    "NOT when it was merely [mentioned].\n"
                    "- For 'which did I get/do first, X or Y' find the dated note for X "
                    "and for Y, compare the two dates, and name the EARLIER one.\n"
                    "- For 'order / sequence / what came first' questions, gather every "
                    "relevant dated note, sort by date, and list them ALL in that order "
                    "(do not skip any and do not stop at one).\n"
                    "- When notes give conflicting values for the SAME attribute (a "
                    "changed amount, status, job, city), trust the one with the most "
                    "recent date — the world changed; never answer with the stale value.\n"
                    "- For suggestion / recommendation / 'what should I do' questions you "
                    "MUST give a concrete answer grounded in the remembered preferences, "
                    "interests, routines, or plans (e.g. 'you have a 40-min commute and "
                    "like podcasts, so try ...'). NEVER abstain and NEVER refuse for "
                    "missing details like location — work with what the notes provide.\n"
                    "- Only if the notes contain nothing relevant at all, reply exactly "
                    '"I don\'t know".'
                )
            ),
            HumanMessage(
                content=(
                    f"Today is {question_date}.\n\nMEMORY NOTES:\n{context}\n\nQuestion: {question}"
                )
            ),
        ],
        operation="lme_answer",
    )
    return result.answer if result else "I don't know"


async def _judge(question: str, gold: str, model_answer: str) -> bool:
    result = await _invoke_structured(
        _Verdict,
        [
            SystemMessage(
                content=(
                    "You grade question answering. Decide whether the model answer "
                    "conveys the same information as the gold answer. Grade on MEANING, "
                    "not wording. Mark CORRECT when:\n"
                    "- It states the same fact in different words, or names the same "
                    "entity/event by a different but unambiguous description (e.g. 'the "
                    "Lakers vs Bulls game' == 'an NBA game at the Staples Center'; "
                    "'Acme Corp' == 'the company he works at').\n"
                    "- Dates/quantities match even if partial or rephrased.\n"
                    "- The gold describes the KIND of response the user wants (e.g. 'the "
                    "user would prefer suggestions about podcasts') and the model makes a "
                    "concrete suggestion consistent with that preference.\n"
                    "- The answer contains the correct fact plus extra detail.\n"
                    "Mark INCORRECT only when the model gives a wrong/contradictory value, "
                    "names a different entity, abstains ('I don't know'), or omits the "
                    "asked-for fact. When the core information matches, prefer CORRECT.\n\n"
                    "EXAMPLES:\n"
                    "Gold: 'the user would prefer suggestions about podcasts' | Model: "
                    "'Since you have a long commute, you could listen to podcasts.' -> "
                    "CORRECT (suggestion honors the preference).\n"
                    "Gold: 'an NBA game at the Staples Center' | Model: 'the Lakers vs "
                    "Bulls game' -> CORRECT (same event, different description).\n"
                    "Gold: '$400,000' | Model: '$350,000' -> INCORRECT (wrong value).\n"
                    "Gold: 'Samsung Galaxy S22' | Model: 'I don't know' -> INCORRECT "
                    "(abstained)."
                )
            ),
            HumanMessage(
                content=f"Question: {question}\nGold answer: {gold}\nModel answer: {model_answer}"
            ),
        ],
        operation="lme_judge",
    )
    return bool(result and result.correct)


async def _run_question(
    item: dict, index: int, total: int, diagnose: bool = False
) -> tuple[str, bool, str]:
    user_id = f"lme-{item['question_id']}"
    qtype = item["question_type"]
    try:
        for date_raw, session in zip(item["haystack_dates"], item["haystack_sessions"]):
            messages = [
                {"role": turn["role"], "content": turn["content"]}
                for turn in session
                if turn.get("content")
            ]
            if not messages:
                continue
            await memory_engine.retain(
                user_id,
                messages,
                source_type=MemorySourceType.CONVERSATION,
                now=_parse_date(date_raw),
            )

        # Higher limit than a normal chat turn: counting / multi-session
        # questions ("how many appointments did I have") need every matching
        # instance retrieved, not just the top few.
        recall = await memory_engine.recall(user_id, item["question"], limit=20)
        episode_hits = await memory_engine.recall_episodes(user_id, item["question"], limit=12)
        transcript_hits = await memory_engine.recall_transcripts(user_id, item["question"], limit=5)
        notes = (
            [entry_to_note(m) for m in recall.memories]
            + [f"(journal {hit.date.isoformat()}) {hit.text}" for hit in episode_hits[:12]]
            + [f"(conversation on {date})\n{text}" for date, text, _ in transcript_hits]
        )
        model_answer = await _answer(item["question"], item["question_date"], notes)
        correct = await _judge(item["question"], str(item["answer"]), model_answer)
        print(
            f"[{index + 1}/{total}] {'OK ' if correct else 'MISS'} {qtype:26} "
            f"q={item['question'][:48]!r} -> {model_answer[:60]!r} (gold {str(item['answer'])[:40]!r})",
            flush=True,
        )
        if diagnose and not correct:
            await _print_diagnosis(user_id, item, notes, model_answer)
        return qtype, correct, model_answer
    finally:
        await memory_engine.delete_all(user_id)


async def _print_diagnosis(item_user: str, item: dict, notes: list[str], answer: str) -> None:
    """Classify where the chain broke: extraction, retrieval, or answering."""
    stored = await memory_engine.list_memories(item_user, page=1, page_size=200)
    gold = str(item["answer"]).lower()
    gold_tokens = [t for t in gold.replace(",", " ").split() if len(t) > 3][:4]
    in_store = [
        m.content for m in stored.memories if any(t in m.content.lower() for t in gold_tokens)
    ]
    in_notes = [n for n in notes if any(t in n.lower() for t in gold_tokens)]
    if not in_store:
        verdict = "EXTRACTION-MISS (gold info never stored)"
    elif not in_notes:
        verdict = "RETRIEVAL-MISS (stored but not recalled)"
    else:
        verdict = "ANSWER/JUDGE-MISS (info was in the notes)"
    print(f"    DIAG {verdict}", flush=True)
    print(f"    gold: {gold[:100]}", flush=True)
    print(f"    stored matching: {[s[:70] for s in in_store[:3]]}", flush=True)
    print(f"    notes matching: {[n[:70] for n in in_notes[:2]]}", flush=True)
    print(f"    total stored: {stored.total_count} | notes: {len(notes)}", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run LongMemEval against the memory engine.")
    parser.add_argument("--dataset", required=True, help="Path to longmemeval_*.json")
    parser.add_argument("--num", type=int, default=50, help="Stratified sample size")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--types", help="Comma-separated question types to include")
    parser.add_argument(
        "--diagnose", action="store_true", help="Classify each miss (extraction/retrieval/answer)"
    )
    parser.add_argument(
        "--max-usd",
        type=float,
        default=2.0,
        help="Hard cost ceiling — abort before exceeding this (conservative pricing).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=16,
        help="How many questions to run in parallel.",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.0,
        help=(
            "Circuit breaker: after --warmup questions, abort if running accuracy "
            "is below this (0 disables). Saves a full run on a config that won't hit target."
        ),
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=60,
        help="Questions to grade before the --min-accuracy breaker can trip.",
    )
    args = parser.parse_args()

    init_postgresql_engine()
    init_chroma()
    register_llm_providers()

    # Hard budget guard: attach a cost meter to the memory module's silent
    # config so every extraction/reconcile/answer/judge call counts. The run
    # loop stops the moment projected spend reaches --max-usd.
    import app.memory.extraction as extraction_mod

    meter = CostMeter(args.max_usd)
    extraction_mod._SILENT_CONFIG = {
        **extraction_mod._SILENT_CONFIG,
        "callbacks": [meter],
    }

    data = json.loads(Path(args.dataset).read_text())
    by_type: dict[str, list[dict]] = defaultdict(list)
    for item in data:
        if str(item["question_id"]).endswith("_abs"):
            continue  # abstention split needs its own grading protocol
        by_type[item["question_type"]].append(item)

    # Deterministic, seeded sampling for reproducible benchmark runs — not a
    # security context, so the stdlib PRNG is the correct tool here.
    rng = random.Random(args.seed)  # NOSONAR python:S2245
    per_type = max(1, args.num // len(by_type))
    if args.types:
        wanted = {t.strip() for t in args.types.split(",")}
        by_type = defaultdict(list, {k: v for k, v in by_type.items() if k in wanted})
        per_type = max(1, args.num // max(len(by_type), 1))

    sample: list[dict] = []
    for items in by_type.values():
        rng.shuffle(items)  # NOSONAR python:S2245
        sample.extend(items[:per_type])
    rng.shuffle(sample)  # NOSONAR python:S2245
    print(f"Running {len(sample)} questions across {len(by_type)} types...\n", flush=True)

    scores: dict[str, list[bool]] = defaultdict(list)
    semaphore = asyncio.Semaphore(args.concurrency)
    tally = {"done": 0, "correct": 0}
    aborted = {"budget": False, "accuracy": False}

    async def _bounded(index: int, item: dict) -> tuple[str, bool, str] | None:
        # Gate at acquire time so once a ceiling is hit no NEW question starts;
        # in-flight ones finish (a few cents / a few questions of overshoot).
        if meter.exceeded or aborted["accuracy"]:
            return None
        async with semaphore:
            if meter.exceeded:
                aborted["budget"] = True
                return None
            if aborted["accuracy"]:
                return None
            outcome = await _run_question(item, index, len(sample), diagnose=args.diagnose)
            tally["done"] += 1
            tally["correct"] += int(outcome[1])
            # Circuit breaker: once past warmup, abort a run that is clearly not
            # going to hit target so we can review + fix instead of waiting it out.
            if args.min_accuracy and tally["done"] >= args.warmup:
                running = tally["correct"] / tally["done"]
                if running < args.min_accuracy and not aborted["accuracy"]:
                    aborted["accuracy"] = True
                    print(
                        f"\n!! Accuracy breaker: {running:.1%} < {args.min_accuracy:.0%} "
                        f"after {tally['done']} questions — aborting for review.\n",
                        flush=True,
                    )
            return outcome

    outcomes = await asyncio.gather(*(_bounded(i, item) for i, item in enumerate(sample)))
    for outcome in outcomes:
        if outcome is not None:
            qtype, correct, _ = outcome
            scores[qtype].append(correct)

    graded = sum(len(v) for v in scores.values())
    if aborted["accuracy"]:
        print("=== LONGMEMEVAL (ABORTED — accuracy breaker) RESULTS ===")
    elif aborted["budget"] or graded < len(sample):
        print(
            f"\n!! Budget ceiling ${args.max_usd:.2f} reached "
            f"(spent ~${meter.cost_usd:.2f}); graded {graded}/{len(sample)}.\n"
        )
        print("=== LONGMEMEVAL (PARTIAL — budget-limited) RESULTS ===")
    else:
        print("\n=== LONGMEMEVAL (oracle subset) RESULTS ===")
    total_correct = total = 0
    for qtype in sorted(scores):
        results = scores[qtype]
        total_correct += sum(results)
        total += len(results)
        print(
            f"  {qtype:28} {sum(results)}/{len(results)} = {100 * sum(results) / len(results):.0f}%"
        )
    print(f"  {'OVERALL':28} {total_correct}/{total} = {100 * total_correct / total:.1f}%")
    print(
        f"\n  Spend: ~${meter.cost_usd:.2f} "
        f"({meter.input_tokens:,} in / {meter.output_tokens:,} out tokens, "
        f"cap ${args.max_usd:.2f})"
    )


if __name__ == "__main__":
    asyncio.run(main())
