"""
Monkey patch for Opik's evaluation_tasks_executor to use sequential execution
instead of ThreadPoolExecutor, avoiding cross-event-loop Future issues.
"""

from typing import Any, Callable, List, TypeVar

T = TypeVar("T")


def _patched_execute(
    evaluation_tasks: List[Callable[[], T]],
    workers: int,
    verbose: int,
    desc: str = "Evaluation",
) -> List[T]:
    """
    Replacement for Opik's execute function that runs sequentially
    instead of using ThreadPoolExecutor.

    This avoids cross-loop Future issues with async clients (MongoDB, gRPC, etc.)
    """
    # Import tqdm here to avoid circular imports
    from opik.environment import get_tqdm_for_current_environment

    tqdm = get_tqdm_for_current_environment()

    # Run all tasks sequentially regardless of workers count
    # This avoids ThreadPoolExecutor which causes cross-loop Future issues
    test_results: List[Any] = [
        evaluation_task()
        for evaluation_task in tqdm(  # type: ignore[operator]
            evaluation_tasks,
            disable=(verbose < 1),
            desc=desc,
            total=len(evaluation_tasks),
        )
    ]
    return test_results


def apply_opik_patch() -> None:
    """
    Apply the monkey patch to Opik's evaluation_tasks_executor.

    Call this BEFORE running any Opik evaluations.
    """
    try:
        import opik.evaluation.engine.evaluation_tasks_executor as executor_module

        executor_module.execute = _patched_execute  # type: ignore[assignment]

        print("✓ Applied Opik monkey patch: ThreadPoolExecutor disabled")
    except (ImportError, AttributeError) as e:
        print(f"⚠ Failed to apply Opik monkey patch: {e}")
