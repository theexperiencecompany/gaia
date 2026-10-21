"""Every model a browser run calls, served by one local server and scripted per run.

Comms and the executor (streamed, with tools) follow tools/llm-stub's inline
directives and re-voice a result handed to them word for word; a structured
one-shot (one tool, unstreamed) gets the emptiest value its schema accepts. The
Browser-Use agent ({memory, action}) and Jev's text model ({text}) are told apart
by their json_schema; Jev's decisions and Gemini's embeddings (which seed the
tools store) have their own routes. The agent and Jev are scripted per run, found
by a marker the task carries; targets are named by visible text and resolved to
the index the request itself offers, so a script acts only on what the real page
shows. A script that runs out, a target the page lacks, or a required string never
seen is recorded in errors and answered with a failure, never a made-up success.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from tests.helpers import load_llm_stub_module, pick_free_port
from tests.integration.real.browser._stack.local_server import LocalServer, serve_locally

# wire imports directives by its bare name, so directives is registered first.
_directives = load_llm_stub_module("directives")
_wire = load_llm_stub_module("wire")

#: The Browser-Use structured-output name both of its callers use.
_AGENT_OUTPUT = "agent_output"
_EXTRACT_SYSTEM = "You are an expert at extracting data from the markdown of a webpage."
_COMPACTION_SYSTEM = "You are summarizing an agent run for prompt compaction."
_KEY_TERMS_PROMPT = "Extract 3-5 key search terms from this goal"
#: Payloads a tier hands the next one that a model re-voices: a run's result, never a context slot.
_RESULT_PAYLOAD = re.compile(
    r"<(?P<tag>executor_result|executor_error|browser_[a-z_]+)(?:\s[^>]*)?>\n?(?P<body>.*?)\n?</(?P=tag)>",
    re.DOTALL,
)
_INTERACTIVE_LINE = re.compile(
    r"^(?P<indent>\t*)\*?(?:\|[^\[\n]*)?\[(?P<index>\d+)\]<(?P<tag>[\w-]+)(?P<attrs>[^>]*)/?>"
)
_ATTRIBUTE = re.compile(r"(?P<key>[\w-]+)=(?P<value>'[^']*'|\S+)")
_TEXT_ATTRIBUTES = ("value", "aria-label", "placeholder", "title", "alt", "name")
_BROWSER_STATE = re.compile(r"<browser_state>(.*?)</browser_state>", re.DOTALL)
_WEBPAGE_CONTENT = re.compile(r"<webpage_content>(.*?)</webpage_content>", re.DOTALL)
_CURRENT_TAB = re.compile(r"^Current tab: (\w+)", re.MULTILINE)
_TAB = re.compile(r"^Tab (\w+): (\S+)", re.MULTILINE)
#: Written in a done text, replaced by the address of the page the agent is on.
PAGE_URL = "{page_url}"
#: The tools and triggers stores are built for vectors this long.
_EMBEDDING_DIMS = 768


@dataclass(frozen=True)
class Text:
    """An element named by its visible text, resolved to the index the request offers."""

    text: str


@dataclass(frozen=True)
class AgentStep:
    """One agent step: its actions, taken once what it waits on is there.

    An action is {name: params}; any param that is a Text is resolved to an element
    index, and PAGE_URL in a string param becomes the current tab's address. Until
    wait_for is on the page, heard is anywhere in what the agent is shown (a
    follow-up the user sent mid-run), and gate (if any) is set, the agent waits a
    second instead, at most patience times. A done action is sent only when every
    require string was seen in the page state or the run's history.
    """

    actions: list[dict[str, Any]]
    wait_for: str | None = None
    heard: str | None = None
    gate: asyncio.Event | None = None
    patience: int = 20
    require: tuple[str, ...] = ()


@dataclass(frozen=True)
class JevMove:
    """One Jev decision: an operation, its target's visible text, and what to type or pick.

    value is a literal the goal spells out or a <secret>name</secret> placeholder;
    generated is the text the text model writes when the value is GENERATE.
    """

    operation: str
    target: str | None = None
    value: str | None = None
    generated: str | None = None
    option: str | None = None


@dataclass
class RunScript:
    """The agent's and Jev's scripts for one run, and how far each has got."""

    marker: str
    agent: list[AgentStep]
    jev: list[JevMove]
    agent_cursor: int = 0
    jev_cursor: int = 0
    waited: int = 0
    last_move: JevMove | None = None
    #: Agent answers by the request that asked: a retried or hedged duplicate gets the same answer.
    answered: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCall:
    """One request the server answered: which caller it was, and for which run."""

    kind: str
    marker: str | None


def _one_hot(ids: list[str], chosen: str) -> dict[str, float]:
    return {option: 1.0 if option == chosen else 0.0 for option in ids}


def _attr_text(attrs: str) -> list[str]:
    found: list[str] = []
    for match in _ATTRIBUTE.finditer(attrs):
        if match.group("key") in _TEXT_ATTRIBUTES:
            found.append(match.group("value").strip("'"))
    return found


def element_index(browser_state: str, text: str) -> int | None:
    """Return the index of the interactive element whose visible text or label is text.

    An exact match wins over a containing one; the first of each in page order.
    """
    lines = browser_state.splitlines()
    exact: int | None = None
    contains: int | None = None
    wanted = text.casefold().strip()
    for i, line in enumerate(lines):
        match = _INTERACTIVE_LINE.match(line)
        if match is None:
            continue
        depth = len(match.group("indent"))
        names = _attr_text(match.group("attrs"))
        for child in lines[i + 1 :]:
            child_depth = len(child) - len(child.lstrip("\t"))
            if child_depth <= depth or _INTERACTIVE_LINE.match(child):
                break
            names.append(child.strip())
        index = int(match.group("index"))
        folded = [name.casefold().strip() for name in names]
        if exact is None and wanted in folded:
            exact = index
        if contains is None and any(wanted in name for name in folded):
            contains = index
    return exact if exact is not None else contains


class FakeModels:
    """The model server one browser stack talks to, scripted run by run from the test."""

    def __init__(self) -> None:
        self.port = pick_free_port()
        self.calls: list[ModelCall] = []
        self.errors: list[str] = []
        #: Every tool comms or the executor was answered with, in order.
        self.tool_calls: list[str] = []
        self._runs: dict[str, RunScript] = {}
        #: While cleared, comms and executor model calls wait: a test holds what comes after a run.
        self.agent_tier_open = asyncio.Event()
        self.agent_tier_open.set()
        self._server: LocalServer | None = None

    @property
    def base_url(self) -> str:
        """The OpenAI-wire base both the dev lane and OPENROUTER_BASE_URL point at."""
        return f"http://127.0.0.1:{self.port}/api/v1"

    @property
    def gemini_base_url(self) -> str:
        """Where GOOGLE_GEMINI_BASE_URL points the Gemini SDK."""
        return f"http://127.0.0.1:{self.port}/"

    def script(
        self, marker: str, *, agent: list[AgentStep], jev: list[JevMove] | None = None
    ) -> None:
        """Script the run whose task carries marker."""
        self._runs[marker] = RunScript(marker=marker, agent=agent, jev=jev or [])

    def calls_for(self, marker: str, kind: str) -> int:
        return sum(1 for call in self.calls if call.marker == marker and call.kind == kind)

    async def start(self) -> None:
        app = Starlette(
            routes=[
                Route("/api/v1/chat/completions", self._chat, methods=["POST"]),
                Route("/api/alpha/decisions", self._decisions, methods=["POST"]),
                Route("/v1beta/models/{call}", self._gemini_embeddings, methods=["POST"]),
            ]
        )
        self._server = await serve_locally("fake model server", app, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop()

    # --- routing ------------------------------------------------------------

    def _marker_in(self, text: str) -> RunScript | None:
        for marker, run in self._runs.items():
            if marker in text:
                return run
        return None

    def _fail(self, message: str) -> None:
        self.errors.append(message)

    async def _chat(self, request: Request) -> Response:
        body = await request.json()
        try:
            return await self._answer_chat(body)
        except (
            Exception
        ) as exc:  # a fault in the fake itself is recorded and answered loud, never hidden
            self._fail(f"the fake failed on {json.dumps(body)[:600]}: {exc!r}")
            return JSONResponse(status_code=500, content={"error": {"message": repr(exc)}})

    async def _answer_chat(self, body: dict[str, Any]) -> Response:
        response_format = body.get("response_format") or {}
        schema = (response_format.get("json_schema") or {}).get("schema") or {}
        properties = set((schema.get("properties") or {}).keys())
        messages: list[dict[str, Any]] = body.get("messages") or []
        system = _directives.message_text(messages[0]) if messages else ""
        tools = body.get("tools") or []
        if not body.get("stream") and len(tools) == 1:
            return self._structured_one_shot(body, tools[0])
        if body.get("stream") or tools:
            await self.agent_tier_open.wait()
            return self._agent_tier(body)
        if (response_format.get("json_schema") or {}).get("name") == _AGENT_OUTPUT:
            if properties == {"memory", "action"}:
                return self._json_content(self._agent_step(messages, schema), messages)
            if properties == {"text"}:
                return self._json_content(self._text_value(messages), messages)
        if system.startswith(_EXTRACT_SYSTEM):
            return self._plain(self._extract(messages), messages)
        if system.startswith(_COMPACTION_SYSTEM):
            self.calls.append(ModelCall("compaction", None))
            return self._plain("The run so far, compacted.", messages)
        if system.startswith(_KEY_TERMS_PROMPT):
            self.calls.append(ModelCall("key_terms", None))
            return self._plain("page text", messages)
        self._fail(f"a model request nothing here answers: {json.dumps(body)[:400]}")
        return JSONResponse(status_code=500, content={"error": {"message": "unscripted request"}})

    # --- structured one-shots ------------------------------------------------

    def _structured_one_shot(self, body: dict[str, Any], tool: dict[str, Any]) -> Response:
        function = tool.get("function") or {}
        parameters = function.get("parameters") or {}
        self.calls.append(ModelCall(f"structured:{function.get('name')}", None))
        response = _directives.ToolCallResponse(
            name=str(function.get("name")),
            args=_emptiest(parameters, parameters.get("$defs") or {}),
        )
        return JSONResponse(
            content=_wire.build_chat_completion(
                body.get("model") or "fake",
                response,
                _wire.prompt_tokens(body.get("messages") or []),
            )
        )

    # --- comms and executor ------------------------------------------------

    def _agent_tier(self, body: dict[str, Any]) -> Response:
        parsed = _directives.parse_request(body)
        response = self._result_echo(parsed.messages)
        if response is None:
            response = _directives.resolve_response(parsed.messages, parsed.available_tools)
        self.calls.append(ModelCall("agent_tier", None))
        if isinstance(response, _directives.ToolCallResponse):
            self.tool_calls.append(response.name)
        if parsed.stream:
            return StreamingResponse(
                _wire.sse_lines(parsed.model, response, _wire.prompt_tokens(parsed.messages)),
                media_type="text/event-stream",
            )
        return JSONResponse(
            content=_wire.build_chat_completion(
                parsed.model, response, _wire.prompt_tokens(parsed.messages)
            )
        )

    def _result_echo(self, messages: list[dict[str, Any]]) -> Any:
        """Re-voice a result handed to this tier after its script, word for word."""
        scripted = _directives._script_message_index(messages)
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.get("role") != "user":
                continue
            if scripted is not None and index <= scripted:
                return None
            found = _RESULT_PAYLOAD.search(_directives.message_text(message))
            if found is not None:
                return _directives.SayResponse(found.group("body").strip())
        return None

    # --- the Browser-Use agent ---------------------------------------------

    def _agent_step(self, messages: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
        state = "\n".join(_directives.message_text(m) for m in messages if m.get("role") == "user")
        run = self._marker_in(state)
        self.calls.append(ModelCall("agent", run.marker if run else None))
        if run is None:
            self._fail(f"an agent step for no scripted run: {state[:300]}")
            return _done("No run was scripted for this task.", success=False)
        asked = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
        if asked in run.answered:
            return run.answered[asked]
        answer = self._next_agent_answer(run, state, schema)
        run.answered[asked] = answer
        return answer

    def _next_agent_answer(
        self, run: RunScript, state: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        if run.agent_cursor >= len(run.agent):
            self._fail(f"{run.marker}: the agent was asked for a step past its script")
            return _done("The scripted agent ran out of steps.", success=False)
        planned = run.agent[run.agent_cursor]
        page = _browser_state(state)
        waiting = (
            (planned.wait_for is not None and planned.wait_for not in page)
            or (planned.heard is not None and planned.heard not in state)
            or (planned.gate is not None and not planned.gate.is_set())
        )
        if waiting:
            run.waited += 1
            if run.waited > planned.patience:
                self._fail(f"{run.marker}: step {run.agent_cursor + 1} waited past its patience")
                return _done("What the step waited on never came.", success=False)
            return {"memory": "Waiting.", "action": [{"wait": {"seconds": 1}}]}
        missing = [needed for needed in planned.require if needed not in state]
        if missing:
            self._fail(f"{run.marker}: the agent was to report {missing} but never saw them")
            return _done(f"Not seen on the page: {missing}", success=False)
        actions = [self._resolve(run, action, page, schema) for action in planned.actions]
        run.agent_cursor += 1
        run.waited = 0
        return {"memory": f"Step {run.agent_cursor} of the script.", "action": actions}

    def _resolve(
        self, run: RunScript, action: dict[str, Any], page: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        ((name, params),) = action.items()
        offered = _action_params(schema, name)
        if offered is None:
            self._fail(f"{run.marker}: the agent offers no {name!r} action")
            return action
        resolved: dict[str, Any] = {}
        for key, value in params.items():
            if key not in offered:
                # A param this build's schema does not declare (done_when before Jev's contract had it).
                continue
            if isinstance(value, Text):
                index = element_index(page, value.text)
                if index is None:
                    self._fail(f"{run.marker}: no element reads {value.text!r} on the page")
                    index = 0
                resolved[key] = index
            elif isinstance(value, str):
                resolved[key] = value.replace(PAGE_URL, _current_url(page))
            else:
                resolved[key] = value
        return {name: resolved}

    def _text_value(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        user = _directives.message_text(messages[-1]) if messages else ""
        run = self._marker_in(user)
        self.calls.append(ModelCall("text_value", run.marker if run else None))
        move = run.last_move if run else None
        if move is None or move.generated is None:
            self._fail(f"a value to write with nothing scripted: {user[:300]}")
            return {"text": None}
        return {"text": move.generated}

    def _extract(self, messages: list[dict[str, Any]]) -> str:
        user = "\n".join(_directives.message_text(m) for m in messages if m.get("role") == "user")
        self.calls.append(ModelCall("extract", None))
        content = _WEBPAGE_CONTENT.search(user)
        return content.group(1).strip() if content else user

    # --- Jev ---------------------------------------------------------------

    async def _decisions(self, request: Request) -> Response:
        body = await request.json()
        questions: dict[str, dict[str, Any]] = body.get("questions") or {}
        goals = " ".join(
            json.dumps(question.get("instructions")) for question in questions.values()
        )
        run = self._marker_in(goals)
        self.calls.append(ModelCall("jev", run.marker if run else None))
        if run is None:
            self._fail(f"a Jev decision for no scripted run: {goals[:300]}")
            return JSONResponse(status_code=500, content={"error": {"message": "unscripted"}})
        answers: dict[str, Any] = {}
        if "operation" in questions:
            answers = self._operation(run, questions)
        elif "value" in questions:
            answers = {"value": self._value(run, questions["value"])}
        elif "option" in questions:
            answers = {"option": self._option(run, questions["option"])}
        else:
            self._fail(f"{run.marker}: a Jev question nothing here answers: {list(questions)}")
        return JSONResponse(
            content={"answers": answers, "usage": {"inputTokens": 0, "outputTokens": 0}}
        )

    def _operation(self, run: RunScript, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        operations = list(questions["operation"]["criteria"])
        if run.jev_cursor >= len(run.jev):
            self._fail(f"{run.marker}: Jev was asked past its script")
            move = JevMove("BLOCKED")
        else:
            move = run.jev[run.jev_cursor]
            run.jev_cursor += 1
        run.last_move = move
        if move.operation not in operations:
            self._fail(f"{run.marker}: Jev was not offered {move.operation} (offered {operations})")
            move = JevMove("BLOCKED")
        answers: dict[str, Any] = {"operation": _choice(operations, move.operation)}
        head = f"{move.operation.lower()}_target"
        if head in questions and move.target is not None:
            criteria = questions[head]["criteria"]
            chosen = _target_id(criteria, move.target)
            if chosen is None:
                self._fail(f"{run.marker}: Jev was offered no {move.target!r} to {move.operation}")
                chosen = next(iter(criteria))
            answers[head] = _choice(list(criteria), chosen)
        return answers

    def _value(self, run: RunScript, question: dict[str, Any]) -> dict[str, Any]:
        criteria: dict[str, Any] = question["criteria"]
        move = run.last_move
        wanted = "GENERATE" if move is not None and move.generated is not None else None
        if move is not None and move.value is not None:
            wanted = next((key for key, value in criteria.items() if value == move.value), None)
        if wanted is None:
            self._fail(f"{run.marker}: no offered value matches {move}: {criteria}")
            wanted = "NONE"
        return _choice(list(criteria), wanted)

    def _option(self, run: RunScript, question: dict[str, Any]) -> dict[str, Any]:
        criteria: dict[str, Any] = question["criteria"]
        move = run.last_move
        wanted = next(
            (key for key, label in criteria.items() if move is not None and label == move.option),
            None,
        )
        if wanted is None:
            self._fail(f"{run.marker}: no offered option is {move}: {criteria}")
            wanted = next(iter(criteria))
        return _choice(list(criteria), wanted)

    # --- Gemini embeddings ------------------------------------------------------

    async def _gemini_embeddings(self, request: Request) -> Response:
        call = request.path_params["call"]
        body = await request.json()
        if call.endswith(":batchEmbedContents"):
            texts = [
                _content_text(item.get("content") or {}) for item in body.get("requests") or []
            ]
            return JSONResponse(content={"embeddings": [{"values": _vector(t)} for t in texts]})
        if call.endswith(":embedContent"):
            return JSONResponse(
                content={"embedding": {"values": _vector(_content_text(body.get("content") or {}))}}
            )
        self._fail(f"a Gemini call nothing here answers: {call}")
        return JSONResponse(status_code=500, content={"error": {"message": "unscripted"}})

    # --- wire ---------------------------------------------------------------

    @staticmethod
    def _json_content(content: dict[str, Any], messages: list[dict[str, Any]]) -> JSONResponse:
        return FakeModels._plain(json.dumps(content), messages)

    @staticmethod
    def _plain(text: str, messages: list[dict[str, Any]]) -> JSONResponse:
        return JSONResponse(
            content=_wire.build_chat_completion(
                "fake", _directives.SayResponse(text), _wire.prompt_tokens(messages)
            )
        )


def _emptiest(schema: dict[str, Any], defs: dict[str, Any]) -> Any:
    """Return the emptiest value schema accepts: null where allowed, else empty, zero, false or its first choice."""
    if "$ref" in schema:
        return _emptiest(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        nullable = next((v for v in variants if v.get("type") == "null"), None)
        return None if nullable is not None else _emptiest(variants[0], defs)
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties") or {}
        return {key: _emptiest(properties[key], defs) for key in schema.get("required") or []}
    empty: dict[str, Any] = {"array": [], "string": "", "integer": 0, "number": 0, "boolean": False}
    return empty.get(str(kind))


def _content_text(content: dict[str, Any]) -> str:
    return " ".join(str(part.get("text", "")) for part in content.get("parts") or [])


def _vector(text: str) -> list[float]:
    """Return a stable vector for text: the same text always lands in the same place."""
    seed = hashlib.sha256(text.encode()).digest()
    return [((seed[i % len(seed)] + i) % 256) / 255 - 0.5 for i in range(_EMBEDDING_DIMS)]


def _done(text: str, *, success: bool) -> dict[str, Any]:
    return {"memory": "Ending the run.", "action": [{"done": {"text": text, "success": success}}]}


def _choice(ids: list[str], chosen: str) -> dict[str, Any]:
    return {"type": "choice", "choice": chosen, "probabilities": _one_hot(ids, chosen)}


def _target_id(criteria: dict[str, Any], text: str) -> str | None:
    """Return the offered target whose label is text, exactly or else containing it."""
    wanted = text.casefold()
    labels = {
        key: re.sub(r"^\[\w+\]\s*", "", str(value.get("element", ""))).casefold()
        for key, value in criteria.items()
    }
    exact = next((key for key, label in labels.items() if label == wanted), None)
    return exact or next((key for key, label in labels.items() if wanted in label), None)


def _current_url(page: str) -> str:
    """Return the address of the tab the agent is on, as its browser state lists it."""
    tabs = dict(_TAB.findall(page))
    current = _CURRENT_TAB.search(page)
    if current is not None and current.group(1) in tabs:
        return tabs[current.group(1)]
    return next(iter(tabs.values()), "")


def _browser_state(state: str) -> str:
    found = _BROWSER_STATE.findall(state)
    return found[-1] if found else ""


def _action_params(schema: dict[str, Any], name: str) -> set[str] | None:
    """Return the params the request's schema declares for an action, or None when it offers no such action."""
    items = ((schema.get("properties") or {}).get("action") or {}).get("items") or {}
    for variant in items.get("anyOf") or [items]:
        declared = (variant.get("properties") or {}).get(name)
        if declared is not None:
            return set((declared.get("properties") or {}).keys())
    return None
