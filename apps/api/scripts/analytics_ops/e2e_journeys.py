"""Drive each analytics journey through the real routes of a local sim-mode stack.

Every request is the one a client makes: the browser's routes with its PostHog
session header, Dodo's webhook signed with the real secret, and the bot path
through gaia-sim, which runs the shared bot pipeline against the bot API route.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx
from standardwebhooks.webhooks import Webhook

from app.constants.analytics import POSTHOG_SESSION_HEADER
from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import ReplySettled
from app.models.conversation_send_models import (
    ConversationEvent,
    MessageAccepted,
    SendMessageRequest,
)
from app.models.user_models import (
    OnboardingAnswers,
    OnboardingNeed,
    OnboardingRequest,
)
from app.models.webhook_models import (
    DodoBillingData,
    DodoCustomerData,
    DodoPaymentData,
    DodoSubscriptionData,
    DodoSubscriptionMetadata,
    DodoWebhookEvent,
    DodoWebhookEventType,
)
from app.models.workflow_execution_models import WorkflowExecutionsResponse
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.onboarding import OnboardingStep
from shared.py.conversation_wire import ReplyOutcome

from .posthog_api import REPO_ROOT

DEV_USER_HEADER = "X-Dev-User"
BOT_PLATFORM = "telegram"
WEBHOOK_SECRET_ENV = "DODO_WEBHOOK_PAYMENTS_SECRET"
SSE_DATA_PREFIX = "data: "
HTTP_TIMEOUT_S = 120.0
# The sim reply settles in seconds; past this the step is stuck.
REPLY_TIMEOUT_S = 120.0
BOT_SIM_TIMEOUT_S = 300
# A Pro price in cents; the webhook reports it, nothing is charged.
PRO_PRICE_CENTS = 2000
CURRENCY = "USD"
BILLING_COUNTRY = "US"
SIM_REPLY = "[[say:analytics e2e]]"
# The ARQ worker runs a manual workflow; a sim run finishes in seconds.
WORKFLOW_RUN_TIMEOUT_S = 120.0
WORKFLOW_POLL_INTERVAL_S = 1.0
EXECUTION_RUNNING = "running"
EXECUTION_SUCCEEDED = "success"


class JourneyError(RuntimeError):
    """A journey's request did not get the response a working stack gives."""


@dataclass
class Stack:
    """The running local API, as one fresh dev user with one browser session."""

    api_url: str
    email: str
    session_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: UserId | None = None

    def client(self) -> httpx.Client:
        """Return a client for the API's v1 routes, authenticated as this run's user."""
        return httpx.Client(
            base_url=f"{self.api_url}/api/v1",
            headers={DEV_USER_HEADER: self.email},
            timeout=HTTP_TIMEOUT_S,
        )

    def browser(self) -> dict[str, str]:
        """Return the headers the web app adds to every request: its PostHog session."""
        return {POSTHOG_SESSION_HEADER: self.session_id}

    def owner(self) -> UserId:
        """Return the minted user's id."""
        if self.user_id is None:
            raise JourneyError("the dev user has not been minted")
        return self.user_id


def _expect(response: httpx.Response, status: HTTPStatus) -> httpx.Response:
    if response.status_code != status:
        raise JourneyError(
            f"{response.request.method} {response.request.url.path}: expected {status.value}, "
            f"got {response.status_code} {response.text[:300]}"
        )
    return response


def mint(stack: Stack) -> None:
    """Delete any user left by an earlier run, then mint a fresh one through the real signup path."""
    with stack.client() as api:
        deleted = api.delete(f"/dev/users/{stack.email}")
        if deleted.status_code not in (HTTPStatus.OK, HTTPStatus.NOT_FOUND):
            _expect(deleted, HTTPStatus.OK)
        minted = _expect(api.post("/dev/users", json={"email": stack.email}), HTTPStatus.OK)
    stack.user_id = UserId(str(minted.json()["id"]))


#: Every phase_completed the wizard walk below produces, in the order it reaches them.
ONBOARDING_PHASES = (
    OnboardingStep.QUESTIONS_ANSWERED,
    OnboardingStep.PAYWALL_REACHED,
    OnboardingStep.PAID_REVEAL_SEEN,
    OnboardingStep.FIRST_CHAT_OPENED,
)


