"""Authored-gate eval: the condition GAIA writes for a job, and what JEV then skips. Bills real tokens.

author: send each creation request through the real authoring prompt on the production chat
  model (the workflow subagent's system prompt and task with the real search_triggers schema,
  or the todo prompt with the real subscribe_todo_to_trigger schema) and write the condition it
  produces to rules.jsonl. search_triggers is answered from the trigger catalog, not an account.
gate: ask JEV, as production does, about every labelled email under each request's condition,
  and write every sampled answer to recorded.jsonl for the CI regrade.
report: wrong skips and wasted runs per split, one sample against the consensus.

Usage: uv run --group backend python -m scripts.evals.authored_gates author|gate|report [request-id ...]
Needs OPENROUTER_API_KEY in the environment.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import json
import os
import sys
from typing import Final

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.agents.prompts.subagent_prompts import WORKFLOW_AGENT_SYSTEM_PROMPT
from app.agents.prompts.todo_prompts import TODO_SYSTEM_PROMPT
from app.constants.llm import DEFAULT_LLM_TEMPERATURE, DEFAULT_MODEL_NAME
from app.constants.trigger_gates import (
    TRIGGER_GATE_JEV_SAMPLES,
    TRIGGER_GATE_QUESTION_KEY,
    TRIGGER_GATE_SKIP_PROBABILITY,
)
from app.models.jev_models import JevDecisionsResponse
from app.models.trigger_gate_models import AuthoredGate
from app.services.hil.jev_client import post_decisions
from app.services.triggers.gmail_signals import gmail_gate_view
from app.services.triggers.trigger_gate import consensus_skip, gate_request
from app.services.workflow.subagent_output import parse_subagent_response
from app.utils.workflow_utils import build_new_workflow_task
from scripts.evals.suites.authored_gate import (
    CLARIFICATION,
    CONNECTED_HINT,
    RECORDED_PATH,
    RULES_PATH,
    TODO_TASK,
    TRIGGER_CATALOG,
    AuthoredRule,
    AuthoringPath,
    CreationRequest,
    RecordedGate,
    authoring_tools,
    gate_of,
    job_of,
    labelled,
    load_mail,
    load_recorded,
    load_requests,
    load_rules,
    prompt_sha,
    write_jsonl,
)
from scripts.evals.suites.trigger_gate import jev_body, request_sha

OPENROUTER_CHAT_URL: Final = "https://openrouter.ai/api/v1/chat/completions"
MAX_TOOL_TURNS: Final = 6
CONCURRENCY: Final = 6
Message = dict[str, object]


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(min=1, max=20),
)
async def _sample(
    state: Mapping[str, object], questions: Mapping[str, Mapping[str, object]]
) -> JevDecisionsResponse:
    """One production Decisions call; a transient 5xx is retried so a pass is never short."""
    return await post_decisions(state, questions)


async def _chat(client: httpx.AsyncClient, messages: list[Message], path: AuthoringPath) -> Message:
    resp = await client.post(
        OPENROUTER_CHAT_URL,
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "model": DEFAULT_MODEL_NAME,
            "temperature": DEFAULT_LLM_TEMPERATURE,
            "messages": messages,
            "tools": authoring_tools(path),
        },
    )
    resp.raise_for_status()
    message: Message = resp.json()["choices"][0]["message"]
    return message


async def _workflow_turns(client: httpx.AsyncClient, messages: list[Message]) -> str:
    """Run the subagent's tool loop to its final text, answering search_triggers from the catalog."""
    for _ in range(MAX_TOOL_TURNS):
        reply = await _chat(client, messages, AuthoringPath.WORKFLOW)
        messages.append(reply)
        calls = reply.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            return str(reply.get("content") or "")
        found = json.dumps({"status": "success", "triggers": list(TRIGGER_CATALOG)})
        messages += [{"role": "tool", "tool_call_id": c["id"], "content": found} for c in calls]
    raise RuntimeError("the workflow subagent never stopped calling tools")


async def _author_workflow(client: httpx.AsyncClient, request: CreationRequest) -> AuthoredRule:
    """Draft the workflow; a clarifying question gets one answer, as a user would give it."""
    task = build_new_workflow_task(request["request"])
    messages: list[Message] = [
        {"role": "system", "content": WORKFLOW_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"{CONNECTED_HINT}\n\n---\n\nRequest: {task}"},
    ]
    parsed = parse_subagent_response(await _workflow_turns(client, messages))
    if parsed.mode == "clarifying":
        messages.append({"role": "user", "content": CLARIFICATION})
        parsed = parse_subagent_response(await _workflow_turns(client, messages))
    if parsed.draft is None:
        raise RuntimeError(f"{request['id']}: no finalized draft: {parsed.raw_response[:400]}")
    return AuthoredRule(
        request_id=request["id"],
        rule=parsed.draft.runs_only_when,
        title=parsed.draft.title,
        description=parsed.draft.description,
        prompt_sha=prompt_sha(AuthoringPath.WORKFLOW),
    )


