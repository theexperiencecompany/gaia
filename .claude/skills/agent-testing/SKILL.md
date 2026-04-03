---
name: agent-testing
description: >
  Testing GAIA agents end-to-end using Chrome DevTools MCP and LangSmith CLI. Use when asked
  to test, verify, or validate any agent behavior — tool usage, subagent spawning, middleware,
  new features, or bug reproduction. Requires sending messages via the chat UI and inspecting
  backend traces. Triggers on: "test if this is working", "verify agent behavior", "test the
  agent", "check if X fires", "does X work", "test with Chrome DevTools", "check LangSmith",
  "test this feature", "validate this change".
---

# Agent Testing: Chrome DevTools + LangSmith

## Environment

| Thing | Value |
|-------|-------|
| Frontend | `http://localhost:3000/c` |
| Backend API | `http://localhost:8000` — hot-reloads on file save |
| LangSmith project | `pr-whispered-caliber-1` |
| LangSmith CLI | `langsmith` |

## General Testing Workflow

### Step 1: Prepare the condition to trigger
If the feature requires a lower threshold or a config change, edit the relevant constant/config file. FastAPI hot-reloads automatically on save — no restart needed.

> **First request after hot-reload WILL FAIL** with `'NoneType' object has no attribute 'astream'`
> This is expected (lazy provider init). Just retry the same message.

### Step 2: Open a new chat
```
mcp__chrome-devtools__take_snapshot   → find "Create new chat" link UID
mcp__chrome-devtools__click uid=<uid> → open fresh chat
```

### Step 3: Send a triggering prompt
Find the textbox UID, click it, then type and submit:
```
mcp__chrome-devtools__click uid=<textbox-uid>
mcp__chrome-devtools__type_text text="your prompt here" submitKey="Enter"
```

Craft the prompt to explicitly force the behavior you're testing. Be direct:
- For tool use: `"Search the web for X"`, `"Look up Y on GitHub"`
- For subagents: `"IMPORTANT: You MUST call spawn_subagent right now with this task: ..."`
- For handoffs: `"Use the Reddit subagent (handoff to reddit subagent) to..."`

### Step 4: Monitor the UI
```
mcp__chrome-devtools__take_screenshot   → take every 5-10s
```

Common status labels to watch for:
- `"Spawning subagent"` — subagent spawned
- `"Delegating to executor"` — comms → executor handoff
- `"Fetched source N/10"` — web/deep_research active
- `"Checking..."` — tool running

If stuck >30s: `mcp__chrome-devtools__list_console_messages` for JS errors.

### Step 5: Verify via LangSmith
See **LangSmith Reference** below for commands and what to look for.

### Step 6: Restore any changed constants
Always restore config changes to production values after testing.

---

## Chrome DevTools Reference

```
mcp__chrome-devtools__take_snapshot          → get element UIDs (always do this before clicking)
mcp__chrome-devtools__take_screenshot        → visual check
mcp__chrome-devtools__click uid=<uid>        → click element
mcp__chrome-devtools__type_text text="..."   → type into focused element (add submitKey="Enter" to send)
mcp__chrome-devtools__press_key key="Escape" → keyboard press
mcp__chrome-devtools__navigate_page type="url" url="..." → navigate
mcp__chrome-devtools__list_console_messages  → JS console errors
mcp__chrome-devtools__evaluate_script        → run JS in page context
```

**Typical flow:**
1. `take_snapshot` → find textbox UID
2. `click` the textbox
3. `type_text text="..." submitKey="Enter"`
4. `take_screenshot` repeatedly until response appears

---

## LangSmith Reference

```bash
# Latest traces (one per conversation turn)
langsmith trace list --project pr-whispered-caliber-1 --limit 5 --format pretty

# All runs within traces (tool calls, LLM calls, chains)
langsmith run list --project pr-whispered-caliber-1 --limit 30 --format pretty

# Filter runs by name
langsmith run list --project pr-whispered-caliber-1 --limit 30 --format pretty \
  | grep -E "<tool-name>"

# Get single run detail (--project is REQUIRED or it errors)
langsmith run get <run-id> --project pr-whispered-caliber-1
```

**How to read a trace:**
- Each user message = one `Call Agent` trace at the top level
- Inside each trace: `LangGraph` chain → `agent` chain → `call_model` chain → `ChatGoogleGenerativeAI` LLM call
- Tool calls appear as `tool` type runs with the tool's name
- Nested subagents appear as child `LangGraph` runs under `spawn_subagent` or `call_executor`

**Reading the signal:**
- A tool ran → its name appears as a `tool` run in the trace
- Middleware fired → look for extra LLM calls or unexpected tool runs in the trace
- Something ran twice → look for duplicate run names (e.g. 2× `ChatGoogleGenerativeAI` = summarization fired)
- Subagent read from VFS → `vfs_read` appears nested under `spawn_subagent`

**CLI limitations:**
- Token fields (`total_tokens`, `prompt_tokens`) return `None` — use LangSmith web UI for token counts
- Run inputs/outputs not shown in CLI `run get` — use web UI for full detail
