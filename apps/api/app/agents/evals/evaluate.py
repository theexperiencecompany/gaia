"""
Generalized Subagent Evaluation Script

Evaluates any subagent using Opik with LLM-as-judge.
Supports both CLI and programmatic usage.

Usage:
    # Create dataset in Opik
    python -m app.agents.evals.evaluate --subagent github --create-dataset

    # Run evaluation
    python -m app.agents.evals.evaluate --subagent github

    # List available subagents
    python -m app.agents.evals.evaluate --list
"""

import argparse
import asyncio
import json
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TypeVar

import nest_asyncio

# Apply Opik patch BEFORE importing opik to disable ThreadPoolExecutor
# This must happen before any opik imports, hence the E402 suppressions below
from app.patches.opik_patch import apply_opik_patch

apply_opik_patch()

import opik  # noqa: E402
from app.agents.core.subagents.subagent_helpers import (  # noqa: E402
    build_subagent_system_prompt,
)
from app.agents.llm.client import init_llm  # noqa: E402
from app.config.loggers import app_logger as logger  # noqa: E402
from app.config.oauth_config import get_integration_by_id  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.core.lazy_loader import providers  # noqa: E402
from app.helpers.agent_helpers import build_agent_config  # noqa: E402
from app.services.model_service import get_model_by_id  # noqa: E402
from langchain_core.messages import (  # noqa: E402
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph.state import CompiledStateGraph  # noqa: E402
from opik.evaluation import evaluate  # noqa: E402
from opik.evaluation.metrics import base_metric, score_result  # noqa: E402

from .config import (  # noqa: E402
    SubagentEvalConfig,
    get_config,
    list_available_subagents,
)
from .initialization import init_eval_providers  # noqa: E402
from .judge_prompts import SUBAGENT_EVALUATION_PROMPT  # noqa: E402

T = TypeVar("T")

# Apply nest_asyncio to allow nested event loops
# This is needed because Opik's evaluate() is sync but we call it from an async context
nest_asyncio.apply()


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """
    Run an async coroutine from a sync context.

    Uses nest_asyncio to allow nested event loops, which handles the case
    where we're called from within an already-running event loop.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


EVALS_DIR = Path(__file__).parent


class LLMJudgeMetric(base_metric.BaseMetric):
    """Custom metric that uses LLM-as-judge to evaluate subagent execution."""

    def __init__(self, judge_llm: Any, judge_prompt: opik.Prompt, system_prompt: str):
        self.judge_llm = judge_llm
        self.judge_prompt = judge_prompt
        self.system_prompt = system_prompt
        self.name = "llm_judge"  # type: ignore[misc]

    def score(
        self,
        input: str,
        output: str,
        expected_output: str = "",
        context: str = "",
        trajectory: str = "",
        tool_calls: str = "",
        errors: str = "",
        **kwargs: Any,
    ) -> score_result.ScoreResult:
        """Score using LLM judge - synchronous wrapper."""
        return run_async(
            self.async_score(
                input=input,
                output=output,
                expected_output=expected_output,
                context=context,
                trajectory=trajectory,
                tool_calls=tool_calls,
                errors=errors,
            )
        )

    async def async_score(
        self,
        input: str,
        output: str,
        expected_output: str = "",
        context: str = "",
        trajectory: str = "",
        tool_calls: str = "",
        errors: str = "",
        **kwargs: Any,
    ) -> score_result.ScoreResult:
        """Score using LLM judge."""
        prompt = self.judge_prompt.format(
            input=input,
            expected_output=expected_output,
            context=context,
            system_prompt=self.system_prompt[:500] if self.system_prompt else "N/A",
            output=output[:1000],
            trajectory=trajectory[:2000],
            tool_calls=tool_calls,
            errors=errors,
        )

        response = await self.judge_llm.ainvoke(prompt)
        content = str(response.content)

        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            scores = json.loads(content[start:end])
            overall = scores.get("overall_score", 0.0)
            summary = scores.get("summary", "")
            return score_result.ScoreResult(
                value=overall,
                name=self.name,
                reason=summary,
                metadata=scores,
            )
        except (json.JSONDecodeError, ValueError):
            return score_result.ScoreResult(
                value=0.0,
                name=self.name,
                reason="Failed to parse LLM judge response",
            )


class SubagentEvaluator:
    """Generalized evaluator for any subagent."""

    def __init__(self, config: SubagentEvalConfig, use_opik_dataset: bool = True):
        self.config = config
        self.use_opik_dataset = use_opik_dataset
        self.opik_client: opik.Opik
        self.subagent_graph: CompiledStateGraph
        self.judge_llm: Any
        self.system_prompt: Optional[str] = None
        self.judge_prompt: opik.Prompt
        self.subagent_prompt: Optional[opik.Prompt] = None

    async def initialize(self) -> None:
        """Initialize Opik, LLM judge, and subagent."""
        if not settings.OPIK_API_KEY or not settings.OPIK_WORKSPACE:
            raise ValueError("OPIK_API_KEY and OPIK_WORKSPACE must be set")

        self.opik_client = opik.Opik()
        logger.info(f"Opik initialized for workspace: {settings.OPIK_WORKSPACE}")

        # Store judge prompt in Opik for versioning
        self.judge_prompt = opik.Prompt(
            name="subagent_evaluation_prompt",
            prompt=SUBAGENT_EVALUATION_PROMPT,
            metadata={"type": "llm_as_judge", "version": "1.0"},
        )
        logger.info(
            f"Judge prompt stored/retrieved from Opik: {self.judge_prompt.commit}"
        )

        # Sync subagent system prompt to Opik if available in config
        if self.config.system_prompt:
            self.subagent_prompt = opik.Prompt(
                name=self.config.prompt_name,
                prompt=self.config.system_prompt,
                metadata={"type": "subagent_system_prompt", "subagent": self.config.id},
            )
            self.system_prompt = self.config.system_prompt
            logger.info(
                f"Subagent prompt '{self.config.prompt_name}' synced to Opik: {self.subagent_prompt.commit}"
            )

        # Initialize only required providers for this subagent
        await init_eval_providers(subagent_ids=[self.config.integration_id])

        subagent = await providers.aget(self.config.agent_name)
        if not subagent:
            raise ValueError(f"Failed to load subagent: {self.config.agent_name}")
        self.subagent_graph = subagent

        # Use system prompt from config (already synced to Opik) or fallback to integration
        if not self.system_prompt:
            integration = get_integration_by_id(self.config.integration_id)
            if integration and integration.subagent_config:
                self.system_prompt = integration.subagent_config.system_prompt

        self.judge_llm = init_llm()
        logger.info(f"Evaluator initialized for {self.config.name}")

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

        items = [
            {
                "input": {"question": item["input"]},
                "expected_output": {"answer": item["expected_output"]},
                "metadata": {
                    "context": item.get("context", ""),
                    "tags": item.get("tags", []),
                    **item.get("metadata", {}),
                },
            }
            for item in data["items"]
        ]

        dataset.insert(items)
        logger.info(
            f"Dataset '{self.config.dataset_name}' synced with {len(items)} items"
        )

    async def _run_subagent(
        self, query: str
    ) -> tuple[str, list[dict[str, Any]], list[str], list[str]]:
        """Run subagent and capture trajectory."""
        runnable_config = build_agent_config(
            conversation_id=f"eval_{self.config.id}_{datetime.now().timestamp()}",
            user={
                "user_id": "691f716ce014f3ad5e8dc9a6",
                "email": "dhruvmaradiya0@gmail.com",
                "name": "Dhruv",
            },
            user_model_config=await get_model_by_id("gemini-2.0-flash"),
            user_time=datetime.now(),
            agent_name=self.config.agent_name,
        )

        system_prompt_with_metadata = await build_subagent_system_prompt(
            integration_id=self.config.integration_id,
            user_id=runnable_config.get("configurable", {}).get("user_id"),
            base_system_prompt=self.system_prompt,
        )

        messages: list[BaseMessage] = [HumanMessage(content=query)]
        if system_prompt_with_metadata:
            messages.insert(0, SystemMessage(content=system_prompt_with_metadata))

        trajectory: list[dict[str, Any]] = []
        tool_calls: list[str] = []
        errors: list[str] = []

        try:
            result = await self.subagent_graph.ainvoke(
                {"messages": messages},
                config=runnable_config,  # type: ignore[arg-type]
            )

            for msg in result.get("messages", []):
                if isinstance(msg, AIMessage):
                    trajectory.append(
                        {
                            "type": "ai",
                            "content": str(msg.content)[:300] if msg.content else "",
                            "tool_calls": [
                                tc.get("name") for tc in (msg.tool_calls or [])
                            ],
                        }
                    )
                    for tc in msg.tool_calls or []:
                        tool_calls.append(tc.get("name", "unknown"))

                elif isinstance(msg, ToolMessage):
                    content = str(msg.content)[:200] if msg.content else ""
                    trajectory.append(
                        {"type": "tool_result", "name": msg.name, "content": content}
                    )
                    if "error" in content.lower():
                        errors.append(content)

            final_messages = [
                m for m in result.get("messages", []) if isinstance(m, AIMessage)
            ]
            output = str(final_messages[-1].content) if final_messages else ""

        except Exception as e:
            logger.error(f"Subagent error: {e}")
            output = f"Error: {e}"
            errors.append(str(e))

        return output, trajectory, tool_calls, errors

    def _create_evaluation_task(self):
        """Create the evaluation task function for Opik."""
        evaluator = self

        def evaluation_task(dataset_item: dict[str, Any]) -> dict[str, Any]:
            """Task that runs the subagent and returns results for scoring."""
            query = dataset_item["input"]["question"]
            expected = dataset_item["expected_output"]["answer"]
            context = dataset_item.get("metadata", {}).get("context", "")

            output, trajectory, tool_calls, errors = run_async(
                evaluator._run_subagent(query)
            )

            return {
                "input": query,
                "output": output,
                "expected_output": expected,
                "context": context,
                "trajectory": json.dumps(trajectory, indent=2),
                "tool_calls": ", ".join(tool_calls) if tool_calls else "None",
                "errors": json.dumps(errors) if errors else "None",
            }

        return evaluation_task

    async def run_evaluation(self) -> Any:
        """Run evaluation using Opik's experiment framework."""
        logger.info(f"Starting evaluation for {self.config.name}...")

        dataset = self.opik_client.get_dataset(name=self.config.dataset_name)
        experiment_name = (
            f"{self.config.id}_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        llm_judge_metric = LLMJudgeMetric(
            judge_llm=self.judge_llm,
            judge_prompt=self.judge_prompt,
            system_prompt=self.system_prompt or "",
        )

        logger.info(f"Running experiment: {experiment_name}")

        eval_results = evaluate(
            experiment_name=experiment_name,
            dataset=dataset,
            task=self._create_evaluation_task(),
            scoring_metrics=[llm_judge_metric],
            experiment_config={
                "subagent": self.config.name,
                "prompt_version": self.subagent_prompt.commit
                if self.subagent_prompt
                else "N/A",
                "judge_prompt_version": self.judge_prompt.commit,
            },
            task_threads=4,
            project_name="GAIA",
        )
        logger.info(f"Evaluation complete: {experiment_name}")
        return eval_results

    def print_results(self, eval_results: Any) -> None:
        """Print evaluation results summary."""
        print("\n" + "=" * 70)
        print(f"EVALUATION COMPLETE: {self.config.name}")
        print("=" * 70)
        print(f"Experiment: {eval_results.experiment_name}")
        print(f"Dataset: {self.config.dataset_name}")
        print("\nView detailed results in Opik dashboard:")
        print(f"  https://www.comet.com/opik/{settings.OPIK_WORKSPACE}")
        print("=" * 70 + "\n")


async def evaluate_subagent(
    subagent_id: str,
    create_dataset: bool = False,
    use_opik_dataset: bool = True,
) -> Any:
    """
    Evaluate a subagent programmatically.

    Args:
        subagent_id: ID of the subagent to evaluate (e.g., 'github', 'gmail')
        create_dataset: If True, sync dataset to Opik before evaluation
        use_opik_dataset: If True, load dataset from Opik; else use local JSON

    Returns:
        Opik EvaluationResult object
    """
    config = get_config(subagent_id)
    if not config:
        raise ValueError(
            f"Unknown subagent: {subagent_id}. Available: {list_available_subagents()}"
        )

    evaluator = SubagentEvaluator(config, use_opik_dataset=use_opik_dataset)
    await evaluator.initialize()

    if create_dataset:
        await evaluator.create_dataset()

    return await evaluator.run_evaluation()


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Evaluate subagents with Opik")
    parser.add_argument("--subagent", "-s", type=str, help="Subagent ID to evaluate")
    parser.add_argument(
        "--create-dataset", "-c", action="store_true", help="Create/sync Opik dataset"
    )
    parser.add_argument(
        "--local",
        "-l",
        action="store_true",
        help="Use local dataset file instead of Opik",
    )
    parser.add_argument("--list", action="store_true", help="List available subagents")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable subagents:")
        for sid in list_available_subagents():
            print(f"  - {sid}")
        return

    if not args.subagent:
        parser.error("--subagent is required (use --list to see available)")

    config = get_config(args.subagent)
    if not config:
        print(f"Unknown subagent: {args.subagent}")
        print(f"Available: {list_available_subagents()}")
        return

    evaluator = SubagentEvaluator(config, use_opik_dataset=not args.local)
    await evaluator.initialize()

    if args.create_dataset:
        await evaluator.create_dataset()
        print(f"✓ Dataset '{config.dataset_name}' synced to Opik")

    results = await evaluator.run_evaluation()
    evaluator.print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
