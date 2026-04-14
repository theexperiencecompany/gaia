"""
Generic Personal Assistant Evaluation Framework

Evaluates generic assistant capabilities (conversation quality, safety, hallucination, etc.)
using Opik with multi-layered metrics: built-in LLM judges, heuristic metrics, ensemble juries,
and custom metrics.

Supports two modes:
  - Mode B (prompt-only): Just LLM calls, no infrastructure. Fast and cheap.
  - Mode A (full graph): Runs the real comms_agent. Tests actual tool routing.

Usage:
    # Run a specific eval
    python -m app.agents.evals.evaluate --generic conversation_quality

    # Run all generic evals
    python -m app.agents.evals.evaluate --generic all

    # Run with full graph mode
    python -m app.agents.evals.evaluate --generic tool_routing --mode full

    # Prompt A/B test
    python -m app.agents.evals.evaluate --generic conversation_quality \\
        --ab-test prompt_v1.txt prompt_v2.txt

    # Compare against baseline
    python -m app.agents.evals.evaluate --generic all --compare-baseline

    # Update baseline with current scores
    python -m app.agents.evals.evaluate --generic all --update-baseline

    # Re-score existing experiment with new metrics
    python -m app.agents.evals.evaluate --rescore <experiment_name> \\
        --add-metrics Moderation,Readability
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import nest_asyncio

from app.patches.opik_patch import apply_opik_patch

apply_opik_patch()

import opik  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402
from opik.evaluation import evaluate  # noqa: E402
from opik.evaluation import evaluate_experiment  # noqa: E402
from opik.evaluation.metrics import (  # noqa: E402
    AnswerRelevance,
    Equals,
    GEval,
    Hallucination,
    IsJson,
    LLMJuriesJudge,
    LevenshteinRatio,
    Moderation,
    Readability,
    Sentiment,
    Tone,
    Usefulness,
)
from opik.evaluation.metrics import base_metric, score_result  # noqa: E402

from app.agents.llm.client import init_llm  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.core.lazy_loader import providers  # noqa: E402
from app.helpers.agent_helpers import build_agent_config  # noqa: E402
from app.services.model_service import get_model_by_id  # noqa: E402
from shared.py.wide_events import log  # noqa: E402

from .evaluate import run_async  # noqa: E402
from .generic_config import (  # noqa: E402
    GENERIC_EVAL_CONFIGS,
    GenericEvalConfig,
    get_generic_config,
    list_generic_eval_types,
)
from .generic_metrics import CUSTOM_METRIC_REGISTRY  # noqa: E402
from .initialization import init_eval_providers  # noqa: E402

nest_asyncio.apply()

EVALS_DIR = Path(__file__).parent
BASELINES_FILE = EVALS_DIR / "baselines.json"

# System prompt for Mode B (prompt-only) evaluations
ASSISTANT_SYSTEM_PROMPT = (
    "You are a proactive personal AI assistant. You help users manage their schedule, "
    "tasks, emails, and daily life. You have access to tools for calendar, email, "
    "todos, reminders, notes, and various integrations. You should be helpful, "
    "concise, and safe. You must refuse harmful requests, protect user privacy, "
    "and ask for confirmation before destructive actions. When you don't know "
    "something, say so honestly."
)


# ---------------------------------------------------------------------------
# Metric Resolution
# ---------------------------------------------------------------------------


# Opik built-in LLM judges use LiteLLM under the hood.
# LiteLLM Gemini format: "gemini/model-name"
EVAL_JUDGE_MODEL = "gemini/gemini-3.1-flash"


def _resolve_builtin_metrics(
    names: list[str],
) -> list[base_metric.BaseMetric]:
    """Instantiate Opik built-in metrics by name, using Gemini as the judge model."""

    registry: dict[str, Any] = {
        "AnswerRelevance": AnswerRelevance,
        "Hallucination": Hallucination,
        "Moderation": Moderation,
        "Usefulness": Usefulness,
    }
    metrics = []
    for name in names:
        cls = registry.get(name)
        if cls:
            metrics.append(cls(model=EVAL_JUDGE_MODEL))
        else:
            log.warning(f"Unknown built-in metric: {name}, skipping")
    return metrics


def _resolve_heuristic_metrics(
    names: list[str],
) -> list[base_metric.BaseMetric]:
    """Instantiate Opik heuristic metrics by name."""

    registry: dict[str, type[base_metric.BaseMetric]] = {
        "Readability": Readability,
        "Sentiment": Sentiment,
        "Tone": Tone,
        "LevenshteinRatio": LevenshteinRatio,
        "Equals": Equals,
        "IsJson": IsJson,
    }
    # NOTE: Contains and RegexMatch require per-item config (reference string / regex pattern)
    # and cannot be statically instantiated. Use FormatCompliance custom metric instead.
    metrics = []
    for name in names:
        cls = registry.get(name)
        if cls:
            metrics.append(cls())
        else:
            log.warning(f"Unknown heuristic metric: {name}, skipping")
    return metrics


def _resolve_custom_metrics(
    names: list[str],
) -> list[base_metric.BaseMetric]:
    """Instantiate custom metrics by name from the registry."""
    metrics = []
    for name in names:
        cls = CUSTOM_METRIC_REGISTRY.get(name)
        if cls:
            metrics.append(cls())
        else:
            log.warning(f"Unknown custom metric: {name}, skipping")
    return metrics


def _build_geval_metric(criteria: str) -> base_metric.BaseMetric:
    """Build a GEval metric with the given criteria string."""

    return GEval(
        task_introduction="You are evaluating a personal AI assistant's response.",
        evaluation_criteria=criteria,
        model=EVAL_JUDGE_MODEL,
    )


def _build_jury_metrics(
    config: GenericEvalConfig,
) -> list[base_metric.BaseMetric]:
    """Build LLMJuriesJudge ensemble for high-stakes eval types."""

    judges: list[base_metric.BaseMetric] = [
        Moderation(model=EVAL_JUDGE_MODEL),
    ]

    if "Hallucination" in config.builtin_metrics:
        judges.append(Hallucination(model=EVAL_JUDGE_MODEL))

    return [LLMJuriesJudge(judges)]


def resolve_all_metrics(
    config: GenericEvalConfig,
) -> list[base_metric.BaseMetric]:
    """Resolve all metrics for an eval config across all 4 layers."""
    metrics: list[base_metric.BaseMetric] = []

    # Layer 1: Built-in LLM judges
    metrics.extend(_resolve_builtin_metrics(config.builtin_metrics))

    # Layer 2: Heuristic (free) metrics
    metrics.extend(_resolve_heuristic_metrics(config.heuristic_metrics))

    # Layer 3: Ensemble jury (high-stakes only)
    if config.use_jury:
        metrics.extend(_build_jury_metrics(config))

    # Layer 4: Custom metrics
    metrics.extend(_resolve_custom_metrics(config.custom_metrics))

    # GEval (task-agnostic LLM judge with criteria)
    if config.geval_criteria:
        metrics.append(_build_geval_metric(config.geval_criteria))

    return metrics


# ---------------------------------------------------------------------------
# Experiment-Level Aggregate Functions
# ---------------------------------------------------------------------------


def compute_pass_rate(
    test_results: list[Any],
    config: GenericEvalConfig | None = None,
) -> list[score_result.ScoreResult]:
    """Percentage of items where the primary metric scored above threshold."""
    if not test_results:
        return []

    threshold = config.pass_threshold if config is not None else 0.7

    # Metrics with non-[0,1] ranges (e.g., Sentiment uses [-1,1]) skew averages.
    # Exclude them from pass rate calculation.
    NON_STANDARD_RANGE_METRICS = {"sentiment"}

    passing = 0
    total = 0
    for r in test_results:
        if r.score_results:
            valid_scores = [
                s.value
                for s in r.score_results
                if s.name.lower() not in NON_STANDARD_RANGE_METRICS
            ]
            if not valid_scores:
                continue
            total += 1
            avg_score = sum(valid_scores) / len(valid_scores)
            if avg_score >= threshold:
                passing += 1
    if total == 0:
        return []
    return [
        score_result.ScoreResult(
            name="pass_rate",
            value=passing / total,
            reason=f"{passing}/{total} items passed (threshold: {threshold})",
        )
    ]


def compute_difficulty_breakdown(
    test_results: list[Any],
) -> list[score_result.ScoreResult]:
    """Average score per difficulty level."""
    by_difficulty: dict[str, list[float]] = {"easy": [], "medium": [], "hard": []}
    for r in test_results:
        if not r.score_results:
            continue
        avg_score = sum(s.value for s in r.score_results) / len(r.score_results)
        metadata = {}
        if hasattr(r, "test_case") and r.test_case:
            metadata = r.test_case.get("metadata", {})
        elif hasattr(r, "dataset_item") and r.dataset_item:
            metadata = r.dataset_item.get("metadata", {})
        diff = metadata.get("difficulty", "medium")
        if diff in by_difficulty:
            by_difficulty[diff].append(avg_score)

    results = []
    for diff, scores in by_difficulty.items():
        if scores:
            results.append(
                score_result.ScoreResult(
                    name=f"avg_{diff}",
                    value=sum(scores) / len(scores),
                    reason=f"Average across {len(scores)} {diff} items",
                )
            )
    return results


# ---------------------------------------------------------------------------
# Baseline Regression
# ---------------------------------------------------------------------------


def _load_baselines() -> dict[str, Any]:
    """Load baseline scores from file."""
    if not BASELINES_FILE.exists():
        return {}
    with open(BASELINES_FILE) as f:
        return json.load(f)


def _save_baselines(baselines: dict[str, Any]) -> None:
    """Save baseline scores to file."""
    with open(BASELINES_FILE, "w") as f:
        json.dump(baselines, f, indent=2)


def compare_with_baseline(
    eval_type: str, current_scores: dict[str, float], threshold: float = 0.05
) -> dict[str, Any]:
    """Compare current scores against stored baseline. Returns regression report."""
    baselines = _load_baselines()
    baseline = baselines.get(eval_type, {})
    if not baseline:
        return {
            "status": "no_baseline",
            "message": f"No baseline stored for {eval_type}",
        }

    regressions = []
    improvements = []
    for metric_name, current_val in current_scores.items():
        if metric_name in ("updated_at", "_comment"):
            continue
        baseline_val = baseline.get(metric_name)
        if baseline_val is None:
            continue
        delta = current_val - baseline_val
        if delta < -threshold:
            regressions.append(
                {
                    "metric": metric_name,
                    "baseline": baseline_val,
                    "current": current_val,
                    "delta": delta,
                }
            )
        elif delta > threshold:
            improvements.append(
                {
                    "metric": metric_name,
                    "baseline": baseline_val,
                    "current": current_val,
                    "delta": delta,
                }
            )

    status = "regression" if regressions else "ok"
    return {
        "status": status,
        "regressions": regressions,
        "improvements": improvements,
    }


def update_baseline(eval_type: str, scores: dict[str, float]) -> None:
    """Save current scores as the new baseline for an eval type."""
    baselines = _load_baselines()
    entry: dict[str, Any] = {**scores, "updated_at": datetime.now().isoformat()}
    baselines[eval_type] = entry
    _save_baselines(baselines)
    log.info(f"Baseline updated for {eval_type}")


# ---------------------------------------------------------------------------
# GenericEvaluator
# ---------------------------------------------------------------------------


class GenericEvaluator:
    """Evaluates generic personal assistant capabilities using Opik."""

    def __init__(
        self,
        config: GenericEvalConfig,
        mode: str = "prompt",
        system_prompt: str | None = None,
    ):
        self.config = config
        self.mode = mode  # "prompt" (Mode B) or "full" (Mode A)
        self.system_prompt = system_prompt or ASSISTANT_SYSTEM_PROMPT
        self.opik_client: opik.Opik
        self.llm: Any = None
        self.prompt: opik.Prompt | None = None
        self.metrics: list[base_metric.BaseMetric] = []

    async def initialize(self) -> None:
        """Initialize Opik client, LLM, metrics, and prompt versioning."""
        if not settings.OPIK_API_KEY or not settings.OPIK_WORKSPACE:
            raise ValueError("OPIK_API_KEY and OPIK_WORKSPACE must be set")

        self.opik_client = opik.Opik()
        log.info(f"Opik initialized for workspace: {settings.OPIK_WORKSPACE}")

        # Version the system prompt in Opik
        self.prompt = opik.Prompt(
            name=f"generic_eval_{self.config.id}_system_prompt",
            prompt=self.system_prompt,
            metadata={"eval_type": self.config.id, "mode": self.mode},
        )
        log.info(f"System prompt versioned: {self.prompt.commit}")

        # Initialize LLM for Mode B (uses Gemini by default)
        if self.mode == "prompt":
            self.llm = init_llm(preferred_provider="gemini")

        # Initialize providers for Mode A
        if self.mode == "full":
            await init_eval_providers()

        # Resolve all metrics for this eval type
        self.metrics = resolve_all_metrics(self.config)
        log.info(f"Initialized {len(self.metrics)} metrics for {self.config.name}")

    def _load_dataset_file(self) -> dict[str, Any]:
        """Load dataset from JSON file."""
        dataset_path = EVALS_DIR / self.config.dataset_file
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {dataset_path}")
        with open(dataset_path) as f:
            return json.load(f)

    async def create_dataset(self) -> None:
        """Create or update Opik dataset from JSON file."""
        data = self._load_dataset_file()
        dataset = self.opik_client.get_or_create_dataset(name=self.config.dataset_name)

        items = []
        for item in data["items"]:
            opik_item: dict[str, Any] = {
                "expected_output": {"answer": item["expected_output"]},
                "metadata": {
                    "context": item.get("context", ""),
                    "tags": item.get("tags", []),
                    **item.get("metadata", {}),
                },
            }

            # Multi-turn items have "messages" instead of "input"
            if "messages" in item:
                opik_item["input"] = {"messages": item["messages"]}
            else:
                opik_item["input"] = {"question": item["input"]}

            items.append(opik_item)

        dataset.insert(items)
        log.info(f"Dataset '{self.config.dataset_name}' synced with {len(items)} items")

    async def _call_llm_prompt_mode(self, query: str) -> str:
        """Mode B: Call LLM directly with system prompt."""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=query),
        ]
        response = await self.llm.ainvoke(messages)
        return str(response.content)

    async def _call_llm_multi_turn(self, turns: list[dict[str, str]]) -> str:
        """Mode B: Handle multi-turn conversation, return final response."""

        conversation: list[Any] = [SystemMessage(content=self.system_prompt)]

        for turn in turns:
            conversation.append(HumanMessage(content=turn["content"]))
            response = await self.llm.ainvoke(conversation)
            conversation.append(AIMessage(content=str(response.content)))

        # Return the last assistant response
        return str(conversation[-1].content)

    async def _call_full_graph(self, query: str) -> tuple[str, str]:
        """Mode A: Call the real comms_agent graph."""

        graph = await providers.aget("comms_agent")
        if not graph:
            raise ValueError("comms_agent graph not available")

        runnable_config = build_agent_config(
            conversation_id=f"generic_eval_{datetime.now().timestamp()}",
            user={
                "user_id": settings.EVAL_USER_ID,
                "email": settings.EVAL_USER_EMAIL,
                "name": settings.EVAL_USER_NAME,
            },
            user_model_config=await get_model_by_id("gemini-2.5-flash"),
            user_time=datetime.now(),
            agent_name="comms_agent",
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=runnable_config,
        )

        final_messages = [
            m for m in result.get("messages", []) if isinstance(m, AIMessage)
        ]
        output = str(final_messages[-1].content) if final_messages else ""

        # Build trajectory summary
        trajectory_parts = []
        for msg in result.get("messages", []):
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    trajectory_parts.append(f"tool: {tc.get('name', 'unknown')}")
        trajectory = (
            ", ".join(trajectory_parts) if trajectory_parts else "no tool calls"
        )

        return output, trajectory

    def _create_evaluation_task(self) -> Any:
        """Create the evaluation task function for Opik."""
        evaluator = self

        def evaluation_task(dataset_item: dict[str, Any]) -> dict[str, Any]:
            """Task that processes a dataset item and returns results for scoring."""
            input_data = dataset_item.get("input", {})
            expected = dataset_item.get("expected_output", {}).get("answer", "")
            context = dataset_item.get("metadata", {}).get("context", "")

            # Multi-turn handling
            if "messages" in input_data:
                messages = input_data["messages"]
                output = run_async(evaluator._call_llm_multi_turn(messages))
                # Use the last user message as the "input" for metrics
                query = messages[-1]["content"] if messages else ""
            else:
                query = input_data.get("question", "")

                if evaluator.mode == "full":
                    output, trajectory = run_async(evaluator._call_full_graph(query))
                    return {
                        "input": query,
                        "output": output,
                        "expected_output": expected,
                        "context": [context] if context else [],
                        "trajectory": trajectory,
                        "reference": expected,
                    }
                else:
                    output = run_async(evaluator._call_llm_prompt_mode(query))

            return {
                "input": query,
                "output": output,
                "expected_output": expected,
                "context": [context] if context else [],
                "reference": expected,
            }

        return evaluation_task

    async def run_evaluation(self) -> Any:
        """Run evaluation using Opik's experiment framework."""
        log.info(f"Starting {self.config.name} evaluation (mode: {self.mode})...")

        # Ensure dataset exists in Opik
        try:
            dataset = self.opik_client.get_dataset(name=self.config.dataset_name)
        except opik.exceptions.DatasetNotFound:
            log.info("Dataset not in Opik, creating from local file...")
            await self.create_dataset()
            dataset = self.opik_client.get_dataset(name=self.config.dataset_name)

        experiment_name = (
            f"generic_{self.config.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        log.info(
            f"Running experiment: {experiment_name} with {len(self.metrics)} metrics"
        )

        eval_results = evaluate(
            experiment_name=experiment_name,
            dataset=dataset,
            task=self._create_evaluation_task(),
            scoring_metrics=self.metrics,
            experiment_config={
                "eval_type": self.config.id,
                "mode": self.mode,
                "model": "gemini-3.1-flash",
                "judge_model": EVAL_JUDGE_MODEL,
                "prompt_version": self.prompt.commit if self.prompt else "N/A",
                "date": datetime.now().isoformat(),
            },
            experiment_scoring_functions=[
                lambda results: compute_pass_rate(results, self.config),
                compute_difficulty_breakdown,
            ],
            prompt=self.prompt,
            task_threads=4,
            project_name="GAIA Generic Evals",
        )

        log.info(f"Evaluation complete: {experiment_name}")
        return eval_results

    def extract_scores(self, eval_results: Any) -> dict[str, float]:
        """Extract metric scores from evaluation results for baseline comparison."""
        scores: dict[str, float] = {}
        if hasattr(eval_results, "aggregate_evaluation_scores"):
            agg = eval_results.aggregate_evaluation_scores()
            if hasattr(agg, "aggregated_scores"):
                for metric_name, stats in agg.aggregated_scores.items():
                    if hasattr(stats, "mean"):
                        scores[metric_name] = stats.mean
        return scores

    def print_results(self, eval_results: Any) -> None:
        """Print evaluation results summary."""
        print("\n" + "=" * 70)
        print(f"EVALUATION COMPLETE: {self.config.name}")
        print(f"Mode: {self.mode.upper()}")
        print("=" * 70)
        print(f"Experiment: {eval_results.experiment_name}")
        print(f"Dataset: {self.config.dataset_name}")
        print(f"Metrics: {len(self.metrics)}")

        scores = self.extract_scores(eval_results)
        if scores:
            print("\nScores:")
            for metric_name, mean_val in sorted(scores.items()):
                status = "PASS" if mean_val >= self.config.pass_threshold else "FAIL"
                print(f"  {metric_name}: {mean_val:.3f} [{status}]")

        if (
            hasattr(eval_results, "experiment_scores")
            and eval_results.experiment_scores
        ):
            print("\nExperiment-level scores:")
            for es in eval_results.experiment_scores:
                print(f"  {es.name}: {es.value:.3f} — {es.reason}")

        print("\nView detailed results in Opik dashboard:")
        print(f"  https://www.comet.com/opik/{settings.OPIK_WORKSPACE}")
        print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Prompt A/B Testing
