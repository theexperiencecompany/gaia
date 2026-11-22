# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "fastapi>=0.115",
#     "uvicorn>=0.30",
# ]
# ///
"""Scripted, deterministic LLM stub — an OpenAI/OpenRouter-compatible server.

Point GAIA's OpenRouter client at this process to drive the full stack with a
scripted model instead of a real provider. An agent's own turn is answered by
parsing inline directives from the latest user message (see ``directives.py``):
``[[tool:<name> <json-args>]]`` for scripted tool calls and
``[[say:<text>]]`` for the final reply, ``[[fail:<message>]]`` to break the
final call (after streaming any say text) — deterministic fault injection —
and ``[[wait:<ms>]]`` / ``[[pace:<ms>]]`` to hold a step or slow the reply.
Every other call (memory extraction, follow-ups, titles) gets a neutral,
schema-valid answer instead (see ``background.py``).

Run (no repo venv coupling — uv resolves the inline deps into an ephemeral env):

    uv run tools/llm-stub/server.py                 # default port 9797
    LLM_STUB_PORT=9797 uv run tools/llm-stub/server.py

Wire it into GAIA (development only) with the one canonical switch:

    GAIA_SIM_MODE=1        # `mise dev --sim` sets this; every LLM factory
                           # resolves to this stub (see app/agents/llm/client.py)
    OPENROUTER_BASE_URL=…  # optional: only to point sim mode at a non-default
                           # stub address (defaults to http://localhost:9797/api/v1)

Both ``/chat/completions`` and ``/api/v1/chat/completions`` are served so the
override URL works with or without the ``/api/v1`` suffix. The OpenAI Responses
API (``/responses``, ``/api/v1/responses``) answers ``create_artifact``'s model
call the same way, from the directives in its ``input``: text only.

Unit tests (parser + turn-counting + wire shapes), no repo project needed:

    uv run --no-project --with pytest pytest tools/llm-stub -q
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from background import answer_request
from decisions import DecisionsScriptError, answer_decisions
from directives import (
    ChatRequest,
    DirectiveError,
    Response,
    SayResponse,
    _last_user_index,
    _script_message_index,
    _strip_echoed_payloads,
    message_text,
    parse_directives,
    parse_request,
    parse_responses_request,
    resolve_text_response,
    unanswered_tool_calls,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from responses_wire import build_response, response_sse_lines
import uvicorn
from wire import build_chat_completion, prompt_tokens, sse_lines

DEFAULT_PORT = 9797
SCRIPTED_FAULT_STATUS = 500
UNANSWERED_TOOL_CALL_STATUS = 400

# A per-response think-delay lets a sim test keep an agent genuinely busy across
# its scripted steps — the wide, deterministic window the live-steer / inbox-drain
# path needs to be exercised (a mid-run message must arrive while the executor is
# still reasoning). Seeded from the environment, adjustable at runtime via /control
# so a browser-driven campaign can widen or reset the window without a reboot.
# Default 0 keeps every existing sim run instantaneous and unchanged.
_state: dict[str, int] = {"response_delay_ms": int(os.getenv("LLM_STUB_DELAY_MS", "0"))}

app = FastAPI(title="GAIA scripted LLM stub", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "llm-stub"}


# evlog-map-disable-next-line wide-event -- standalone dev stub with no wide-event pipeline; nothing emits an event to add to
@app.get("/control")
async def get_control() -> dict[str, int]:
    return dict(_state)


# evlog-map-disable-next-line wide-event -- standalone dev stub with no wide-event pipeline; nothing emits an event to add to
@app.post("/control")
async def set_control(request: Request) -> dict[str, int]:
    body = await request.json()
    if "response_delay_ms" in body:
        _state["response_delay_ms"] = max(0, int(body["response_delay_ms"]))
    return dict(_state)


def _log_request(parsed: ChatRequest) -> None:
    """Log one line per request: role sequence, latest-user text, and directives found."""
    roles = ",".join(m.get("role", "?") for m in parsed.messages)
    try:
        script_idx = _script_message_index(parsed.messages)
    except DirectiveError as exc:
        print(f"[llm-stub] roles=[{roles}] MALFORMED directive: {exc}", flush=True)
        return
    idx = script_idx if script_idx is not None else _last_user_index(parsed.messages)
    text = message_text(parsed.messages[idx]) if idx is not None else ""
    directives = parse_directives(_strip_echoed_payloads(text)) if script_idx is not None else []
    print(
        f"[llm-stub] roles=[{roles}] tools={len(parsed.available_tools)} "
        f"directives={len(directives)} script_msg={text[:160]!r}",
        flush=True,
    )


@app.exception_handler(DirectiveError)
async def _directive_error(_request: Request, exc: DirectiveError) -> JSONResponse:
    """Fail loud: a malformed directive is an authoring bug, never a silent default."""
    return JSONResponse(
        status_code=500,
        content={"error": {"message": str(exc), "type": "directive_error"}},
    )


def _unstreamable_fault(response: Response, stream: bool) -> JSONResponse | None:
    """Return the scripted fault as the whole response when no text streams before it breaks."""
    if not isinstance(response, SayResponse) or response.fail is None:
        return None
    if stream and response.text:
        return None
    # Shaped as OpenRouter's error body (its SDK rejects one without a code).
    return JSONResponse(
        status_code=SCRIPTED_FAULT_STATUS,
        content={
            "error": {
                "message": response.fail,
                "type": "scripted_fault",
                "code": SCRIPTED_FAULT_STATUS,
            }
        },
    )


async def _think(response: Response) -> None:
    """Wait out the runtime think-delay, then the response's own scripted wait."""
    delay_ms = _state["response_delay_ms"] + response.delay_ms
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)


