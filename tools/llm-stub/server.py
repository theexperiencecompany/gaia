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

Wire it into GAIA (development only):

    OPENROUTER_BASE_URL=http://localhost:9797   # apps/api/.env
    OPENROUTER_API_KEY=sk-stub-not-used         # any non-empty value; the stub ignores it

Both ``/chat/completions`` and ``/api/v1/chat/completions`` are served so the
override URL works with or without the ``/api/v1`` suffix.

Unit tests (parser + turn-counting + wire shapes), no repo project needed:

    uv run --no-project --with pytest pytest tools/llm-stub -q
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from directives import (  # noqa: E402
    DirectiveError,
    parse_request,
    resolve_response,
)
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
import uvicorn  # noqa: E402
from wire import build_chat_completion, sse_lines  # noqa: E402

DEFAULT_PORT = 9797

app = FastAPI(title="GAIA scripted LLM stub", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "llm-stub"}


async def _complete(request: Request) -> JSONResponse | StreamingResponse:
    body = await request.json()
    parsed = parse_request(body)
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