def onboarding(stack: Stack) -> None:
    """Walk the wizard as the browser does, reporting the start twice as a reload would."""
    answers = OnboardingAnswers(profession="engineer", needs=[OnboardingNeed.INBOX])
    request = OnboardingRequest(**answers.model_dump(), timezone="UTC")
    with stack.client() as api:

        def report(step: OnboardingStep) -> None:
            _expect(
                api.post("/onboarding/phase", json={"phase": step.value}, headers=stack.browser()),
                HTTPStatus.OK,
            )

        report(OnboardingStep.STARTED)
        report(OnboardingStep.STARTED)
        _expect(
            api.put(
                "/onboarding/answers", json=answers.model_dump(mode="json"), headers=stack.browser()
            ),
            HTTPStatus.OK,
        )
        report(OnboardingStep.PAYWALL_REACHED)
        report(OnboardingStep.PAID_REVEAL_SEEN)
        _expect(
            api.post("/onboarding", json=request.model_dump(mode="json"), headers=stack.browser()),
            HTTPStatus.OK,
        )
        report(OnboardingStep.FIRST_CHAT_OPENED)


def _send(api: httpx.Client, stack: Stack, conversation_id: str) -> httpx.Response:
    """Send the scripted message into the conversation the way the web app does."""
    body = SendMessageRequest(message_id=str(uuid4()), text=SIM_REPLY)
    return api.post(
        f"/conversations/{conversation_id}/messages",
        json=body.model_dump(mode="json", exclude_none=True),
        headers=stack.browser(),
    )


def paywall(stack: Stack) -> None:
    """Send a chat message as a free user, which the paywall refuses."""
    with stack.client() as api:
        _expect(_send(api, stack, str(uuid4())), HTTPStatus.PAYMENT_REQUIRED)


def _send_webhook(
    api: httpx.Client,
    signer: Webhook,
    kind: DodoWebhookEventType,
    data: DodoSubscriptionData | DodoPaymentData,
) -> None:
    now = datetime.now(UTC)
    payload = DodoWebhookEvent(
        business_id="analytics-e2e",
        type=kind.value,
        timestamp=now.isoformat(),
        data=data.model_dump(mode="json"),
    ).model_dump_json()
    webhook_id = f"analytics-e2e-{uuid4()}"
    headers = {
        "webhook-id": webhook_id,
        "webhook-timestamp": str(int(now.timestamp())),
        "webhook-signature": signer.sign(webhook_id, now, payload),
        "content-type": "application/json",
    }
    _expect(api.post("/payments/webhooks/dodo", content=payload, headers=headers), HTTPStatus.OK)


def payment(stack: Stack) -> None:
    """Deliver a signed subscription.active and payment.succeeded for this user to the real route."""
    secret = os.environ.get(WEBHOOK_SECRET_ENV)
    if not secret:
        raise JourneyError(f"{WEBHOOK_SECRET_ENV} is not set; the API rejects unsigned webhooks")
    signer = Webhook(secret)
    user_id = stack.owner().distinct_id
    now = datetime.now(UTC).isoformat()
    customer = DodoCustomerData(customer_id=f"cus_{user_id}", email=stack.email, name="E2E")
    billing = DodoBillingData(country=BILLING_COUNTRY)
    metadata = DodoSubscriptionMetadata(user_id=user_id)
    subscription_id = f"sub_e2e_{uuid4().hex}"
    subscription = DodoSubscriptionData(
        subscription_id=subscription_id,
        product_id="prod_e2e",
        customer=customer,
        billing=billing,
        status="active",
        currency=CURRENCY,
        quantity=1,
        recurring_pre_tax_amount=PRO_PRICE_CENTS,
        payment_frequency_count=1,
        payment_frequency_interval="Month",
        subscription_period_count=1,
        subscription_period_interval="Year",
        created_at=now,
        metadata=metadata,
    )
    paid = DodoPaymentData(
        payment_id=f"pay_e2e_{uuid4().hex}",
        subscription_id=subscription_id,
        business_id="analytics-e2e",
        brand_id="analytics-e2e",
        customer=customer,
        billing=billing,
        currency=CURRENCY,
        total_amount=PRO_PRICE_CENTS,
        settlement_amount=PRO_PRICE_CENTS,
        settlement_currency=CURRENCY,
        tax=0,
        settlement_tax=0,
        status="succeeded",
        payment_method="card",
        created_at=now,
        metadata=metadata,
    )
    with stack.client() as api:
        _send_webhook(api, signer, DodoWebhookEventType.SUBSCRIPTION_ACTIVE, subscription)
        _send_webhook(api, signer, DodoWebhookEventType.PAYMENT_SUCCEEDED, paid)