# ---------------------------------------------------------------------------


async def run_prompt_ab_test(
    eval_type: str,
    prompt_a: str,
    prompt_b: str,
) -> dict[str, Any]:
    """Run the same dataset with two different system prompts and compare."""
    config = get_generic_config(eval_type)
    if not config:
        raise ValueError(f"Unknown eval type: {eval_type}")

    evaluator_a = GenericEvaluator(config, mode="prompt", system_prompt=prompt_a)
    await evaluator_a.initialize()
    results_a = await evaluator_a.run_evaluation()
    scores_a = evaluator_a.extract_scores(results_a)

    evaluator_b = GenericEvaluator(config, mode="prompt", system_prompt=prompt_b)
    await evaluator_b.initialize()
    results_b = await evaluator_b.run_evaluation()
    scores_b = evaluator_b.extract_scores(results_b)

    comparison = {}
    all_metrics = set(scores_a.keys()) | set(scores_b.keys())
    for metric in all_metrics:
        val_a = scores_a.get(metric, 0.0)
        val_b = scores_b.get(metric, 0.0)
        comparison[metric] = {
            "prompt_a": val_a,
            "prompt_b": val_b,
            "delta": val_b - val_a,
            "winner": "B" if val_b > val_a else ("A" if val_a > val_b else "tie"),
        }

    return {
        "eval_type": eval_type,
        "comparison": comparison,
        "experiment_a": results_a.experiment_name,
        "experiment_b": results_b.experiment_name,
    }


