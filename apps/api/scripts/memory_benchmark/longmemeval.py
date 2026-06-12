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
    answer: str = Field(description="Concise answer, or 'I don't know' if not in the memories")


class _Verdict(BaseModel):
    correct: bool = Field(description="Whether the model answer matches the gold answer")


def _parse_date(raw: str) -> datetime:
    cleaned = " ".join(part for part in raw.split() if not part.startswith("("))
    return datetime.strptime(cleaned, _DATE_FORMAT).replace(tzinfo=UTC)


async def _answer(question: str, question_date: str, memories: list[str]) -> str:
    context = "\n".join(f"- {m}" for m in memories) or "(no memories found)"
    result = await _invoke_structured(
        _Answer,
        [
            SystemMessage(
                content=(
                    f"Today is {question_date}. Answer the user's question using ONLY the "
                    "memory notes below (extracted from past conversations; bracketed "
                    "dates say when something happened / was mentioned). Be concise. Use "
                    "the dates for any 'when / how long ago / which came first' "
                    "arithmetic, and sum or compare quantities across notes for any "
                    "'total / most / higher' question. If the question asks for "
                    "suggestions or recommendations, do NOT abstain: answer by stating "
                    "the remembered preferences, interests, or plans that should guide "
                    "the suggestion (e.g. 'you enjoy stand-up comedy specials on "
                    "Netflix, so...'). Only if the notes contain nothing relevant at "
                    'all, reply exactly "I don\'t know".\n\nMEMORY NOTES:\n' + context
                )
            ),
            HumanMessage(content=question),
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
                    "conveys the same information as the gold answer for the question. "
                    "Paraphrases, partial dates that match, and extra detail are fine; "
                    "contradictions or missing the asked-for fact are incorrect."
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

        recall = await memory_engine.recall(user_id, item["question"], limit=12)
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

    rng = random.Random(args.seed)
    per_type = max(1, args.num // len(by_type))
    if args.types:
        wanted = {t.strip() for t in args.types.split(",")}
        by_type = defaultdict(list, {k: v for k, v in by_type.items() if k in wanted})
        per_type = max(1, args.num // max(len(by_type), 1))

    sample: list[dict] = []
    for items in by_type.values():
        rng.shuffle(items)
        sample.extend(items[:per_type])
    rng.shuffle(sample)
    print(f"Running {len(sample)} questions across {len(by_type)} types...\n", flush=True)

    scores: dict[str, list[bool]] = defaultdict(list)
    stopped_early = False
    for index, item in enumerate(sample):
        if meter.exceeded:
            stopped_early = True
            print(
                f"\n!! Budget ceiling ${args.max_usd:.2f} reached after {index} questions "
                f"(spent ~${meter.cost_usd:.2f}); stopping early.\n",
                flush=True,
            )
            break
        qtype, correct, _ = await _run_question(item, index, len(sample), diagnose=args.diagnose)
        scores[qtype].append(correct)

    if stopped_early:
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
