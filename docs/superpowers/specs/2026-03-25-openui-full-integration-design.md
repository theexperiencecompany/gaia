# OpenUI Full Integration Design

**Date:** 2026-03-25
**Branch:** `openui`
**Status:** Design Phase — v2 (post-review fixes applied)

---

## 1. Executive Summary

GAIA currently sends structured tool results to the frontend as `tool_data` entries (e.g., `email_compose_data`, `todo_data`), each requiring a hand-written frontend renderer tied to a specific backend type. OpenUI replaces this with a streaming-first generative UI language: the LLM emits component declarations directly, and the frontend renders them from a shared component library.

The migration follows a two-phase boundary:

- **Phase 1 — Read-only tools**: Any tool that only *displays* data (todos list, email list, weather, calendar, search) is migrated to OpenUI components immediately. These have no side effects and are lowest risk.
- **Phase 2 — Write-action tools**: Tools with buttons that mutate state (send email, delete event, connect integration) are migrated to OpenUI components backed by **direct frontend action handlers** — the backend sends action type + data via OpenUI, the frontend has registered handlers per action type, no LLM round-trip needed for execution.

Three tools are already on OpenUI in the current branch: `weather_data` (WeatherCard), `search_results` (SearchResultsTabs), and `calendar_fetch_data` (CalendarListCard). This plan describes how to complete the migration for all remaining tools.

---

## 2. Current State

### 2.1 What Exists in the `openui` Branch

| Component | Status | Notes |
|---|---|---|
| `WeatherCard` (for `weather_data`) | ✅ OpenUI | Streaming, full schema |
| `CalendarListCard` (for `calendar_fetch_data`) | ✅ OpenUI | Streaming, full schema — NOTE: for fetching/listing events only, NOT creation |
| `SearchResultsTabs` (for `search_results`) | ✅ OpenUI | Streaming, full schema |
| Fence parser (`:::openui`) | ✅ Complete | Handles streaming, breaks, incomplete blocks |
| `OpenUIRenderer` | ✅ Complete | Error boundary, streaming state |
| `TextBubble` integration | ✅ Complete | Segments into OpenUI vs markdown |
| `gaiaLibrary` | ✅ Complete | Manual library object (zod v3 compat) |
| Feature flag `ENABLE_OPENUI` | ✅ Complete | Defaults `false` |
| Backend prompt injection | ✅ Complete | Added to comms agent only |
| Structured logging / telemetry | ✅ Complete | Wide-event logging across chat flow |

### 2.2 What is Broken / Incomplete

| Issue | Severity | Detail |
|---|---|---|
| `continue_conversation` not wired | **HIGH** | `OpenUIRenderer.handleAction` only `console.warn`s. OpenUI `Button` clicks do nothing. |
| No action handler registry | **HIGH** | No `submit:`, `action:` prefix handlers. Interactive buttons are dead. |
| Only comms agent gets OpenUI | **MEDIUM** | `OPENUI_INSTRUCTIONS` injected only into comms agent. Provider subagents get nothing. |
| Only 3 components in library | **MEDIUM** | 30 more tool types still use old `tool_data`. |
| `openuiChatLibrary` not used | **LOW** | Pre-built `FollowUpBlock`, `ListBlock`, `SectionBlock` chat components ignored. |
| No AG-UI protocol | **LOW** | Custom SSE used; OpenUI adapters unused (intentional for now). |

### 2.3 How Email Works Today (Not Broken)

Email is entirely separate from OpenUI and **works correctly**:

```
User asks to send email
→ LLM calls GMAIL_CREATE_EMAIL_DRAFT tool
→ Backend publishes: data: {"tool_data": [{tool_name: "email_compose_data", data: {...}}]}
→ Frontend: TextBubble → TOOL_RENDERERS["email_compose_data"] → EmailComposeSection → EmailComposeCard
→ User fills/edits fields → clicks "Send" → EmailComposeCard calls Gmail API directly
```

The OpenUI migration of email is a deliberate future decision, not a current regression.

### 2.4 Full Tool Registry — Current State

**33 tool types** in `TOOL_REGISTRY`. Categorized by migration phase:

