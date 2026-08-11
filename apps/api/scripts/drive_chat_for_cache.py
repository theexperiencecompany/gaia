#!/usr/bin/env python3
"""Drive a real multi-turn chat conversation against the running dev API.

Each turn POSTs the full history (exactly what the web client sends). After
the run, grep the API log for `llm_call` events to read the provider-reported
cache hit rates.

Usage: API=http://localhost:8620/api/v1 python3 scripts/drive_chat_for_cache.py
"""

import secrets
import sys

import httpx
from pymongo import MongoClient

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8620/api/v1"
MONGO_URI = sys.argv[2] if len(sys.argv) > 2 else "mongodb://localhost:27017/gaia"
CONV_ID = "cache-e2e-" + secrets.token_hex(6)

TURNS = [
    "Can you summarize my inbox for today and flag anything urgent?",
    "Also draft a reply to Sarah declining Thursday's meeting invite politely.",
    "What's on my calendar this week? Any conflicts with the vendor demo?",
    "Set a reminder to call the dentist tomorrow at 3pm.",
    "What did we decide about the new onboarding flow? Summarize our decisions.",
]


def send(message: str, history: list[dict], turn_id: str) -> tuple[int, str]:
    # The client always sends the full history INCLUDING the current message
    # as the last entry (the backend reads messages[-1] as the new turn).
    body = {
        "message": message,
        "conversation_id": CONV_ID,
        "messages": [*history, {"role": "user", "content": message}],
        "turn_id": turn_id,
        "fileIds": [],
        "fileData": [],
        "use_default_models": True,
    }
    try:
        with httpx.Client(timeout=300) as client:
            resp = client.post(f"{API}/chat-stream", json=body)
            return resp.status_code, resp.text
    except httpx.HTTPError as e:
        return getattr(e.response, "status_code", 0) or 0, str(e)


def history_from_mongo() -> list[dict]:
    """Rebuild the conversation history exactly like the web client does on
    reload: read the persisted conversation messages from Mongo."""
    client = MongoClient(MONGO_URI)
    db = client.get_default_database()
    doc = db["conversations"].find_one({"conversation_id": CONV_ID})
    if not doc:
        return []
    out = []
    for m in doc.get("messages", []):
        role = m.get("role")
        content = m.get("content", "")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content})
    return out


def main() -> None:
    history: list[dict] = []
    for i, text in enumerate(TURNS):
        status, body = send(text, history, f"turn-{i}-{CONV_ID}")
        print(f"turn {i}: http {status}, {len(body)} bytes")
        if status != 200:
            print(body[:500])
            sys.exit(1)
        if '"error"' in body:
            print(body[:800])
            sys.exit(1)
        # Rebuild history from the DB (authoritative) for the next turn.
        history = history_from_mongo()
        last = history[-1]["content"][:100] if history else ""
        print(f"  history now: {len(history)} msgs; last: {last!r}")
    print(f"\nconversation_id: {CONV_ID}")


if __name__ == "__main__":
    main()
