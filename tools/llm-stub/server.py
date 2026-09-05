# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi>=0.115",
#     "uvicorn>=0.30",
# ]
# ///
"""Scripted, deterministic LLM stub — an OpenAI/OpenRouter-compatible server.

Point GAIA's OpenRouter client at this process to drive the full stack with a
scripted model instead of a real provider. Every chat-completions request is
answered by parsing inline directives from the latest user message (see
``directives.py``): ``[[tool:<name> <json-args>]]`` for scripted tool calls and
``[[say:<text>]]`` for the final reply.

Run (no repo venv coupling — uv resolves the inline deps into an ephemeral env):

    uv run tools/llm-stub/server.py                 # default port 9797
    LLM_STUB_PORT=9797 uv run tools/llm-stub/server.py

Wire it into GAIA (development only) with the one canonical switch:

    GAIA_SIM_MODE=1        # `mise dev --sim` sets this; every LLM factory
                           # resolves to this stub (see app/agents/llm/client.py)
    OPENROUTER_BASE_URL=…  # optional: only to point sim mode at a non-default
                           # stub address (defaults to http://localhost:9797/api/v1)

Both ``/chat/completions`` and ``/api/v1/chat/completions`` are served so the
override URL works with or without the ``/api/v1`` suffix.

Unit tests (parser + turn-counting + wire shapes), no repo project needed:

    uv run --no-project --with pytest pytest tools/llm-stub -q
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directives import (
    ChatRequest,
    DirectiveError,
    _last_user_index,
    _script_message_index,
    message_text,
    parse_directives,
    parse_request,
    resolve_response,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
from wire import build_chat_completion, sse_lines

DEFAULT_PORT = 9797

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


@app.get("/control")
async def get_control() -> dict[str, int]:
    return dict(_state)


@app.post("/control")
async def set_control(request: Request) -> dict[str, int]:
    body = await request.json()
    if "response_delay_ms" in body:
        _state["response_delay_ms"] = max(0, int(body["response_delay_ms"]))
    return dict(_state)


def _log_request(parsed: ChatRequest) -> None:
    """One line per request so a sim run is debuggable from the stub's stdout:
    role sequence, the resolved latest-user text, and the directives found."""
    roles = ",".join(m.get("role", "?") for m in parsed.messages)
    try:
        script_idx = _script_message_index(parsed.messages)
    except DirectiveError as exc:
        print(f"[llm-stub] roles=[{roles}] MALFORMED directive: {exc}", flush=True)
        return
    idx = script_idx if script_idx is not None else _last_user_index(parsed.messages)
    text = message_text(parsed.messages[idx]) if idx is not None else ""
    directives = parse_directives(text) if script_idx is not None else []
    print(
        f"[llm-stub] roles=[{roles}] tools={len(parsed.available_tools)} "
        f"directives={len(directives)} script_msg={text[:160]!r}",
        flush=True,
    )


# evlog-map-disable-next-line wide-event -- dev-only stub, never deployed; the PEP-723 header pins fastapi+uvicorn so it runs with no repo venv, putting shared.py.wide_events out of reach by design, and _log_request() already prints the per-request debug line
async def _complete(request: Request) -> JSONResponse | StreamingResponse:
    body = await request.json()
    parsed = parse_request(body)
    _log_request(parsed)
    delay_ms = _state["response_delay_ms"]
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)
    try:
        response = resolve_response(parsed.messages, parsed.available_tools)
    except DirectiveError as exc:
        # Fail loud: a malformed directive is an authoring bug, never a silent default.
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "directive_error"}},
        )

    if parsed.stream:
        return StreamingResponse(
            sse_lines(parsed.model, response),
            media_type="text/event-stream",
        )
    return JSONResponse(content=build_chat_completion(parsed.model, response))


app.add_api_route("/chat/completions", _complete, methods=["POST"], response_model=None)
app.add_api_route("/api/v1/chat/completions", _complete, methods=["POST"], response_model=None)


def main() -> None:
    port = int(os.getenv("LLM_STUB_PORT", str(DEFAULT_PORT)))
    host = os.getenv("LLM_STUB_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