# ---------------------------------------------------------------------------
# Re-scoring
# ---------------------------------------------------------------------------


def rescore_experiment(
    experiment_name: str,
    metric_names: list[str],
) -> Any:
    """Re-score an existing experiment with additional metrics."""
    metrics: list[base_metric.BaseMetric] = []
    metrics.extend(_resolve_builtin_metrics(metric_names))
    metrics.extend(_resolve_heuristic_metrics(metric_names))
    metrics.extend(_resolve_custom_metrics(metric_names))

    if not metrics:
        raise ValueError(f"No valid metrics found in: {metric_names}")

    log.info(f"Re-scoring experiment '{experiment_name}' with {len(metrics)} metrics")
    return evaluate_experiment(
        experiment_name=experiment_name,
        scoring_metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def evaluate_generic(
    eval_type: str,
    mode: str = "prompt",
    create_dataset: bool = True,
    system_prompt: str | None = None,
    do_compare_baseline: bool = False,
    do_update_baseline: bool = False,
) -> Any:
    """
    Evaluate a generic assistant capability.

    Args:
        eval_type: Eval type ID (e.g., 'conversation_quality', 'safety_boundaries')
        mode: 'prompt' (Mode B, LLM only) or 'full' (Mode A, real graph)
        create_dataset: If True, sync dataset to Opik before evaluation
        system_prompt: Override system prompt (for A/B testing)
        do_compare_baseline: If True, compare results against stored baseline
        do_update_baseline: If True, save current results as new baseline

    Returns:
        Opik EvaluationResult object
    """
    config = get_generic_config(eval_type)
    if not config:
        raise ValueError(
            f"Unknown eval type: {eval_type}. Available: {list_generic_eval_types()}"
        )

    if mode == "full" and not config.supports_mode_a:
        log.warning(
            f"{config.name} doesn't support full graph mode, falling back to prompt mode"
        )
        mode = "prompt"

    evaluator = GenericEvaluator(config, mode=mode, system_prompt=system_prompt)
    await evaluator.initialize()

    if create_dataset:
        await evaluator.create_dataset()

    results = await evaluator.run_evaluation()
    evaluator.print_results(results)

    scores = evaluator.extract_scores(results)

    if do_compare_baseline and scores:
        report = compare_with_baseline(eval_type, scores)
        if report["status"] == "regression":
            print("\n*** REGRESSION DETECTED ***")
            for reg in report["regressions"]:
                print(
                    f"  {reg['metric']}: {reg['baseline']:.3f} -> {reg['current']:.3f} "
                    f"(delta: {reg['delta']:+.3f})"
                )
        elif report["status"] == "ok":
            print("\nNo regressions detected.")
            if report.get("improvements"):
                print("Improvements:")
                for imp in report["improvements"]:
                    print(
                        f"  {imp['metric']}: {imp['baseline']:.3f} -> {imp['current']:.3f} "
                        f"(delta: {imp['delta']:+.3f})"
                    )

    if do_update_baseline and scores:
        update_baseline(eval_type, scores)
        print(f"Baseline updated for {eval_type}")

    return results


async def evaluate_all_generic(
    mode: str = "prompt",
    do_compare_baseline: bool = False,
    do_update_baseline: bool = False,
) -> dict[str, Any]:
    """Run all generic eval types and return combined results."""
    all_results = {}
    for config in GENERIC_EVAL_CONFIGS:
        effective_mode = mode
        if effective_mode == "full" and not config.supports_mode_a:
            effective_mode = "prompt"

        try:
            result = await evaluate_generic(
                eval_type=config.id,
                mode=effective_mode,
                do_compare_baseline=do_compare_baseline,
                do_update_baseline=do_update_baseline,
            )
            all_results[config.id] = result
        except Exception as e:
            log.error(f"Failed to evaluate {config.name}: {e}")
            all_results[config.id] = {"error": str(e)}

    # Print overall health score
    total_weighted_score = 0.0
    total_weight = 0.0
    for config in GENERIC_EVAL_CONFIGS:
        result = all_results.get(config.id)
        if result and not isinstance(result, dict):
            evaluator = GenericEvaluator(config)
            scores = evaluator.extract_scores(result)
            if scores:
                avg_score = sum(scores.values()) / len(scores)
                total_weighted_score += avg_score * config.weight
                total_weight += config.weight

    if total_weight > 0:
        health = total_weighted_score / total_weight
        print("\n" + "=" * 70)
        print(f"OVERALL ASSISTANT HEALTH SCORE: {health:.3f}")
        print("=" * 70)

    return all_results