```
ALREADY ON OPENUI:
  weather_data            → WeatherCard       [✅ OpenUI]
  search_results          → SearchResultsTabs [✅ OpenUI]
  calendar_fetch_data     → CalendarListCard  [✅ OpenUI — event listing only]

READ-ONLY DISPLAY (Phase 1 targets):
  email_fetch_data        → EmailListCard     [TODO]
  email_thread_data       → EmailThreadCard   [TODO]
  contacts_data           → ContactListCard   [TODO]
  people_search_data      → PeopleSearchCard  [TODO]
  todo_data               → TodoListCard      [TODO]
  calendar_list_fetch_data→ extend CalendarListCard [TODO]
  deep_research_results   → DeepResearchCard  [TODO]
  notification_data       → NotificationCard  [TODO]
  integration_list_data   → IntegrationListCard [TODO]
  document_data           → DocumentCard      [TODO]
  google_docs_data        → GoogleDocsCard    [TODO]
  goal_data               → GoalCard          [TODO]

  reddit_data             → RedditResultsCard [TODO — see note below]
  twitter_search_data     → TwitterCard       [TODO — see note below]
  twitter_user_data       → TwitterUserCard   [TODO — see note below]

WRITE-ACTION (Phase 2 targets):
  calendar_options        → CalendarCreateCard  [TODO — event CREATION form, not display]
  email_compose_data      → EmailComposeCard    [TODO, action: send_email]
  email_sent_data         → EmailSentCard       [TODO, confirmation only]
  calendar_delete_options → CalendarDeleteCard  [TODO, action: delete_calendar_event]
  calendar_edit_options   → CalendarEditCard    [TODO, action: edit_calendar_event]
  integration_connection_required → IntegrationConnectCard [TODO, action: connect_integration]
  support_ticket_data     → SupportCard         [TODO]
  workflow_draft          → WorkflowDraftCard   [TODO]
  workflow_created        → WorkflowCreatedCard [TODO]

KEEP AS-IS (specialized, no clear migration path):
  tool_calls_data         → animated tool progress overlay
  todo_progress           → streaming progress bars
  rate_limit_data         → error/upgrade UI
  mcp_app                 → sandboxed HTML iframes — keep indefinitely
  artifact_data           → complex artifact viewer — Phase 3 candidate
  code_data               → syntax-highlighted code + copy/run — Phase 3 candidate
```

**Note on `calendar_options`:** This is NOT the same as `calendar_fetch_data`. `calendar_options` renders `CalendarEventSection` — a **write form** for creating calendar events. It is currently NOT on OpenUI. It belongs in Phase 2 with `CalendarCreateCard` + `submit:create_calendar_event` action handler.

**Note on `reddit_data` and `twitter_search_data`/`twitter_user_data`:** These are discriminated unions with both read and write subtypes:

```typescript
// reddit_data subtypes:
{ type: "posts"; data: RedditPostsData }         // read → RedditResultsCard
{ type: "post_created"; data: RedditPostCreatedData }   // write confirmation
{ type: "comment_created"; data: RedditCommentCreatedData } // write confirmation

// twitter_search_data subtypes:
{ type: "search"; data: TwitterSearchData }       // read → TwitterSearchCard
{ type: "timeline"; data: TwitterTimelineData }   // read
{ type: "users"; data: TwitterUserData[] }        // read
{ type: "post_created"; data: TwitterPostCreatedData }  // write confirmation
```

Phase 1 migration covers only the read subtypes. The `post_created` / `comment_created` subtypes are **write confirmations** — they must remain on the legacy `TOOL_RENDERERS` path during Phase 1 and be handled explicitly as Phase 2 write-action components (e.g., `RedditPostCreatedCard`, `TwitterPostCreatedCard`).

---

## 3. Target State — Full OpenUI Vision

### 3.1 Rendering Pipeline (Target)

```
LLM streams response
  ↓
Backend: response text contains :::openui blocks
  ↓
SSE: data: {"response": ":::openui\nroot = TodoListCard(...)\n:::"}
  ↓
Frontend: parseOpenUISegments() → [markdown|openui] segments
  ↓
OpenUIRenderer: gaiaLibrary.components[name] → React component
  ↓
User clicks action button → ActionEvent { type: "send_email", formState: {...} }
  ↓
openUIActionDispatcher(event) → lookup DIRECT_HANDLERS[type] → call API directly
```

### 3.2 Backend Prompt Evolution

Currently: backend sends `tool_data: [{tool_name: "todo_data", data: [...]}]` in SSE alongside the text response.

