"""The authored-gate eval's data: creation requests, the conditions GAIA wrote for them, JEV's answers.

data/trigger-gate/authored holds requests.yaml (each request's wanted and unwanted emails),
extra_mail.yaml (pseudonymised emails the corpus lacks), rules.jsonl (the condition the real
authoring prompt wrote for each request) and recorded.jsonl (JEV's sampled answers to every
gate request). scripts/evals/authored_gates.py writes the last two; the CI regrade
(tests/unit/evals/test_authored_gate_sweep.py) replays them through decide_gate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Final, NotRequired, TypedDict

from langchain_core.utils.function_calling import convert_to_openai_tool
import yaml

from app.agents.prompts.subagent_prompts import WORKFLOW_AGENT_SYSTEM_PROMPT
from app.agents.prompts.todo_prompts import TODO_SYSTEM_PROMPT
from app.agents.tools.tracked_todo_tools import subscribe_todo_to_trigger
from app.agents.tools.workflow_shared_tools import search_triggers
from app.constants.trigger_gates import GateAuthor
from app.models.trigger_gate_models import AuthoredGate
from app.services.triggers.trigger_gate import automation_text
from app.utils.workflow_utils import build_new_workflow_task
from scripts.evals.suites.trigger_gate import DATA_DIR, AskedRequest

AUTHORED_DIR: Final = DATA_DIR / "authored"
RULES_PATH: Final = AUTHORED_DIR / "rules.jsonl"
RECORDED_PATH: Final = AUTHORED_DIR / "recorded.jsonl"

CONNECTED_HINT: Final = (
    "# Connected integrations (ground truth for THIS user)\n"
    "Gmail (`gmail`), Slack (`slack`), Google Sheets (`googlesheets`), Google Drive "
    "(`googledrive`), Google Calendar (`googlecalendar`), Linear (`linear`), Telegram "
    "(`telegram`), GitHub (`github`)"
)
# One answer to a clarifying question, the way a user who wants it done would give it.
CLARIFICATION: Final = (
    "It's about emails reaching my Gmail inbox, and Slack or Telegram are connected. Use your "
    "best judgement for anything else and give me the finalized workflow."
)
# What search_triggers returns from the trigger catalog for the triggers these requests need.
TRIGGER_CATALOG: Final = (
    {
        "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE",
        "trigger_name": "New Gmail Message",
        "description": "Trigger when a new email arrives",
        "integration_id": "gmail",
        "integration_name": "Gmail",
        "is_connected": True,
        "config_fields": {},
    },
    {
        "trigger_slug": "GITHUB_STAR_ADDED_EVENT",
        "trigger_name": "Star Added",
        "description": "Trigger when someone stars a repository",
        "integration_id": "github",
        "integration_name": "GitHub",
        "is_connected": True,
        "config_fields": {"repo": {"type": "string", "description": "owner/repo to watch"}},
    },
)
# The executor's turn after it created the tracked todo; the todo id is wiring, never shown.
TODO_TASK: Final = (
    "The user asked: {request}\n\n"
    "You created the tracked todo for it (todo id: todo_eval_0001, title: {request}). It waits "
    "on email, so make it wake itself when the relevant mail arrives in the user's Gmail inbox "
    "(trigger gmail_new_message; its payload fields include sender, subject, message_text)."
)


class AuthoringPath(StrEnum):
    """Which authoring call writes the condition: a workflow draft or a todo's trigger watch."""

    WORKFLOW = "workflow"
    TODO = "todo"


class Split(StrEnum):
    TUNE = "tune"
    HOLDOUT = "holdout"


class CreationRequest(TypedDict):
    """One thing a user asks GAIA to set up, and the emails labelled for its intent."""

    id: str
    path: AuthoringPath
    split: Split
    request: str
    rule: NotRequired[bool]
    wanted: NotRequired[list[str]]
    unwanted: NotRequired[list[str]]


