"""The autouse wide-event isolation fixture must reset a leaked boundary.

Regression for a cross-test leak: ``current_workflow_execution_id()`` returned a
value in a test that opened no boundary. A bare ``log.reset()`` in one test
seeds a shared, MUTABLE ``_EventState`` in the runner ContextVar; a later test's
``log.set(...)`` mutates that same object in place (an async test's context copy
shares the reference), so a workflow execution id set in one test surfaced in an
unrelated one and failed ``test_no_boundary_means_no_execution_id``.

Driven in-process against the real fixture so it stays deterministic: a two-test
cross-leak reproduction can split across xdist workers (``--dist load``) and stop
reproducing. Left unmarked (not ``@pytest.mark.regression``) on purpose — the fix
lives in the overlaid ``tests/conftest.py``, so the regression-proof lane would
see the fixture on base too and the test would pass there.
"""

import pytest

from shared.py.wide_events import current_workflow_execution_id, get_trace_id, log
from tests import conftest


def test_isolation_fixture_teardown_clears_a_leaked_wide_event_boundary() -> None:
    log.reset()
    log.set(workflow={"execution_id": "exec_leaked"}, trace_id="trace_leaked")
    assert current_workflow_execution_id() == "exec_leaked"
    assert get_trace_id() == "trace_leaked"

    # Run the actual autouse fixture's generator past its yield — its teardown.
    isolate = conftest._isolate_wide_event_state.__wrapped__()
    next(isolate)
    with pytest.raises(StopIteration):
        next(isolate)

    assert current_workflow_execution_id() is None
    assert get_trace_id() == ""