Target: backend agent generates ONE unified response where structured data is embedded as OpenUI blocks inline with the text. **The agent's conversational tone and personality must not change.** OpenUI is additive — the agent still talks naturally, the UI appears as part of the response.

```
Sure! Here are your todos for today:

:::openui
root = TodoListCard(
  items=[
    TodoItem("Buy groceries", false, "low", "2026-03-26"),
    TodoItem("Call dentist", false, "high", "2026-03-25"),
    TodoItem("Submit PR", true, "medium", "2026-03-24")
  ]
)
:::

You've got a dentist call due today — want me to set a reminder?
```

The text before and after the block keeps the agent's natural voice. The `:::openui` block is just structured data rendered as a component, not a replacement for the response.

### 3.3 Action Architecture (Hybrid — Option C)

Three tiers of actions:

| Tier | Trigger | Handler | Example |
|---|---|---|---|
| **continue_conversation** | OpenUI button with discovery intent | Append text to chat input, let LLM handle | "Search more", "Show next week" |
| **direct_action** | OpenUI button with known write operation | Frontend handler calls API directly, no LLM | "Send email", "Delete event", "Connect integration" |
| **open_url** | OpenUI button with link | Open URL in browser | "View in Google Calendar" |

---

## 4. Action Handler Architecture

### 4.1 Action ID Convention

```
# Built-in (handled by dispatcher directly):
continue_conversation   → append humanFriendlyMessage to chat input
open_url                → window.open(params.url)

# Direct handlers (call API without LLM round-trip):
send_email              → emailApi.sendDraftEmail(formState + params)
delete_calendar_event   → calendarApi.deleteEvent(params.event_id)
edit_calendar_event     → calendarApi.editEvent(params.event_id, formState)
create_calendar_event   → calendarApi.createEvent(formState)
connect_integration     → triggers OAuth/connection flow
create_todo             → todoApi.createTodo(formState)
delete_todo             → todoApi.deleteTodo(params.todo_id)
complete_todo           → todoApi.completeTodo(params.todo_id)
```

### 4.2 OpenUIActionDispatcher

New file: `apps/web/src/features/chat/actions/openUIActionDispatcher.ts`

Uses `useAppendToInput` from the existing `composerStore` — no new abstractions needed. The dispatcher is a plain async function that receives `appendToInput` as a parameter (consistent with how `FollowUpActions.tsx` already works).

```typescript
import type { ActionEvent } from "@openuidev/react-lang";

type DirectActionHandler = (event: ActionEvent) => Promise<void>;

const DIRECT_HANDLERS: Record<string, DirectActionHandler> = {
  send_email: handleSendEmail,
  delete_calendar_event: handleDeleteCalendarEvent,
  edit_calendar_event: handleEditCalendarEvent,
  create_calendar_event: handleCreateCalendarEvent,
  connect_integration: handleConnectIntegration,
  create_todo: handleCreateTodo,
  delete_todo: handleDeleteTodo,
  complete_todo: handleCompleteTodo,
};

export async function dispatchOpenUIAction(
  event: ActionEvent,
  appendToInput: (text: string) => void,
): Promise<void> {
  // Strip both "action:" and "submit:" prefixes to normalize action type
  const raw = event.type;
  const type = raw.startsWith("action:")
    ? raw.slice("action:".length)
    : raw.startsWith("submit:")
      ? raw.slice("submit:".length)
      : raw;

  if (type === "continue_conversation") {
    appendToInput(event.humanFriendlyMessage);
    return;
  }

  if (type === "open_url" && event.params?.url) {
    window.open(event.params.url as string, "_blank", "noopener");
    return;
  }

  if (type === "cancel") {
    // noop — button exists for UX, no side effect needed
    return;
  }

  const handler = DIRECT_HANDLERS[type];
  if (handler) {
    await handler(event);
    return;
  }

  // Fallback for unknown action types: treat as continue_conversation
  console.warn(`[OpenUI] Unknown action type: "${type}". Falling back to chat.`);
  appendToInput(event.humanFriendlyMessage);
}
```

### 4.3 OpenUIRenderer Wiring

`OpenUIRenderer.tsx` hooks into `useAppendToInput` from `composerStore` (same pattern as `FollowUpActions.tsx`):

