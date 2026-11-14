"""The scripted busy founder: signs up, pays, connects Calendar/GitHub/Todoist, keeps GAIA todos.

Acts only through GAIA's real HTTP surfaces (dev mint, onboarding, the signed Dodo webhook,
todos). App connections are written as the Composio callback writes them (Stage 2 drives the
real connect flow). Every action is recorded with its simulated instant for the oracle.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
import json
from pathlib import Path
import secrets

from bson import ObjectId
import httpx
from pymongo.database import Database
import redis
from standardwebhooks.webhooks import Webhook

from briefsim.world.model import App
from briefsim.world.scenario import Clockwork

EMAIL = "delivered+brief-sim-founder@resend.dev"
PERSONA = "founder"
TIMEZONE = "Asia/Kolkata"
_APP_NAMES = {App.CALENDAR: "Google Calendar", App.GITHUB: "GitHub", App.TODOIST: "Todoist"}
_TODO_TITLES = [
    "Prep the board deck numbers",
    "Reply to the Sequoia associate",
    "Review Kavya's offer letter",
    "Write the changelog for the voice release",
    "Fix the pricing page typo",
    "Call the bank about the FX limit",
    "Draft the hiring post for a designer",
    "Send the NDA to the Dodo team",
    "Book the dentist",
    "Renew the car insurance",
]
JsonObject = dict[str, object]


@dataclass(frozen=True)
class Action:
    at: datetime
    name: str
    run: Callable[[], JsonObject]


@dataclass
class Founder:
    api: str
    world: str
    mongo: Database
    redis_client: redis.Redis
    env: dict[str, str]
    clock: Clockwork
    log_path: Path
    user_id: str = ""
    todos: list[str] = field(default_factory=list)

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.api, headers={"X-Dev-User": EMAIL}, timeout=120)

    def record(self, name: str, detail: JsonObject) -> None:
        row = {"at": datetime.now(UTC).isoformat(), "persona": PERSONA, "action": name, **detail}
        with self.log_path.open("a") as sink:
            sink.write(json.dumps(row, default=str) + "\n")

    def sign_up(self) -> JsonObject:
        with self._client() as api:
            minted = api.post("/dev/users", json={"email": EMAIL, "name": "Sim Founder"})
            minted.raise_for_status()
            self.user_id = str(minted.json()["id"])
            onboarded = api.post(
                "/onboarding",
                json={
                    "profession": "Founder",
                    "needs": ["inbox", "calendar", "mornings"],
                    "timezone": TIMEZONE,
                },
            )
            onboarded.raise_for_status()
        return {"user_id": self.user_id}

    def subscribe_pro(self) -> JsonObject:
        """Deliver Dodo's signed subscription.active to the real webhook route."""
        now = datetime.now(UTC)
        subscription_id = f"sub_sim_{secrets.token_hex(6)}"
        payload = json.dumps(
            {
                "business_id": "brief-sim",
                "type": "subscription.active",
                "timestamp": now.isoformat(),
                "data": {
                    "subscription_id": subscription_id,
                    "product_id": "prod_brief_sim",
                    "customer": {
                        "customer_id": f"cus_{self.user_id}",
                        "email": EMAIL,
                        "name": "Sim Founder",
                    },
                    "billing": {"country": "IN"},
                    "status": "active",
                    "currency": "USD",
                    "quantity": 1,
                    "recurring_pre_tax_amount": 2000,
                    "payment_frequency_count": 1,
                    "payment_frequency_interval": "Month",
                    "subscription_period_count": 1,
                    "subscription_period_interval": "Year",
                    "created_at": now.isoformat(),
                    "metadata": {"user_id": self.user_id},
                },
            }
        )
        webhook_id = f"brief-sim-{secrets.token_hex(8)}"
        headers = {
            "webhook-id": webhook_id,
            "webhook-timestamp": str(int(now.timestamp())),
            "webhook-signature": Webhook(self.env["DODO_WEBHOOK_PAYMENTS_SECRET"]).sign(
                webhook_id, now, payload
            ),
            "content-type": "application/json",
        }
        httpx.post(
            f"{self.api}/payments/webhooks/dodo", content=payload, headers=headers, timeout=60
        ).raise_for_status()
        return {"subscription_id": subscription_id}

    def connect(self, apps: list[App]) -> JsonObject:
        """Mark each app connected the way the Composio callback does, and tell the world whose account it is."""
        now = datetime.now(UTC)
        accounts = {app.value: f"ca_{app.value}_{self.user_id}" for app in apps}
        for app in apps:
            account = {
                "id": secrets.token_hex(8),
                "connected_account_id": accounts[app.value],
                "identity": {},
                "label": _APP_NAMES[app],
                "nickname": None,
                "status": "connected",
                "connected_at": now,
            }
            self.mongo.user_integrations.update_one(
                {"user_id": self.user_id, "integration_id": app.value},
                {
                    "$set": {
                        "status": "connected",
                        "connected_at": now,
                        "accounts": [account],
                        "primary_account_id": account["id"],
                        "expired_at": None,
                        "expired_reason": None,
                    },
                    "$setOnInsert": {"_id": ObjectId(), "created_at": now},
                },
                upsert=True,
            )
        for pattern in (
            f"*tools:user:{self.user_id}:*",
            f"*tool_namespaces:{self.user_id}",
            f"*OAUTH_STATUS:{self.user_id}",
        ):
            for key in self.redis_client.scan_iter(match=pattern, count=500):
                self.redis_client.delete(key)
        httpx.post(
            f"{self.world}/_sim/personas/{PERSONA}", json=accounts, timeout=10
        ).raise_for_status()
        return {"apps": [a.value for a in apps]}

    def add_todo(self, day: int) -> JsonObject:
        title = _TODO_TITLES[day % len(_TODO_TITLES)]
        # Added in the evening for the next day: 02:00 local is still the day before in UTC
        # (the next brief sees it overdue), 21:00 local is the same UTC date (due tonight).
        due = self.clock.at(day + 1, 2, 0) if day % 2 == 0 else self.clock.at(day + 1, 21, 0)
        with self._client() as api:
            created = api.post(
                "/todos",
                json={
                    "title": title,
                    "due_date": due.isoformat(),
                    "due_date_timezone": TIMEZONE,
                    "priority": "high",
                },
            )
            created.raise_for_status()
        todo_id = str(created.json()["id"])
        self.todos.append(todo_id)
        return {"todo_id": todo_id, "title": title, "due": due.isoformat()}

    def complete_oldest(self) -> JsonObject:
        if not self.todos:
            return {"skipped": "no open todo"}
        todo_id = self.todos.pop(0)
        with self._client() as api:
            api.put(f"/todos/{todo_id}", json={"completed": True}).raise_for_status()
        return {"todo_id": todo_id}

    def schedule(self, days: int) -> list[Action]:
        """Return every action over the run, in simulated time order."""
        at = self.clock.at
        actions = [
            Action(at(0, 5, 45), "sign_up", self.sign_up),
            Action(at(0, 5, 50), "subscribe_pro", self.subscribe_pro),
            Action(
                at(0, 5, 55),
                "connect",
                partial(self.connect, [App.CALENDAR, App.GITHUB, App.TODOIST]),
            ),
            # The GitHub grant died on day 8; the founder reconnects it at lunch the next day.
            Action(at(9, 12, 0), "reconnect_github", partial(self.connect, [App.GITHUB])),
        ]
        for day in range(days):
            if self.clock.weekday(day) < 5:
                actions.append(Action(at(day, 19, 30), "add_todo", partial(self.add_todo, day)))
            if day % 3 == 2:
                # Slower than one a day, so open todos pile up across briefs.
                actions.append(Action(at(day, 18, 0), "complete_todo", self.complete_oldest))
        return sorted(actions, key=lambda a: a.at)

    def act(self, action: Action) -> None:
        self.record(action.name, action.run())


def day_index(clock: Clockwork, at: datetime) -> int:
    """Return the persona-local day number of an instant (day 0 is the origin's local date)."""
    return (at.astimezone(clock.tz).date() - clock.first_day).days