async def _author_todo(client: httpx.AsyncClient, request: CreationRequest) -> AuthoredRule:
    messages: list[Message] = [
        {"role": "system", "content": TODO_SYSTEM_PROMPT},
        {"role": "user", "content": TODO_TASK.format(request=request["request"])},
    ]
    reply = await _chat(client, messages, AuthoringPath.TODO)
    calls = reply.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        raise RuntimeError(f"{request['id']}: the todo never subscribed: {reply}")
    rule = json.loads(calls[0]["function"]["arguments"]).get("runs_only_when")
    return AuthoredRule(
        request_id=request["id"],
        rule=rule if isinstance(rule, str) and rule else None,
        title=request["request"],
        description=None,
        prompt_sha=prompt_sha(AuthoringPath.TODO),
    )


async def author(only: Sequence[str]) -> None:
    requests = [r for r in load_requests() if not only or r["id"] in only]
    rules = load_rules() if RULES_PATH.exists() else {}
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(client: httpx.AsyncClient, request: CreationRequest) -> AuthoredRule:
        async with limit:
            if request["path"] is AuthoringPath.TODO:
                return await _author_todo(client, request)
            return await _author_workflow(client, request)

    async with httpx.AsyncClient(timeout=180) as client:
        written = await asyncio.gather(*(one(client, r) for r in requests))
    for rule in written:
        rules[rule["request_id"]] = rule
        print(f"{rule['request_id']}: {rule['rule']!r}")
    write_jsonl(RULES_PATH, [rules[k] for k in sorted(rules)])


async def _ask(
    rule: AuthoredRule, authored: AuthoredGate, mail_id: str, message: Mapping[str, object]
) -> RecordedGate:
    view = gmail_gate_view(message)
    if view is None:
        raise ValueError(f"{mail_id} is not a readable Gmail payload")
    state, questions = gate_request(authored, view.as_event(), job_of(rule), quiet=False)
    bodies = await asyncio.gather(
        *(_sample(state, questions) for _ in range(TRIGGER_GATE_JEV_SAMPLES))
    )
    return RecordedGate(
        request_id=rule["request_id"],
        mail_id=mail_id,
        request_sha=request_sha(jev_body(state, questions)),
        responses=[b.model_dump(mode="json", exclude_none=True) for b in bodies],
    )


async def gate(only: Sequence[str]) -> None:
    requests = {r["id"]: r for r in load_requests()}
    mail = load_mail()
    kept = (
        [r for r in load_recorded() if only and r["request_id"] not in only]
        if (RECORDED_PATH.exists())
        else []
    )
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(rule: AuthoredRule, authored: AuthoredGate, mail_id: str) -> RecordedGate:
        async with limit:
            return await _ask(rule, authored, mail_id, mail[mail_id]["message"])

    jobs = [
        one(rule, authored, mail_id)
        for request_id, rule in sorted(load_rules().items())
        if (not only or request_id in only) and (authored := gate_of(rule)) is not None
        for mail_id in labelled(requests[request_id])
    ]
    recorded = await asyncio.gather(*jobs)
    rows = sorted([*kept, *recorded], key=lambda row: (row["request_id"], row["mail_id"]))
    write_jsonl(RECORDED_PATH, rows)
    print(f"recorded {len(recorded)} gate requests")


def report() -> None:
    """Print JEV's skips of wanted and unwanted mail; the CI regrade adds decide_gate's free runs."""
    requests = {r["id"]: r for r in load_requests()}
    rules = load_rules()
    tally: dict[tuple[str, str], list[int]] = {}
    for row in load_recorded():
        request = requests[row["request_id"]]
        authored = gate_of(rules[request["id"]])
        if authored is None:
            raise ValueError(f"{request['id']} has recorded answers but no condition")
        wanted = labelled(request)[row["mail_id"]]
        answers = [
            JevDecisionsResponse.model_validate(r).answers[TRIGGER_GATE_QUESTION_KEY]
            for r in row["responses"]
        ]
        for mode, sampled in (("single", answers[:1]), ("consensus", answers)):
            skipped = consensus_skip(authored, sampled)[1] >= TRIGGER_GATE_SKIP_PROBABILITY
            counts = tally.setdefault((request["split"], mode), [0, 0, 0, 0])
            counts[0 if wanted else 2] += 1
            counts[1 if wanted else 3] += int(skipped if wanted else not skipped)
            if wanted and skipped:
                print(f"WRONG SKIP {mode} {request['id']} {row['mail_id']}")
    for (split, mode), (n_wanted, wrong, n_unwanted, wasted) in sorted(tally.items()):
        print(
            f"{split:8} {mode:9} wrong skips {wrong}/{n_wanted}  wasted runs {wasted}/{n_unwanted}"
        )


def main() -> None:
    command, *only = sys.argv[1:]
    if command == "author":
        asyncio.run(author(only))
    elif command == "gate":
        asyncio.run(gate(only))
    elif command == "report":
        report()
    else:
        raise SystemExit(f"unknown command {command!r}: author, gate or report")


if __name__ == "__main__":
    main()