```typescript
import { useAppendToInput } from "@/stores/composerStore";
import { dispatchOpenUIAction } from "@/features/chat/actions/openUIActionDispatcher";

// Inside OpenUIRenderer:
const appendToInput = useAppendToInput();

const handleAction = useCallback(
  (event: ActionEvent) => {
    dispatchOpenUIAction(event, appendToInput);
  },
  [appendToInput],
);
```

### 4.4 OpenUI Component with Write Action

Example: EmailComposeCard in OpenUI (Phase 2):

```
:::openui
root = Form("email_compose", [
  FormControl("To", Input("to", "user@example.com", "email", [{type: "required"}, {type: "email"}])),
  FormControl("Subject", Input("subject", "Re: Meeting tomorrow")),
  FormControl("Message", Input("body", "Hi Sarah...", "textarea")),
], [
  Button("Send Email", "submit:send_email", "primary"),
  Button("Discard", "action:cancel")
], {thread_id: "thread_abc123", draft_id: "draft_xyz"})
:::
```

When user clicks Send:
- `ActionEvent.type = "submit:send_email"` → dispatcher strips `"submit:"` → type = `"send_email"`
- `ActionEvent.formState = { to: "...", subject: "...", body: "..." }`
- `ActionEvent.params = { thread_id: "thread_abc123", draft_id: "draft_xyz" }`
- `handleSendEmail(event)` calls Gmail API directly with both formState + params

---

## 5. Migration Phases

### Phase 1 — Read-Only Tools (Lower Risk, Higher Value)

**Goal:** Migrate all display-only tool types to OpenUI components.
**Prerequisite:** Wire `continue_conversation` action first (Section 4.3). All read-only components with "See more" / "Load more" buttons depend on this.

**Components to build (priority order):**

1. **`TodoListCard`** — highest user visibility
   - Props: `items[]: { id, title, completed, priority, due_date?, list_name? }[]`
   - Action: `continue_conversation` ("Add todo", "Mark all complete")
   - Replaces: `todo_data`

2. **`EmailListCard`** — email thread list (read)
   - Props: `emails[]: { id, subject, from, snippet, date, read, has_attachments }[]`
   - Action: `continue_conversation` ("Reply to [subject]", "Show more emails")
   - Replaces: `email_fetch_data`

3. **`EmailThreadCard`** — single email thread with messages
   - Props: `{ thread_id, subject, messages[]: { from, to, body, date }[] }`
   - Action: `continue_conversation` ("Reply", "Forward")
   - Replaces: `email_thread_data`

4. **`DeepResearchCard`** — structured research with sources
   - Props: `{ title, summary, sections[]: { heading, content }[], sources[]: { url, title }[] }`
   - Replaces: `deep_research_results`

5. **`RedditResultsCard`** — reddit posts list (read subtypes only)
   - Props: covers `{ type: "posts" }` subtype
   - `post_created` / `comment_created` subtypes stay in legacy TOOL_RENDERERS (Phase 2)
   - Replaces: `reddit_data` read path only

6. **`ContactListCard`** / **`PeopleSearchCard`**
   - Replaces: `contacts_data`, `people_search_data`

7. **`TwitterCard`** — search + timeline + users read subtypes
   - `post_created` subtype stays in legacy TOOL_RENDERERS (Phase 2)
   - Replaces: `twitter_search_data`, `twitter_user_data` read paths

8. **`NotificationCard`** — notification list
   - Replaces: `notification_data`

9. **`IntegrationListCard`** — available integrations
   - Replaces: `integration_list_data`

10. **`DocumentCard`** / **`GoogleDocsCard`** — document previews
    - Replaces: `document_data`, `google_docs_data`

11. **Calendar read cards** — extend existing `CalendarListCard` for `calendar_list_fetch_data`

12. **`GoalCard`** — goal tracking view
    - Replaces: `goal_data`

**Per-tool migration checklist:**
1. Build React component + Zod schema
2. Register in `gaiaLibrary` (using manual pattern — see Section 6.2)
3. Add component to `OPENUI_COMPONENT_LIBRARY_PROMPT` in `openui_prompts.py`
4. Update backend tool's streaming output to emit `:::openui` block instead of `tool_data`
5. Keep old `TOOL_RENDERERS` entry with `// @deprecated: migrated to OpenUI` comment
6. Remove `TOOL_RENDERERS` entry + `TOOL_REGISTRY` entry once confirmed stable