class AuthoredRule(TypedDict):
    """What the authoring call produced: the condition (None for none) and the job JEV reads."""

    request_id: str
    rule: str | None
    title: str
    description: str | None
    prompt_sha: str


class RecordedGate(AskedRequest):
    """One gate request about one email for one request's condition."""

    request_id: str
    mail_id: str


class LabelledMail(TypedDict):
    """A labelled email's Gmail message, and whether the user wrote in its thread."""

    message: Mapping[str, object]
    wrote_in_thread: bool


def authoring_tools(path: AuthoringPath) -> list[dict[str, object]]:
    """Return the real tool schemas the authoring call binds."""
    tool = subscribe_todo_to_trigger if path is AuthoringPath.TODO else search_triggers
    return [convert_to_openai_tool(tool)]


def prompt_sha(path: AuthoringPath) -> str:
    """Hash everything the authoring call reads but the request, so a prompt edit needs a re-author."""
    if path is AuthoringPath.TODO:
        parts: list[object] = [TODO_SYSTEM_PROMPT, TODO_TASK]
    else:
        parts = [WORKFLOW_AGENT_SYSTEM_PROMPT, build_new_workflow_task(""), CONNECTED_HINT]
        parts += [CLARIFICATION, list(TRIGGER_CATALOG)]
    canonical = json.dumps([*parts, authoring_tools(path)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_requests() -> list[CreationRequest]:
    requests: list[CreationRequest] = yaml.safe_load((AUTHORED_DIR / "requests.yaml").read_text())
    for request in requests:
        request["path"] = AuthoringPath(request["path"])
        request["split"] = Split(request["split"])
    return requests


def load_mail() -> dict[str, LabelledMail]:
    """Return every labelled email by id: the corpus's and the extra ones, which start threads."""
    corpus = yaml.safe_load((DATA_DIR / "corpus.yaml").read_text())
    extra = yaml.safe_load((AUTHORED_DIR / "extra_mail.yaml").read_text())
    mail = {
        case["id"]: LabelledMail(
            message=case["setup"]["message"],
            wrote_in_thread=bool(case["setup"].get("user_wrote_in_thread", True)),
        )
        for case in corpus
    }
    mail.update(
        {case["id"]: LabelledMail(message=case["message"], wrote_in_thread=True) for case in extra}
    )
    return mail


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def load_rules() -> dict[str, AuthoredRule]:
    rules: dict[str, AuthoredRule] = {}
    for row in read_jsonl(RULES_PATH):
        rule, description = row["rule"], row["description"]
        request_id = str(row["request_id"])
        rules[request_id] = AuthoredRule(
            request_id=request_id,
            rule=rule if isinstance(rule, str) else None,
            title=str(row["title"]),
            description=description if isinstance(description, str) else None,
            prompt_sha=str(row["prompt_sha"]),
        )
    return rules


def load_recorded() -> list[RecordedGate]:
    rows: list[RecordedGate] = []
    for row in read_jsonl(RECORDED_PATH):
        responses = row["responses"]
        if not isinstance(responses, list):
            raise ValueError(f"recorded row without responses: {row['request_id']}")
        rows.append(
            RecordedGate(
                request_id=str(row["request_id"]),
                mail_id=str(row["mail_id"]),
                request_sha=str(row["request_sha"]),
                responses=responses,
            )
        )
    return rows


def gate_of(rule: AuthoredRule) -> AuthoredGate | None:
    if rule["rule"] is None:
        return None
    return AuthoredGate(condition=rule["rule"], author=GateAuthor.GAIA)


def job_of(rule: AuthoredRule) -> str:
    """Return the automation text decide_gate sends for this request's job."""
    return automation_text(rule["title"], rule["description"])


def labelled(request: CreationRequest) -> dict[str, bool]:
    """Return each labelled email of a request and whether the user wanted the job to run on it."""
    return {
        **dict.fromkeys(request.get("unwanted", []), False),
        **dict.fromkeys(request.get("wanted", []), True),
    }
