"""Every case must own its user, or the suite measures the wrong thing.

quality, comms and safety each ran every case as ONE shared account, so a case
inherited the previous one's todos, reminders and — worst — the agent's memory
of them, accumulating across every case and every historical run. That makes
results order-dependent, lets a later case answer from memory instead of doing
the work, and makes concurrency impossible because two cases would write over
each other.
"""

from __future__ import annotations

import pytest
from scripts.evals.core.types import Case
from scripts.evals.suites.livechat import SuiteChatTransport
from scripts.evals.suites.quality import ChatStreamTransport


def _case(case_id: str) -> Case:
    return Case(id=case_id, ticket="t", prompt="hello")


@pytest.mark.parametrize(
    "transport",
    [ChatStreamTransport(), SuiteChatTransport("comms"), SuiteChatTransport("safety")],
)
def test_each_case_gets_its_own_identity(transport: ChatStreamTransport) -> None:
    first = transport.case_email(_case("case-one"))
    second = transport.case_email(_case("case-two"))
    assert first != second
    # Same case twice is still distinct: a re-run must not inherit the state of
    # the attempt before it either.
    assert transport.case_email(_case("case-one")) != first


def test_identity_is_namespaced_by_suite() -> None:
    """Two suites running concurrently must not collide in the same account."""
    comms = SuiteChatTransport("comms").case_email(_case("shared-id"))
    safety = SuiteChatTransport("safety").case_email(_case("shared-id"))
    assert comms.startswith("comms-")
    assert safety.startswith("safety-")
    assert comms != safety


def test_identity_carries_the_case_id_for_debugging() -> None:
    assert "billing-refund" in SuiteChatTransport("comms").case_email(_case("billing-refund"))
