"""The running stack, as the drive sees it: the API under the dev auth bypass.

Every call goes through the real REST surface (`driving-gaia` skill §2 and §4):
the drive never reaches into a service, so what it proves is what a user's
client would get. ``wait_healthy`` exists because the API under test has been
killed from outside mid-drive; a scenario must wait for the port, not fail on it.
"""

from __future__ import annotations

from datetime import UTC, datetime
import time
from typing import Literal

import httpx
from pydantic import BaseModel

DEFAULT_API = "http://127.0.0.1:9480"
DEFAULT_USER = "dev@gaia.local"
HEALTH_WAIT_SECONDS = 120
EXECUTION_WAIT_SECONDS = 300
SETTLE_SECONDS = 6
TODOS_PER_PAGE = 100

ExecutionStatus = Literal["success", "failed"]


class DevUser(BaseModel):
    id: str
    email: str


class WorkflowRef(BaseModel):
    id: str
    activated: bool


class TodoRef(BaseModel):
    id: str
    title: str
    completed: bool


class Execution(BaseModel):
    execution_id: str
    status: str
    started_at: datetime
    error_message: str | None = None
    summary: str | None = None


class GaiaClient:
    """One dev user's view of one API."""

    def __init__(self, api: str = DEFAULT_API, user: str = DEFAULT_USER) -> None:
        self.base = api.rstrip("/")
        self.api = f"{self.base}/api/v1"
        self.headers = {"content-type": "application/json", "X-Dev-User": user}
        self.email = user
        self.http = httpx.Client(timeout=60)

    # --- readiness -----------------------------------------------------------

    def wait_healthy(self, limit: int = HEALTH_WAIT_SECONDS) -> None:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            try:
                if self.http.get(f"{self.base}/health", timeout=3).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(3)
        raise RuntimeError(f"API at {self.base} did not answer /health within {limit}s")

    def mint_user(self) -> DevUser:
        """Idempotent: the dev router's find-or-create through the real signup path."""
        self.wait_healthy()
        response = self.http.post(
            f"{self.api}/dev/users",
            headers=self.headers,
            json={"email": self.email, "name": "Playbook drive"},
        )
        response.raise_for_status()
        return DevUser.model_validate(response.json())

    # --- workflows -----------------------------------------------------------

    def create_workflow(self, title: str, prompt: str, category: str = "todos") -> WorkflowRef:
        """A one-step workflow whose step text is ``prompt``: under the scripted
        model that text IS the script (the step description is rendered verbatim
        into the run's user message)."""
        self.wait_healthy()
        response = self.http.post(
            f"{self.api}/workflows",
            headers=self.headers,
            json={
                "title": title,
                "prompt": prompt,
                "trigger_config": {
                    "type": "schedule",
                    "enabled": True,
                    "cron_expression": "0 9 * * *",
                },
                "steps": [
                    {"id": "s1", "title": title, "category": category, "description": prompt}
                ],
                "generate_immediately": False,
            },
        )
        response.raise_for_status()
        return WorkflowRef.model_validate(response.json()["workflow"])

    def execute(self, workflow_id: str) -> None:
        self.wait_healthy()
        response = self.http.post(
            f"{self.api}/workflows/{workflow_id}/execute", headers=self.headers, json={}
        )
        if response.status_code != 200:
            raise RuntimeError(f"execute -> {response.status_code}: {response.text[:200]}")

    # --- todos ---------------------------------------------------------------

    def create_todo(self, title: str) -> TodoRef:
        response = self.http.post(f"{self.api}/todos", headers=self.headers, json={"title": title})
        response.raise_for_status()
        return TodoRef.model_validate(response.json())

    def pending_todos(self) -> list[TodoRef]:
        """Every pending todo, across every page: the list paginates with
        ``per_page`` (max 100), and a page cap once left leftovers pending that a
        "suspect" scenario then saw as items."""
        found: list[TodoRef] = []
        page = 1
        while True:
            response = self.http.get(
                f"{self.api}/todos",
                headers=self.headers,
                params={"completed": "false", "page": page, "per_page": TODOS_PER_PAGE},
            )
            response.raise_for_status()
            batch = [TodoRef.model_validate(todo) for todo in response.json()["data"]]
            if not batch:
                return found
            found.extend(batch)
            page += 1

    def complete_all_pending(self) -> int:
        todos = self.pending_todos()
        for todo in todos:
            self.http.put(
                f"{self.api}/todos/{todo.id}", headers=self.headers, json={"completed": True}
            ).raise_for_status()
        return len(todos)

    # --- chat ----------------------------------------------------------------

    def chat(self, message: str) -> httpx.Response:
        return self.http.post(
            f"{self.api}/chat-stream",
            headers=self.headers,
            json={"message": message, "messages": []},
            timeout=180,
        )


def now() -> datetime:
    return datetime.now(UTC)
