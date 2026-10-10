"""Drive each analytics journey through the real routes of a local sim-mode stack.

Every request is the one a client makes: the browser's routes with its PostHog
session header, Dodo's webhook signed with the real secret, and the bot path
through gaia-sim, which runs the shared bot pipeline against the bot API route.
"""

from __future__ import annotations

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
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.user_models import (
    OnboardingNeed,
    OnboardingPhase,
    OnboardingPhaseUpdateRequest,
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

from .posthog_api import REPO_ROOT

DEV_USER_HEADER = "X-Dev-User"
BOT_PLATFORM = "telegram"
WEBHOOK_SECRET_ENV = "DODO_WEBHOOK_PAYMENTS_SECRET"
STREAM_DONE = "data: [DONE]"
HTTP_TIMEOUT_S = 120.0
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


def onboarding(stack: Stack) -> None:
    """Submit onboarding and advance its phase, as the browser does."""
    request = OnboardingRequest(
        profession="engineer", needs=[OnboardingNeed.INBOX], other_need=None, timezone="UTC"
    )
    phase = OnboardingPhaseUpdateRequest(phase=OnboardingPhase.GETTING_STARTED)
    with stack.client() as api:
        _expect(
            api.post("/onboarding", json=request.model_dump(mode="json"), headers=stack.browser()),
            HTTPStatus.OK,
        )
        _expect(
            api.post(
                "/onboarding/phase", json=phase.model_dump(mode="json"), headers=stack.browser()
            ),
            HTTPStatus.OK,
        )


def _chat_request() -> dict[str, object]:
    message = MessageDict(role="user", content=SIM_REPLY)
    return MessageRequestWithHistory(message=SIM_REPLY, messages=[message]).model_dump(
        mode="json", exclude_none=True
    )


def paywall(stack: Stack) -> None:
    """Send a chat turn as a free user, which the paywall refuses."""
    with stack.client() as api:
        _expect(
            api.post("/chat-stream", json=_chat_request(), headers=stack.browser()),
            HTTPStatus.PAYMENT_REQUIRED,
        )


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
    """Run one scripted chat turn through /chat-stream and read the stream to its end."""
    with (
        stack.client() as api,
        api.stream("POST", "/chat-stream", json=_chat_request(), headers=stack.browser()) as reply,
    ):
        if reply.status_code != HTTPStatus.OK:
            reply.read()
            _expect(reply, HTTPStatus.OK)
        if not any(line.strip() == STREAM_DONE for line in reply.iter_lines()):
            raise JourneyError("/chat-stream ended without its [DONE] frame")


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
