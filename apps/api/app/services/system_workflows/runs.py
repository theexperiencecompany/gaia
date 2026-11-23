"""The system workflows that run their own pipeline instead of the agent turn, by key.

Only the workflow executor imports this: the pipelines sit on the agent stack (see registry
for the declared behaviour everything else reads).
"""

from collections.abc import Awaitable, Callable

from app.models.workflow_models import Workflow
from app.services.system_workflows.definitions.briefing_runs import BRIEFING_RUNS

#: A run in place of the agent turn, returning the run's summary.
SYSTEM_RUNS: dict[str, Callable[[Workflow], Awaitable[str]]] = {**BRIEFING_RUNS}