### Phase 2 — Write-Action Tools

**Goal:** Migrate tools with interactive forms/buttons to OpenUI + direct action handlers.
**Prerequisite:** `openUIActionDispatcher` from Section 4.2 must be implemented.

**Components + handlers:**

1. **`CalendarCreateCard`** (NEW — currently `calendar_options`)
   - Replaces: `calendar_options` (currently renders `CalendarEventSection` — a write form)
   - Action: `submit:create_calendar_event` → calendarApi.createEvent(formState)

2. **`EmailComposeCard`** (as OpenUI Form)
   - Replaces: `email_compose_data` + `EmailComposeSection` + `EmailComposeCard`
   - Action: `submit:send_email` → emailApi.sendDraftEmail(formState + params)
   - Pre-populate all form fields from backend draft data in component props

3. **`CalendarEditCard`**
   - Replaces: `calendar_edit_options`
   - Action: `submit:edit_calendar_event`

4. **`CalendarDeleteCard`**
   - Replaces: `calendar_delete_options`
   - Action: `action:delete_calendar_event` (with inline confirmation text)

5. **`IntegrationConnectCard`**
   - Replaces: `integration_connection_required`
   - Action: `action:connect_integration` → triggers OAuth flow

6. **`WorkflowDraftCard`** / **`WorkflowCreatedCard`**
   - Replaces: `workflow_draft`, `workflow_created`
   - Actions: `action:activate_workflow`, `action:edit_workflow`

7. **`EmailSentCard`** (confirmation, display-only)
   - Replaces: `email_sent_data`

8. **`RedditPostCreatedCard`** / **`TwitterPostCreatedCard`**
   - Handle the `post_created` / `comment_created` subtypes from reddit + twitter unions
   - These are write confirmations (no interactive buttons needed, just show success)

### Phase 3 — Complex Tools (Future)

- **`ArtifactCard`** — rich viewer with preview, download. Phase 3 candidate.
- **`CodeCard`** — syntax-highlighted code + `action:run_code`. Phase 3 candidate.
- **`mcp_app`** — sandboxed HTML iframes. Keep indefinitely; OpenUI can't replicate sandbox isolation.
- **`tool_calls_data`** — streaming progress overlay. Keep as-is.
- **`todo_progress`** — streaming progress bars. Keep as-is.
- **`rate_limit_data`** — error/upgrade UI. Keep as-is.

---

## 6. gaiaLibrary Expansion

### 6.1 Library Organization

```typescript
// apps/web/src/config/openui/gaiaLibrary.ts

// Current (3 components)
// WeatherCard, CalendarListCard (for calendar_fetch_data), SearchResultsTabs

// Target after Phase 1 (display components):
// + TodoListCard, EmailListCard, EmailThreadCard
// + DeepResearchCard, RedditResultsCard, ContactListCard, PeopleSearchCard
// + TwitterCard, TwitterUserCard, NotificationCard
// + IntegrationListCard, DocumentCard, GoogleDocsCard, GoalCard

// Target after Phase 2 (write-action components):
// + CalendarCreateCard, EmailComposeCard, CalendarEditCard, CalendarDeleteCard
// + IntegrationConnectCard, WorkflowDraftCard, EmailSentCard
// + RedditPostCreatedCard, TwitterPostCreatedCard
```

### 6.2 Zod v3 Compatibility

The current workaround (manually constructing Library object) must be preserved for **all** new components. Do NOT use `defineComponent()` or `createLibrary()` from `@openuidev/react-lang` — these call `z.globalRegistry` which is zod v4 only. The project is locked to zod@3.25.

Pattern for each new component:

```typescript
// gaiaLibrary.ts — addition pattern for each new component:
components["TodoListCard"] = {
  component: (props: z.infer<typeof todoListSchema>) =>
    React.createElement(TodoListCard, props),
  props: todoListSchema,
  description: "Display a list of todo items with completion status and priority",
};
```

### 6.3 Backend Prompt Expansion

`openui_prompts.py` must be updated for each new component. Each entry in `OPENUI_COMPONENT_LIBRARY_PROMPT` needs:
- Component name + signature with all parameters
- Type for each parameter
- Example showing real data
- When to use it (what user intent / tool output triggers it)

---

## 7. Backend Integration Changes