# evlog-map-disable-next-line wide-event -- dev-only stub, never deployed; the PEP-723 header pins fastapi+uvicorn so it runs with no repo venv, putting shared.py.wide_events out of reach by design, and _log_request() already prints the per-request debug line
async def _complete(request: Request) -> JSONResponse | StreamingResponse:
    body = await request.json()
    parsed = parse_request(body)
    _log_request(parsed)
    if open_calls := unanswered_tool_calls(parsed.messages):
        # What a real provider answers a thread holding a call with no result.
        return JSONResponse(
            status_code=UNANSWERED_TOOL_CALL_STATUS,
            content={
                "error": {
                    "message": f"No tool output found for function call {open_calls[0]}.",
                    "type": "invalid_request_error",
                    "code": UNANSWERED_TOOL_CALL_STATUS,
                }
            },
        )
    response = answer_request(body)
    await _think(response)
    fault = _unstreamable_fault(response, parsed.stream)
    if fault is not None:
        return fault

    request_tokens = prompt_tokens(parsed.messages)
    if parsed.stream:
        return StreamingResponse(
            sse_lines(parsed.model, response, request_tokens),
            media_type="text/event-stream",
        )
    return JSONResponse(content=build_chat_completion(parsed.model, response, request_tokens))


# evlog-map-disable-next-line wide-event -- dev-only stub, never deployed; see _complete
async def _respond(request: Request) -> JSONResponse | StreamingResponse:
    parsed = parse_responses_request(await request.json())
    _log_request(parsed)
    response = resolve_text_response(parsed.messages, parsed.available_tools)
    await _think(response)
    fault = _unstreamable_fault(response, parsed.stream)
    if fault is not None:
        return fault

    request_tokens = prompt_tokens(parsed.messages)
    if parsed.stream:
        return StreamingResponse(
            response_sse_lines(parsed.model, response, request_tokens),
            media_type="text/event-stream",
        )
    return JSONResponse(content=build_response(parsed.model, response, request_tokens))


# evlog-map-disable-next-line wide-event, error-handling -- dev-only stub, never deployed; see _complete
async def _decisions(request: Request) -> JSONResponse:
    """JEV's Decisions route (decisions.py): a scripted choice, else OpenRouter's no-credit 402."""
    try:
        answer = answer_decisions(await request.json())
    except DecisionsScriptError as exc:
        return JSONResponse(
            status_code=500, content={"error": {"message": str(exc), "type": "directive_error"}}
        )
    print(f"[llm-stub] decisions status={answer.status}", flush=True)
    return JSONResponse(status_code=answer.status, content=answer.body)


app.add_api_route("/chat/completions", _complete, methods=["POST"], response_model=None)
app.add_api_route("/api/v1/chat/completions", _complete, methods=["POST"], response_model=None)
app.add_api_route("/responses", _respond, methods=["POST"], response_model=None)
app.add_api_route("/api/v1/responses", _respond, methods=["POST"], response_model=None)
# OpenRouter serves Decisions beside v1 under /api; GAIA derives it from OPENROUTER_BASE_URL.
app.add_api_route("/api/alpha/decisions", _decisions, methods=["POST"], response_model=None)


def main() -> None:
    port = int(os.getenv("LLM_STUB_PORT", str(DEFAULT_PORT)))
    host = os.getenv("LLM_STUB_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