def chat(stack: Stack) -> None:
    """Send one scripted message, follow the conversation's events until its reply settles, then press Stop."""
    conversation_id = str(uuid4())
    with stack.client() as api:
        sent = _expect(_send(api, stack, conversation_id), HTTPStatus.ACCEPTED)
        accepted = MessageAccepted.model_validate(sent.json())
        with api.stream(
            "GET",
            f"/conversations/{conversation_id}/events",
            params={"after": accepted.seq - 1},
            headers=stack.browser(),
        ) as events:
            if events.status_code != HTTPStatus.OK:
                events.read()
                _expect(events, HTTPStatus.OK)
            await_reply(
                events.iter_lines(),
                accepted.message_id,
                deadline=time.monotonic() + REPLY_TIMEOUT_S,
            )
        _expect(
            api.post(f"/conversations/{conversation_id}/stop", headers=stack.browser()),
            HTTPStatus.OK,
        )


def await_reply(lines: Iterable[str], message_id: str, *, deadline: float) -> None:
    """Read the events stream until the reply answering message_id settles answered."""
    for line in lines:
        if time.monotonic() > deadline:
            raise JourneyError(f"no reply to {message_id} settled in time")
        if not line.startswith(SSE_DATA_PREFIX):
            continue
        frame = ConversationEvent.model_validate_json(line.removeprefix(SSE_DATA_PREFIX)).frame
        if not isinstance(frame, EntryFrame) or not isinstance(frame.entry, ReplySettled):
            continue
        if message_id not in frame.entry.answers:
            continue
        if frame.entry.outcome is not ReplyOutcome.ANSWERED:
            raise JourneyError(f"the reply to {message_id} settled {frame.entry.outcome.value}")
        return
    raise JourneyError(f"the events stream ended before the reply to {message_id} settled")


def workflow(stack: Stack) -> None:
    """Create a manual workflow, then run it."""
    request = CreateWorkflowRequest(
        title="analytics e2e",
        prompt=SIM_REPLY,
        trigger_config=TriggerConfig(type=TriggerType.MANUAL),
        steps=[WorkflowStep(title="reply", description=SIM_REPLY)],
        generate_immediately=False,
    )
    with stack.client() as api:
        created = _expect(
            api.post("/workflows", json=request.model_dump(mode="json"), headers=stack.browser()),
            HTTPStatus.OK,
        )
        workflow_id = created.json()["workflow"]["id"]
        _expect(
            api.post(f"/workflows/{workflow_id}/execute", json={}, headers=stack.browser()),
            HTTPStatus.OK,
        )
        await_execution(api, workflow_id)


def await_execution(
    api: httpx.Client,
    workflow_id: str,
    *,
    timeout_s: float = WORKFLOW_RUN_TIMEOUT_S,
    poll_s: float = WORKFLOW_POLL_INTERVAL_S,
) -> None:
    """Wait for the worker to finish the workflow's run; raise unless it succeeded."""
    deadline = time.monotonic() + timeout_s
    while True:
        executions = WorkflowExecutionsResponse.model_validate(
            _expect(api.get(f"/workflows/{workflow_id}/executions"), HTTPStatus.OK).json()
        ).executions
        finished = [run for run in executions if run.status != EXECUTION_RUNNING]
        if len(finished) > 1:
            raise JourneyError(
                f"workflow {workflow_id} executed once but has {len(finished)} finished runs"
            )
        if finished:
            [run] = finished
            if run.status != EXECUTION_SUCCEEDED:
                raise JourneyError(
                    f"workflow {workflow_id} run ended {run.status}: {run.error_message}"
                )
            return
        if time.monotonic() >= deadline:
            raise JourneyError(
                f"workflow {workflow_id} still {EXECUTION_RUNNING} after {timeout_s:.0f}s"
                if executions
                else f"workflow {workflow_id} never started in {timeout_s:.0f}s: no ARQ worker took it"
            )
        time.sleep(poll_s)


def bot(stack: Stack, transcript: Path) -> None:
    """Send one message through gaia-sim, the real shared bot pipeline, as a linked telegram user."""
    command = [
        "pnpm",
        "nx",
        "run",
        "bot-harness:sim",
        "--",
        "send",
        "--emulate",
        BOT_PLATFORM,
        "--user",
        stack.email,
        "--api",
        stack.api_url,
        "--out",
        str(transcript),
        SIM_REPLY,
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=BOT_SIM_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise JourneyError(f"gaia-sim exited {result.returncode}: {result.stderr[-1000:]}")