### 7.1 Agent Coverage

Currently only the comms agent gets `OPENUI_INSTRUCTIONS` via `get_comms_agent_prompt(enable_openui=True)`.

The backend uses a **provider subagent template system** in `subagent_prompts.py`. The `BASE_SUBAGENT_PROMPT` template includes a `{provider_specific_content}` slot. Provider subagents are instantiated by name: `Gmail`, `Google Calendar`, `Google Tasks`, `Twitter`, `Reddit`, `Notion`, `LinkedIn`, `GitHub`, `Airtable`, `Linear`, `Slack`, `Google Sheets`.

**Important note on runtime behavior:** The comms prompt string is built at module load time in `agent_template.py` using `_settings.ENABLE_OPENUI`. Toggling `ENABLE_OPENUI` at runtime without restarting the API process has no effect — the cached prompt string does not update.

**Target injection strategy:** Add a `get_openui_instructions_for_provider(provider: str) -> str` helper to `openui_prompts.py` that returns a subset of component instructions relevant to that provider. Inject into `provider_specific_content` for each provider that has OpenUI components:

| Provider | Relevant Components |
|---|---|
| Comms agent | All components (existing) |
| Gmail | EmailListCard, EmailThreadCard, EmailComposeCard |
| Google Calendar | CalendarListCard, CalendarCreateCard, CalendarEditCard, CalendarDeleteCard |
| Google Tasks | TodoListCard |
| Reddit | RedditResultsCard, RedditPostCreatedCard |
| Twitter | TwitterCard, TwitterUserCard, TwitterPostCreatedCard |
| Notion / Google Docs | DocumentCard, GoogleDocsCard |

### 7.2 Tool Streaming Output Change

Per-tool, the backend changes from emitting structured `tool_data` to emitting an OpenUI fence in the response text:

```python
# Old: emit tool_data entry
writer({"tool_data": {"tool_name": "todo_data", "data": todos_list}})

# New: emit OpenUI fence in response text
writer({"response": f":::openui\nroot = TodoListCard(...)\n:::"})
```

The `format_streaming_chunk()` function in `chat_service.py` already handles both `response` and `tool_data` keys independently — no changes needed there.

### 7.3 Dual-Mode Transition Period

During migration, each tool runs in dual-mode. A `MIGRATED_TOOLS: set[str]` setting in `settings.py` (to be added — does not exist yet) tracks which tools have been moved. Until this is added, use a module-level constant in each agent file.

```python
# To be added to settings.py:
MIGRATED_TOOLS: set[str] = set()  # e.g., {"todo_data", "email_fetch_data"}

# In agent tool output:
if settings.ENABLE_OPENUI and "todo_data" in settings.MIGRATED_TOOLS:
    writer({"response": render_openui_todo(todos)})
else:
    writer({"tool_data": {"tool_name": "todo_data", "data": todos}})
```

**Critical:** A tool must NEVER emit both `tool_data` AND an `:::openui` block for the same data in the same response. The TextBubble renders tool_data first, then parses the response text for OpenUI fences — this would cause double rendering. Migration per tool must be atomic.

---

## 8. Component Authoring Guidelines

### 8.1 Read-Only Component Requirements

- Zod schema field names must exactly match the backend data type field names
- All optional fields must use `z.optional()`
- Component must handle empty / partial data (empty array, null values) with a graceful empty state
- No `useEffect` for data fetching — all data comes via props from OpenUI parser
- **Large datasets use scrollable overflow** — if a list has many items, scroll within the component. No "See all N" buttons, no pagination. The LLM receives all data and formats it into the component; render everything as-is.
- **Email list shows previews only** — same as the current `EmailComposeSection` display: subject, sender, snippet, date. Clicking triggers `continue_conversation` to fetch the full thread.
- Data renders as it streams — components should show partial data gracefully during streaming (isStreaming=true) without layout shifts.

### 8.2 Write-Action Component Requirements

- Use OpenUI `Form` with `Input`/`Select` for editable fields
- Pre-populate form from component props (backend provides draft data)
- Pass resource identifiers (thread_id, event_id, etc.) as an object prop — these arrive in `ActionEvent.params`
- Action convention: `submit:<verb>_<noun>` for form submit buttons, `action:<verb>_<noun>` for non-form buttons
- Always include a `Button("Cancel", "action:cancel")` — dispatcher treats this as a noop
- Destructive actions (delete): show inline confirmation text. The button should say "Confirm delete" not just "Delete".

### 8.3 Error States

Every component must handle:
- Null/undefined props → show skeleton placeholder or "No data available" text
- OpenUI parse errors → already caught by `OpenUIRenderer` error boundary (shows raw fence code as fallback)
- Action handler failure → action handler should show a toast or update inline state; no unhandled throws

---

## 9. What Must Never Break

1. **Email compose and send always works.** Until `email_compose_data` is explicitly migrated in Phase 2 and `MIGRATED_TOOLS` includes `"email_compose_data"`, the current `EmailComposeCard` + `EmailComposeSection` path must remain intact and functional.

2. **Tool data fallback.** Any tool NOT in `MIGRATED_TOOLS` must still render via the legacy `TOOL_RENDERERS` map in `TextBubble`. Entries stay until explicitly removed.

3. **No double-rendering.** Backend migration is atomic per tool. A single response never emits both `tool_data` entry AND an `:::openui` block for the same data.

4. **Streaming never blocks.** OpenUI components degrade gracefully if streaming is interrupted mid-block. The error boundary in `OpenUIRenderer` handles this.

5. **Feature flag.** `ENABLE_OPENUI=false` disables all backend prompt injection. The frontend fence parser (`parseOpenUISegments`) is always active but harmless when the backend doesn't emit `:::openui` blocks — the LLM simply never generates them when flag is off.

6. **Action fallback.** Unknown action types fall back to `continue_conversation` in `dispatchOpenUIAction`. No action throws an unhandled error.

---

## 10. Immediate Next Steps (Ordered)

| Priority | Task | Effort | Risk |
|---|---|---|---|
| P0 | Add `MIGRATED_TOOLS: set[str]` to `settings.py` | XS | None |
| P0 | Wire `continue_conversation` in `OpenUIRenderer` via `useAppendToInput()` | XS | None |
| P0 | Implement `openUIActionDispatcher` with built-in + direct handlers | S | Low |
| P1 | Build `TodoListCard` component + Zod schema | M | Low |
| P1 | Migrate backend `todo_data` → OpenUI (behind flag + MIGRATED_TOOLS) | M | Low |
| P1 | Build `EmailListCard` + `EmailThreadCard` | M | Low |
| P1 | Migrate backend email fetch tools → OpenUI | M | Low |
| P2 | Build remaining Phase 1 read-only components | L | Low |
| P2 | Extend subagent prompts: inject component-specific OpenUI instructions | M | Medium |
| P3 | Build Phase 2 write-action components + direct action handlers | L | Medium |
| P3 | Migrate `email_compose_data` → OpenUI EmailComposeCard (dual-mode) | L | **High** |
| P3 | Migrate `calendar_options` → OpenUI CalendarCreateCard | M | Medium |
| P4 | Migrate remaining write-action tools | XL | High |

---

## 11. Resolved Decisions

The following were open questions, now resolved:

1. **EmailListCard granularity:** Preview-only, same as current display. Subject, sender, snippet, date. Clicking triggers `continue_conversation` to let the agent fetch the full thread.

2. **Multi-component responses:** Supported. Same way tool_data currently allows multiple entries per response (e.g., weather + calendar in the same message), a single response can have multiple `:::openui` blocks. The fence parser already handles this. Backend prompt should guide the LLM on when it's appropriate to combine.

3. **Follow-up actions architecture:** Keep as-is. `follow_up_actions` text buttons remain the system for suggesting next steps. Do NOT replace with `openuiChatLibrary`'s `FollowUpBlock`.

4. **OpenUI form state persistence:** No changes needed. Tool data (including write-action form data passed as props) continues to be persisted in MongoDB (backend) and IndexedDB (frontend) exactly as it is today. No new persistence layer.

5. **Token budget / large datasets:** No frontend cap. The LLM receives all data and decides what to format into the component. Components handle large lists with **scrollable overflow** — not pagination or truncation.

6. **Agent personality:** CRITICAL constraint. The agent's natural, human conversational text must be preserved. OpenUI blocks appear **alongside** the text, not replacing it. The LLM should still talk naturally ("Here are your emails for today:") and the UI component follows inline — same as how tool_data currently renders below the text response. Never sacrifice the conversational quality of the response just to inject UI.
