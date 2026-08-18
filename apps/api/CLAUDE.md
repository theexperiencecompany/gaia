# GAIA API

FastAPI backend for the GAIA personal AI assistant. Runs LangGraph agents, exposes REST/SSE/WebSocket endpoints, and manages all user data.

## Key Commands

All commands run from `apps/api/`. Prefer the `nx` wrappers (they set `cwd` and groups correctly) but the raw `uv` equivalents work too.

```bash
# Install / sync deps
nx run api:sync                        # uv sync --frozen --group backend --group dev

# Dev server (hot reload, port 8000)
nx dev api

# ARQ background worker
nx worker api

# Lint / format / type-check
nx lint api                            # ruff check
nx run api:lint:fix                    # ruff check --fix
nx format api                          # ruff format
nx type-check api                      # mypy app --ignore-missing-imports

# Tests (see Testing section below)
nx test api                            # unit + integration, 4 workers
nx run api:test:unit
nx run api:test:integration
nx run api:test:e2e                    # requires live services, not cached
nx run api:test:coverage
```

## Architecture

### Two-Agent Graph

The agent system uses two compiled LangGraph graphs registered via `GraphManager` / `ProviderRegistry`:

- **`comms_agent`** — thin front-door agent. Has only three tools: `call_executor`, `add_memory`, `search_memory`. Handles user-facing chat (streaming or silent).
- **`executor_agent`** — full-tool agent. Receives tasks from `comms_agent` via the `call_executor` tool. Has access to the entire tool registry retrieved from ChromaDB.

Both graphs are built in `app/agents/core/graph_builder/build_graph.py` and registered during startup via `build_graphs()`.

### Agent Execution Modes

`app/agents/core/agent.py` exposes two entry points that share `_core_agent_logic()`:

- `call_agent()` — returns `AsyncGenerator` for SSE streaming (chat endpoint)
- `call_agent_silent()` — returns `(message, tool_data)` tuple (workflows, background tasks)

### Streaming Architecture

Chat streaming is **decoupled from the HTTP connection** (see `app/api/v1/endpoints/chat.py`):

1. Endpoint launches an `asyncio.Task` that runs LangGraph and publishes SSE chunks to a Redis channel.
2. The HTTP response subscribes to that Redis channel and forwards chunks.
3. If the client disconnects, the background task keeps running and saves the conversation to MongoDB.
4. Stream cancellation via `POST /api/v1/cancel-stream/{stream_id}` sets a Redis flag that the background task checks.

### Lazy Provider System

All external clients (DBs, LLM clients, agent graphs) are registered as lazy providers via `app/core/lazy_loader.py`. A provider is initialized on first `providers.aget(name)` call, not at import time. Use the `@lazy_provider(name=..., required_keys=[...])` decorator to register new providers. Never call `providers.get(...)` for async providers — use `await providers.aget(...)`.

Providers are registered (not initialized) during `unified_startup()` in `app/core/provider_registration.py`.

### State

`app/agents/core/state.py` defines `State(DictLikeModel)`. It implements `MutableMapping` so LangGraph can use it like a dict. The `messages` field uses `add_messages` reducer — always append, never replace.

### Nodes

Pre-model hooks in `app/agents/core/nodes/`:

- `filter_messages_node` — strips unanswered tool calls from AI messages (does NOT trim by length; context-window trimming is the summarization middleware's job)
- `manage_system_prompts_node` — keeps only the latest of each system-message slot (static prompt / dynamic-context / todo-context / time) and drops stale copies, to hold the prompt-cache prefix stable; it does not inject prompts (that's `construct_langchain_messages`)
- `follow_up_actions_node` — end-of-graph hook on `comms_agent` only

### Tools

`app/agents/tools/core/registry.py` — central tool registry backed by ChromaDB for semantic retrieval. Tools that the executor agent may need are retrieved at inference time, not statically bound.

## Code Style

- All functions and methods require full type annotations (enforced by mypy).
- No inline imports — all imports at the top of the file.
- Use `ruff` for linting and formatting (not black/flake8/isort).
- Raise `AppError` (from `app/utils/errors.py`) for domain errors — it serializes to a structured JSON response automatically.
- Structured logging uses `from shared.py.wide_events import log`. Call `log.set(key=value)` to attach context fields to the request's wide event. `log.info(...)` emits a real-time line only and **never reaches the wide event**; `log.error(...)` / `log.warning(...)` emit a line *and* append to the event's `errors[]`/`warnings[]` — always with structured kwargs (`error_type=`, ids), not data interpolated into the message. `log.set(ns={...})` merges into the namespace rather than replacing it, so every layer of a request accumulates onto one namespace; `log.set_ns("ns", key=value)` is the same write with the namespace named explicitly and reads better for follow-up fields. Sensitive operations (auth, payments, PII writes) also call `log.audit(...)`. ARQ worker tasks do NOT open their own boundary — `arq_task` (`app/workers/task_envelope.py`), applied once per task in `app/worker.py`, wraps every registered task in a `wide_task()` carrying the propagated `trace_id` plus ARQ's `job_id`/`job_try`, so a task body just calls `log.set(...)`; enqueue through `enqueue_worker_job` (`app/workers/queue.py`), never `pool.enqueue_job` directly, or the job loses the caller's trace. Fire-and-forget background work is spawned with `spawn_logged_task("operation", coro(...))`, which gives it a `log_context()` boundary carrying the request's `trace_id`; without a boundary every `log.set()` inside that task is silently discarded. Write new fire-and-forget work that way, and move any `asyncio.create_task` call you touch over to it — `app/` still has ~42 bare `asyncio.create_task` call sites (plus several ad-hoc task sets keeping references alive) predating the helper, and they are being migrated incrementally rather than in one sweep. No stdlib `logging` / bare `loguru` in `app/` — enforced by the `wide-events-logging` lint (`tools/lints/README`).

### Docstrings & Comments

Default to **less**. The code is the documentation — docstrings and comments exist only where the code cannot speak for itself. AI-generated over-documentation (restating the signature in prose, narrating every line, "textbook" docstrings on trivial helpers) is a defect, not thoroughness. Strip it.

- **Docstrings** belong on public API surface — exported services, route handlers, shared utilities, and functions whose behavior is genuinely non-obvious. Skip them on private/internal helpers, obvious wrappers, and anything whose name + signature already says everything.
- **One line** is the default — and for helpers/internal functions it is a HARD CAP of two lines. A multi-paragraph docstring is reserved for genuinely complex public API; anywhere else it is a review comment waiting to happen. Add an `Args:`/`Returns:`/`Raises:` body only when a parameter, return value, or failure mode is non-obvious — never to mechanically mirror the signature. Document *why* and the non-obvious *what*, never the obvious what.
- **Never** document params/returns/raises that don't exist or no longer match the signature. A stale or hallucinated docstring is worse than none.
- **Comments** explain non-obvious decisions — a tricky invariant, a workaround and its cause, a "why this and not the obvious thing." A comment that restates what the line plainly does is noise; delete it. Never leave commented-out code — git already has it. `ERA001` is *not* currently enforced (213 findings in `app/`, concentrated in `models/calendar_models.py`, `agents/tools/webpage_tool.py` and the deliberately-parked `utils/calendar_utils.py`), so this one is on you rather than the linter until that backlog is cleared.
- When editing AI-generated code, treat trimming its redundant docstrings/comments as part of the change, not a separate cleanup.

### Tooling and the autofix hook

After every `.py` edit, a PostToolUse hook runs `uvx ruff format` then `uvx ruff check --fix` on the file. Formatting, import order/grouping, `Optional[X]` → `X | None`, `Union[X, Y]` → `X | Y`, lowercase generics, unused imports, mutable default args, bare `except`, and `print` are corrected automatically — do not hand-fix them.

What the hook does NOT fix, you handle:

- **Type errors** — `nx type-check api` (mypy strict). Add the missing annotation or correct the type. Use `Any` only for genuinely untyped third-party code.
- **Lint warnings ruff can't auto-resolve** — `nx lint api`, read the rule, fix the cause.

Python 3.11+: use modern syntax (`X | Y` unions, `match` statements).

## File & Structural Organization

One domain per file. Never let a file span multiple domains.

**New code goes in the module that owns the concept, never in the caller's file by convenience.** Before adding a function, ask where a reader would look for it — put it there and import it. Adding to an already-large file because "that's where it's used" is how monoliths grow.

- `app/models/` — SQLAlchemy / MongoDB document models, one file per domain (`todo_models.py`).
- `app/schemas/` — Pydantic request/response schemas, one file per domain. Separate `CreateRequest`, `UpdateRequest`, `Response`.
- `app/services/` — business logic, one file per domain. No route handling.
- `app/api/v1/endpoints/` — route handlers, one file per domain. No business logic.
- `app/db/` — DB client setup and connection utilities only.
- `app/constants/` — constants by domain (`cache.py`, `llm.py`, `auth.py`). Never hardcode values.

## Pydantic Models

- `BaseModel` for all schemas; `model_config = ConfigDict(from_attributes=True)` on ORM-mapped models.
- `Field(description="...")` on fields that appear in API docs; constraints inline (`Field(min_length=1, max_length=255)`).
- Naming: `CreateTodoRequest`, `UpdateTodoRequest`, `TodoResponse`, `TodoModel`.

## FastAPI — Route Handlers

One `APIRouter` per domain with `prefix` and `tags`. Every handler follows the same 3-step contract:

1. `log.set()` with everything known at the start (user, operation, IDs). Presence of this step is enforced by the `route-contract` lint (`tools/lints/README`).
2. Delegate all work to a service function.
3. `log.set()` again with result IDs, then return the Pydantic response model.

```python
@router.post("/todos", status_code=201)
async def create_todo(
    payload: CreateTodoRequest,
    user: dict = Depends(get_current_user),
) -> TodoResponse:
    log.set(user={"id": user["user_id"]}, todo={"operation": "create"})
    result = await create_todo_service(payload, user)
    log.set_ns("todo", id=result["_id"])  # merges into the namespace stamped in step 1
    return JSONResponse(content=result)

```

- The return annotation defines the response schema. Don't also pass `response_model=` — it is redundant and trips SonarQube S8409.
- **Never return a `JSONResponse` from a route that sets `response_model=`.** FastAPI skips response-model validation and serialization entirely for any `Response` instance a handler returns, so the declared schema is never enforced: the documented shape and the shipped payload drift apart silently and permanently. Returning the model is what keeps them inseparable.
- Never return raw dicts — return a Pydantic response model.
- Use correct status codes (`201` create, `204` delete, `404` not found).
- Decorator serializer options still apply, e.g. `response_model_exclude_none=True` when the payload must omit unset optional fields instead of sending nulls.
- A handler that genuinely cannot return a model — streaming, file download, redirect, a deliberately non-JSON body — returns the `Response` subclass and declares **no** `response_model`; a wrong schema is worse than no schema. To return a different body under a non-200 status, annotate the union and set the status on an injected `Response` (see `endpoints/health.py`) rather than reaching for `JSONResponse`.

## Analytics (PostHog)

Conventions, naming and the no-PII rule are in the root `CLAUDE.md`. The one API-specific decision:

**`capture_context_event(event, props)` vs `capture_event(user_id, event, props)`** — both live in `app/services/analytics_service.py`.

`capture_context_event` sends **no `distinct_id`**. It relies entirely on the contextvar identity that `PostHogRequestContextMiddleware` (`app/api/v1/middleware/auth.py`) sets, and that middleware only identifies a request that `WorkOSAuthMiddleware` already authenticated. Use it in ordinary authenticated route handlers, where it keeps the user id out of every call site.

Use `capture_event(user_id, ...)` — explicitly — whenever the handler resolves its user from something other than a session:

- OAuth / platform-link callbacks (the third party redirects the browser back with no session cookie)
- Bot routes (`require_bot_api_key`, user resolved via `PlatformLinkService`)
- Payment and provider webhooks
- ARQ worker tasks and any background/fire-and-forget path — there is no request at all

Getting this wrong is silent: the event is still captured, just attributed to a fresh anonymous person, so it never appears in that user's funnel. Nothing fails, no test goes red unless it asserts the id. **Assert the `distinct_id` in the test** — the mutation gate kills call-count-only assertions anyway.

## Service Layer

Services are async module-level functions, not classes.

- No service classes with `__init__`, instance methods, or injected dependencies. If grouping is needed, use a class with `@staticmethod` methods only — never `self`. Enforced for `*Service`-named classes by the `no-service-classes` lint (`tools/lints/README`).
- Services reach MongoDB through the domain repositories in `app.db.repositories`, never `app.db.mongodb.collections` directly. Only a repository touches its own collection; a service needing another domain's data calls that domain's repository (ownership rule). Enforced by the `repository-boundaries` lint (`tools/lints/README`).
- Repositories are the one deliberate exception to the no-service-classes rule: they are generic classes (`MongoRepository[TDoc, TUpdate]`) because the shared base eliminates per-collection CRUD duplication across 33 collections. Services stay functional and call the module-level repository singleton.
- Keep one-off query logic as a named, typed finder on the repository — not an ad-hoc filter dict in the service — and return typed document models, never raw DB dicts.

```python
# wrong
class TodoService:
    def __init__(self, db):
        self.db = db

    async def get_todo(self, todo_id: str): ...


# correct
async def get_todo(todo_id: str, user_id: str) -> TodoDocument | None:
    return await todo_repository.get(todo_id, user_id=user_id)
```

## Type Safety

Every value has a real, precise type — parameters, return types, class attributes, local variables, collection elements. `Any` and unparametrized generics (`dict`, `list`, `Callable` with no type arguments) are exactly as unsafe as no annotation at all: they satisfy mypy without adding any real protection. This is not just an endpoint/service concern — it applies everywhere in the codebase.

### 1. Every parameter and return type is real and specific, not just the return

Untyped or `Any`-typed *parameters* hide the same bugs as untyped returns — a function that accepts a loose bag and does `.get("key")` on it is exactly as unchecked as one that returns a loose bag.

```python
# wrong — nothing stops a caller from passing the wrong shape; typos in .get() keys are invisible
def apply_discount(order: dict[str, Any]) -> float:
    return order["subtotal"] * (1 - order.get("discount_pct", 0))


# correct — mypy catches a missing field or a typo'd key at every call site
class Order(BaseModel):
    subtotal: float
    discount_pct: float = 0.0


def apply_discount(order: Order) -> float:
    return order.subtotal * (1 - order.discount_pct)
```

### 2. Parametrize every generic container

`dict`, `list`, `set`, `tuple`, `Callable` without type arguments are implicitly `dict[Any, Any]`, `list[Any]`, etc. Always give the real element/argument/return types.

```python
# wrong
def group_by_status(todos: list) -> dict:
    ...

callback: Callable


# correct
def group_by_status(todos: list[TodoDocument]) -> dict[TodoStatus, list[TodoDocument]]:
    ...

callback: Callable[[TodoDocument], None]
```

### 3. Name a shape the moment it recurs — don't pass bags of dict/tuple around

If the same set of keys, or the same tuple positions, shows up in more than one signature, it is a type, not a convention. This applies to function returns, function parameters, and data threaded through several functions alike.

```python
# wrong — every caller has to know the keys/order by convention, nothing is checked
async def get_todo_summary(todo_id: str) -> dict[str, Any]:
    doc = await todo_repository.get(todo_id)
    return {"id": doc.id, "title": doc.title, "status": doc.status}


# correct — a real, named type, checked at every call site
class TodoSummary(BaseModel):
    id: str
    title: str
    status: TodoStatus


async def get_todo_summary(todo_id: str) -> TodoSummary:
    doc = await todo_repository.get(todo_id)
    return TodoSummary(id=doc.id, title=doc.title, status=doc.status)
```

Endpoints follow the same rule: never `-> dict[str, Any]`. Return a Pydantic model (see FastAPI — Route Handlers above). If a lower layer already returns a real model, return it (or build the response from it) directly — don't call `.model_dump()` just to downgrade it back to a dict.

### 4. Once something is a real model, use attribute access — `.get("key")` on it is the same guessing game as `dict[str, Any]`

`some_dict.get("key")` (or `dict["key"]`) only ever gets checked at runtime, if at all: a typo'd key silently returns `None` (or raises `KeyError` far from the mistake), there is no autocomplete, and nothing tells a reader what keys actually exist. This is true whether the dict came from `dict[str, Any]` or from calling `.model_dump()` on a perfectly good model just to consume it with `.get()` — both throw away the exact type information the model exists to provide. Once a shape is a named model (per item 3) or the underlying data source already returns one, consume it with real attribute access everywhere downstream, not just at the boundary where it was created.

```python
# wrong — doc is already a typed TodoDocument; .get() throws that away and
# guesses at runtime whether "assignee_id" is even a real field
async def get_assignee(todo_id: str) -> str | None:
    doc = await todo_repository.get(todo_id)
    data = doc.model_dump()
    return data.get("assignee_id")


# correct — real attribute access; a typo'd field name is a mypy error, not
# a silent None at runtime
async def get_assignee(todo_id: str) -> str | None:
    doc = await todo_repository.get(todo_id)
    return doc.assignee_id
```

This includes request payloads, cached/deserialized values, and anything already validated into a model earlier in the same flow — if it's a model, use its fields. The one case `.get()`/`dict[...]` access is still correct is genuinely dynamic data with no fixed schema (see item 7) — a raw webhook payload before validation, a mapping keyed by user-supplied strings, an `**kwargs`-style pass-through. Reaching for `.get()` out of habit on something that already has a real shape is the pattern to eliminate.

### 5. A fixed set of valid values is an `Enum`/`Literal`, not a bare `str`/`int`

```python
# wrong — any string compiles; a typo ("Compelted") is only caught at runtime, if ever
def set_status(todo: TodoDocument, status: str) -> None:
    todo.status = status


# correct — mypy rejects a typo or an invalid value at the call site
class TodoStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


def set_status(todo: TodoDocument, status: TodoStatus) -> None:
    todo.status = status
```

### 6. TypedDict vs Pydantic — pick by whether the boundary needs validation

- `BaseModel`: crosses a validation/serialization boundary (API request/response, DB document, anything built from untrusted or external input).
- `TypedDict`: a pure in-process shape contract with no need for runtime validation/coercion — cheaper, still fully checked by mypy.

### 7. Class attributes and instance state are typed too, not just function signatures

```python
# wrong — self.cache's real shape is discoverable only by reading every usage
class ToolRegistry:
    def __init__(self) -> None:
        self.cache = {}
        self.last_error = None


# correct
class ToolRegistry:
    def __init__(self) -> None:
        self.cache: dict[str, Tool] = {}
        self.last_error: Exception | None = None
```

### 8. External boundaries: validate immediately, don't propagate raw/`Any` data inward

Raw third-party payloads — webhook bodies, provider SDK responses, DB documents before repository parsing, subprocess/file/env output — may enter as `dict[str, Any]` or `Any`, because the boundary genuinely can't be typed until it's parsed. But validate into a real model in the same function that receives it, and never let the raw value travel more than one hop past where it entered.

```python
# acceptable — this IS the boundary; validated immediately, never returned raw
async def handle_webhook(payload: dict[str, Any]) -> WebhookEvent:
    return WebhookEvent.model_validate(payload)
```

### 9. Generic decorators/wrappers preserve the wrapped signature — they don't erase it to `Any`

A decorator typed `Callable[..., Any] -> Callable[..., Any]` destroys the return type of everything it wraps, which then leaks out as "Returning Any" errors at every call site, arbitrarily far from the actual decorator. Use `ParamSpec`/`TypeVar` to preserve the original signature through the wrapper.

```python
# wrong — every decorated function's real return type is lost
def log_calls(func: Callable[..., Any]) -> Callable[..., Any]:
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        log.info(f"calling {func.__name__}")
        return await func(*args, **kwargs)
    return wrapper


# correct — callers of a decorated function still get its real return type
P = ParamSpec("P")
R = TypeVar("R")

def log_calls(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        log.info(f"calling {func.__name__}")
        return await func(*args, **kwargs)
    return wrapper
```

If the wrapper's own call pattern (e.g. a two-step decorator factory) genuinely defeats `ParamSpec` inference and a real fix would require reworking the decorator's calling convention, that crosses the risk bar in §14 — leave it, and document why.

### 10. Never use a `TYPE_CHECKING`-guarded import to route around a circular import

A circular import is a real architectural problem — two modules that need each other. Hiding it behind `if TYPE_CHECKING:` (plus a string forward-reference) makes mypy happy without fixing anything: the cycle still exists, it's just invisible to anyone not specifically checking import order, and it signals "this dependency direction is wrong" to nobody. Fix the actual dependency instead.

```python
# wrong — TYPE_CHECKING import hides a real circular dependency; the cycle is
# still there, just invisible at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config.settings import CommonSettings


def validate_settings(settings_obj: "CommonSettings") -> list[MissingGroup]:
    for key in group.keys:
        if not hasattr(settings_obj, key):
            ...
```

```python
# correct — the function only ever does hasattr()/getattr() with dynamic
# keys; it never needed the concrete CommonSettings type at all. `object`
# is the honest, real type here, and the cycle disappears entirely.
def validate_settings(settings_obj: object) -> list[MissingGroup]:
    for key in group.keys:
        if not hasattr(settings_obj, key):
            ...
```

When the concrete type genuinely is needed (not just a couple of dynamically-accessed fields), fix the cycle for real:

- **Narrow to a `Protocol`** naming only the attributes actually used, defined locally — no import from the other module needed at all.
- **Extract the shared type** into a lower-level module both sides can import without a cycle (e.g. a `types.py` neither original module needs to import from the other for).
- **Invert the dependency** — restructure so the relationship only flows one direction; the thing being imported shouldn't need to import back.

`TYPE_CHECKING` has exactly two legitimate uses in this codebase, and nothing else:

1. **A stub-only module that doesn't exist at runtime** — e.g. `from _typeshed import ExcInfo`. `_typeshed` is a type-checker-only package; importing it unconditionally is a real `ImportError` at runtime, not caution. This is always fine, no comment needed.
2. **An import cycle that is provably real and unfixable without a large, out-of-scope restructure** — verify the cycle actually exists (import the target module directly and see if it errors) before reaching for `TYPE_CHECKING`; two of the four `TYPE_CHECKING` guards found in this codebase during this pass turned out to have no real cycle at all — unwarranted caution, not a fix, and were removed in favor of a normal top-level import. When the cycle is real, this is a last resort, with a comment naming which module imports back and why.

It is never the first thing to reach for, and it is never a substitute for actually checking whether the cycle exists.

### 11. Framework-injected / structurally-required parameters are kept exactly as the framework calls them

If a parameter is unused by one implementation but required by a framework's call signature — a LangGraph node/tool injecting `config`/`store`, FastAPI `Depends()`, an ARQ task's `ctx`, a Pydantic validator's `cls`/`info`, an abstract method's full interface — keep it. Verify the real call site or framework source first: "looks unused in this body" is not the same as "is unused." Add a `pyproject.toml` `per-file-ignores` entry naming the framework contract; never rename or delete the parameter to silence a linter.

### 12. Narrowing `Any`/unknown values: `cast()` over `isinstance()` when already correct by construction

Prefer `cast(RealType, value)` over `isinstance(value, RealType)` when you already know the value is correct by construction (a lazy-provider registry lookup, a well-known dict's `.get()` result, a value a framework's own contract guarantees). `cast()` only changes what the type checker believes; `isinstance()` changes what the code actually *does* at runtime, and can reject a structurally-compatible object — a mock, a duck-typed wrapper, a different concrete implementation of a `Protocol` — that was working fine before.

Never cast through `Any` (or an `Any`-parametrized container) to bypass a declared type — that re-introduces `Any` through the back door. Cast to the honest narrow type and validate/narrow what you pull out.

### 13. Never change behavior to satisfy a type checker

Confirmed real regressions from exactly this mistake: deleting an `isinstance(x, dict)` guard because a checker called the branch "unreachable" (it wasn't — real callers passed non-dict values); deleting a framework-injected parameter because it "looked unused" (the framework called it positionally); changing a function's actual return *values*, not just its annotation, to satisfy a stricter type (broke a downstream consumer needing the original shape). Fixing a type error changes how something is *described*; it must never change what the code *does*.

### 14. High acceptance bar — when to leave a type loose, deliberately, with a comment

Stop before forcing full type safety through:

- A change to data actually returned to an external consumer (frontend contract, external API caller, another service) — that's a product decision, not a typing fix.
- Rewriting a third-party library's call signature or a framework's calling convention.
- A change that ripples across more files than can be reviewed and verified in one pass.
- Anything whose correctness can't be confirmed by running the real test suite — "mypy is happy" is not proof; "the tests still pass and I can explain why" is.

A narrower type that's provably correct beats a "complete" one that required guessing.

### 15. Tighten the types in every file you touch — never widen them

Type safety is a ratchet: each file you edit leaves stricter than you found it, and never looser. This is not a licence to rewrite the file. Scope the tightening to the code you are already changing plus the signatures it flows through — the same bar as any other diff (Surgical Changes), so the change stays reviewable.

While you are in a function, fix what is in front of you: a `dict[str, Any]` return, an unparametrized `list`/`dict`/`Callable`, an untyped empty collection (`items = []`), a bare `str` holding a fixed value set, a magic literal that wants to be a constant or enum.

The one hard rule is the ratchet direction. Never *introduce* an `Any`, a bare generic, or an untyped empty collection into a file that did not already have one — including in a hurry, including "just for now." Adding a hole is never in scope; closing one nearly always is.

### 16. An existing annotation is a claim, not evidence — verify the runtime type before you trust it

`dict[str, Any]` does not merely lose precision. It launders wrong types downstream: `Any` is compatible with everything, so a false declaration on the receiving end is never challenged.

Real case from this codebase: `LLMProvider.instance` was declared `BaseChatModel` for months. The registry actually holds `RunnableConfigurableFields` (what `configurable_fields()` returns) — a `RunnableSerializable`, **not** a `BaseChatModel`. The `dict[str, Any]` feeding it is the only reason the lie survived; the code then called `configurable_alternatives()`, a method the declared type does not even have.

So when tightening, do not derive the "real" type from the neighbouring annotation, or from a factory's declared return. Construct the value and look:

```python
inst = providers.get("gemini_llm")
print(type(inst).__name__, isinstance(inst, BaseChatModel))  # RunnableConfigurableFields False
```

Then annotate what it *is*, and pick the type that actually declares the methods you call — `configurable_alternatives` lives on `RunnableSerializable`, not on bare `Runnable`/`LanguageModelLike`.

### 17. Prove the tightened annotation can fail

mypy passing before *and* after a "tightening" proves nothing changed — a decorative annotation is as green as a load-bearing one. Same rule as tests: if it cannot fail, it is not doing work.

Write a throwaway probe, run mypy on it, confirm it errors, delete it:

```python
# _typeprobe.py — delete after running
bad: LLMProvider = {"name": "x", "instance": "not-a-model"}   # expect: error
_get_ordered_providers({"gemini": "not-a-model"}, None, True)  # expect: error
reveal_type(_get_available_providers())                        # expect: the real type, not Any
```

`reveal_type` is the fastest way to confirm you closed the hole rather than moved it: if it still reveals `Any`, the annotation is cosmetic.

### 18. A literal repeated at a definition site and a lookup site is an enum, when we own the value set (see item 5)

Item 5 covers a fixed set of *values*. This is the sharper case: the same literal written in two places that must agree. Registry keys, event names, queue names, config keys, cache-key prefixes. Nothing enforces the match, so drift is silent and reaches production.

The enum is the answer only for a **closed, repository-owned** domain — one where we define every member and adding one is our change. When the values are external, open-ended, or owned by someone else's schema (provider model ids, third-party API fields, an upstream event vocabulary), an enum claims a closed world we don't control and goes stale the moment the other side adds a value. Those want a named constant in `app/constants/` referenced from both sites instead — same single source of truth, no false closed-world claim.

That is exactly how the `comms_agent` outage happened — `"gemini_llm"` lived in both `@lazy_provider(name="gemini_llm")` and the lookup mapping, and only one side was environment-gated. One enum, referenced from both sides, makes the drift impossible:

```python
class LLMProviderKey(StrEnum):
    GEMINI = "gemini_llm"
```

Prefer `StrEnum` over `(str, Enum)`. Both hash equal to their string value, so members stay usable as dict keys and in plain-string lookups — but `(str, Enum)` renders as `LLMProviderKey.GEMINI` in f-strings and log messages, while `StrEnum` renders `gemini_llm`. When the value is interpolated into a log line or an error message, `(str, Enum)` silently degrades it. Verify both properties before swapping a hot string for an enum member:

```python
d = {LLMProviderKey.GEMINI: 1}
assert d.get("gemini_llm") == 1          # dict-key compatible
assert f"{LLMProviderKey.GEMINI}" == "gemini_llm"   # renders as the value
```

## Anti-Patterns

- No sync DB/HTTP calls in async endpoints — all I/O must be `async`.
- No `time.sleep()` — use `asyncio.sleep()`; use `asyncio.gather()` for concurrent independent ops.
- No global mutable state — pass dependencies explicitly.
- No monolithic service files spanning multiple domains.
- No copying logic from `gaia-shared` into app code — import it.
- No raw `asyncio.create_task(...)` for fire-and-forget work — call `spawn_background_task()` from `app/utils/background_tasks.py`. It strong-refs the task until it finishes so the event loop can't GC it mid-flight; a bare `create_task` can vanish before running. (Long-lived tasks you store and later `await`/`cancel` are not fire-and-forget — those keep their own reference.)

## Database

| Store          | Used for                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **MongoDB**    | All user data: conversations, todos, reminders, workflows, notes, files, payments, integrations, etc. DB name is `GAIA`. Access is through the typed, cache-integrated domain repositories in `app.db.repositories` — only a repository touches its collection (enforced by the `repository-boundaries` lint). Repositories resolve the lazy async (Motor) collections via the internal accessor in `app.db.mongodb.collections`; services never import `<name>_collection` directly.                                                                                                                                                                                                       |
| **PostgreSQL** | LangGraph checkpointer (conversation thread state / memory). Also general relational data.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **Redis**      | Caching (hand-rolled in `app/db/redis.py` + `app/decorators/caching.py` — not `fastapi-cache2`), SSE stream channels, rate limiter counters, stream cancellation flags. Entity and query caching for repository-managed data is automatic inside the repository base (generation-based invalidation) — services never call `get_cache`/`set_cache`/`delete_cache` for it. The `@Cacheable`/`@CacheInvalidator` decorators (`app/decorators/caching.py`) remain the pattern only for non-entity caching (web search, favicons, provider metadata, OAuth status aggregation) — see `get_all_integrations_status()` in oauth_service.py. **Do NOT try to cache Composio tool objects in Redis** — they contain dynamically-generated Pydantic models and `functools.partial` closures that are not pickleable. Cache these in-memory on the `ComposioService` singleton instead (keyed by `(tool_name, user_id, hook_flags)` with a TTL). |
| **ChromaDB**   | Vector store for tool retrieval (which tools the executor should use), trigger embeddings, and public integration descriptions.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **RabbitMQ**   | Event publishing for cross-service messaging (bots, voice agent).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

## Testing

The single conventions doc — tiers, quality bar, run commands, naming — is **`tests/CLAUDE.md`**. Read it before writing any test. Copy-from-me scaffolds live in `tests/_template/`.

Tier summary (full table in `tests/CLAUDE.md`):

- `tests/unit/` — fast, hermetic, everything mocked. Mirrors `app/` (new service fn → `unit/services/`, new endpoint → `unit/api/`).
- `tests/integration/` — real production code, mocked infra. Wiring between components.
- `tests/integration/real/` — real Postgres/Redis/Mongo, `USE_REAL_SERVICES=1` + Docker (`nx run api:test:real`).
- `tests/contracts/` — repository contracts against real Mongo + Redis (`nx run api:test:contracts`).
- `tests/e2e/` — real compiled graphs, fake LLM via `_harness/` (`nx run api:test:e2e`).
- `tests/stress/` / `tests/meta/` — race/retry battles, import-fence invariants (own targets).
- `tests/composio/`, `tests/model_onboarding/` — live-credential, opt-in, excluded by default.

Never run a raw full `pytest` locally — use the nx targets (`nx test api`, `nx run api:test:*`); they pin the dirs, markers, and xdist settings.

**Unmark the patch-away.** A caller mocking a service means that service's logic has never run — the mock is a permanent blind spot. When you see an endpoint test mocking a service it barely touches, or a service test mocking a repo call whose logic matters, prefer un-mocking: let the real component run against mocked seams one layer down. Same rule as "never mock the thing under test."

Pytest mechanics: `asyncio_mode = auto` (async tests work without `@pytest.mark.asyncio`, but a class still needs `@pytest.mark.unit` etc. under `--strict-markers`). Default `addopts`: `-m "not composio and not model_onboarding" --strict-markers -n 4 --timeout=300`.

**Root `conftest.py` gotchas:**

- Sets `ENV=development` at import time before any app module loads. Must stay first.
- Blanks every credential-looking env var via the `_hermetic_environment` session fixture — tests must never depend on a developer's `.env` values.
- Patches `inject_infisical_secrets` and `MongoDB.ping` globally so tests never hang on external connections; patches `tiered_limiter.check_and_increment` and `payment_service.get_user_subscription_status` globally.
- `USE_REAL_SERVICES` defaults to `0` — a bare local run stays offline. Set it to `1` only for the real-infra tiers.
- Provides `client` (authenticated) and `unauthed_client` fixtures that use `ASGITransport` with a no-op lifespan.

**Integration API tests** use a separate `conftest.py` in `tests/integration/api/` that provides `test_client` and `unauthenticated_client` fixtures with `_MockAuthMiddleware` / `_NoAuthMiddleware`. These are different from the root `client` fixture.

## Native vs Dockered API (JuiceFS trade-off)

The API can run two ways in dev. They are **not** equivalent — the difference matters whenever you touch workspace v2, file uploads, artifacts, or sandbox file ops.

| Mode | How | Port | JuiceFS mount | Hot reload |
|---|---|---|---|---|
| **Native** (default) | `mise dev` / `nx dev api` | host:8000 | not available | `uvicorn --reload` |
| **Dockered** | `mise dev:vm` / `docker compose --profile backend up -d` | host:8000 → container:80 | mounted at `/mnt/jfs` | `WATCHFILES_FORCE_POLLING` |

### Why this split exists

JuiceFS is the host-side FUSE mount that backs workspace v2 (per-session FS, uploads, artifacts, skill installs). Mounting FUSE on Linux needs `CAP_SYS_ADMIN` + `/dev/fuse` + `apparmor:unconfined`. A native macOS process can't grant itself those — they only exist inside the dockered container. So the API code on the host has no `/mnt/jfs`, and `_require_mount()` in `app/services/storage/juicefs.py` raises `JuiceFSUnavailable`.

The compose file profile-gates `gaia-backend` (`profiles: ["backend", "all"]`) precisely so `mise dev` can give you a native API with fast iteration without forcing the JuiceFS plumbing on every dev session.

### What works in native mode

- Chat (LLM calls, message persistence, SSE streaming)
- Memory, todos, reminders, integrations, workflows, payments — anything Mongo/Postgres-only
- Most agent tool calls
- Sandbox tools that don't depend on the API seeding files via JuiceFS first

### What raises `JuiceFSUnavailable` in native mode

All of these call `_require_mount()` in `app/services/storage/juicefs.py`:

- `write_session_file` — user file uploads from the chat UI
- `ensure_user_workspace` — first-time workspace bootstrap for a user
- `write_skill_file` / `ensure_user_skills_dir` — installing skills to the user's workspace
- The artifact watcher in `app/services/sandbox/artifact_watcher.py` — needs to tail `/mnt/jfs/.accesslog`
- Any service path under `app/services/storage/sessions/` that touches the FS

If you hit `JuiceFSUnavailable` while running natively, **that is expected** — the fix is to switch to `mise dev:vm`, not to "fix" the error. Do not silence the exception, do not add a no-op fallback, do not stub `_is_mounted` to return `True`. The mount being missing is a load-bearing signal that JuiceFS-dependent features need the dockered API.

### When to use which

- **Default to native (`mise dev`).** Faster start, port 8000 free, `uv` commands work directly, hot reload is instant.
- **Switch to `mise dev:vm`** when your task touches `app/services/storage/`, `app/services/sandbox/`, file upload endpoints, artifact streaming, workspace v2 in general, or you start seeing `JuiceFSUnavailable` in logs.

### Coding-agent note

If you are an agent fixing a bug here and you see `JuiceFSUnavailable`: do **not** wrap it in `try/except: pass`, do **not** stub the storage helpers, and do **not** create a fake `/mnt/jfs` directory. The user's `mise dev` is intentionally configured to surface this. Either tell the user to switch to `mise dev:vm` for tasks that actually exercise JuiceFS, or confirm with them that the failing code path isn't relevant to the current task before changing anything.

## Environment

Settings class is selected by `ENV` env var (`production` | `development`). `DevelopmentSettings` makes most keys optional. `ProductionSettings` requires all keys.

Settings are loaded once via `@lru_cache` in `app/config/settings.py`. In tests, call `get_settings.cache_clear()` before recreating the app to pick up env changes.

Secrets in production are injected from **Infisical** before Pydantic validates the settings object. In development, use `.env` only.

See `apps/api/.env.example` or the `ProductionSettings` class in `app/config/settings.py` for the full list of required keys. For local dev, `DevelopmentSettings` makes most keys optional — set at minimum `ENV=development`, MongoDB URL, Redis URL, and WorkOS credentials.

### Dev auth bypass (`DEV_AUTH_BYPASS_EMAIL`)

When `DEV_AUTH_BYPASS_EMAIL=<email>` is set (development only), every request is authenticated as that Mongo user with no WorkOS session — `WorkOSAuthMiddleware` short-circuits before any cookie handling. This is how agents (and you) drive the full app end to end locally without logging in: point `apps/web/.env.local` at `http://localhost:8000/api/v1/` and the web app just works. **Don't set it in `apps/api/.env`** — it stays commented there so a bare `mise dev` is the real WorkOS login flow. Enable the bypass with the `--agent` flag (real LLM) or `--sim` (scripted LLM) on `mise dev` (native) or `mise dev:vm` (dockered API + JuiceFS); each exports `DEV_AUTH_BYPASS_EMAIL=${DEV_USER:-dev@gaia.local}` for you and refuses to run under `ENV=production` (`scripts/dev/assert-not-prod.sh`, backed by the `get_settings()` guard). For the full operating cookbook (boot matrix, mint/seed/impersonate curls, driving the API/browser/bots), see the **`driving-gaia`** skill.

Related: `GAIA_SIM_MODE=1` (`mise dev --sim`) routes every LLM call to the local scripted stub — use it to verify *plumbing* (tool flow, streaming, persistence) deterministically; never to judge real model behavior (prompts, tool selection, tone). The skill has the full use/don't-use table. Production refuses to boot with it set.

- The user must exist in Mongo. Mint one without a WorkOS login via the dev router: `POST /api/v1/dev/users {"email": ...}` (idempotent; reuses the real signup path). A bypass target that resolves to no user fails loud with a 401 whose message names the fix ("mint it via POST /api/v1/dev/users") instead of a generic auth error.
- Per-request impersonation: with the bypass active, an `X-Dev-User: <email>` request header authenticates as that user instead of `DEV_AUTH_BYPASS_EMAIL`, so one server can act as many users without restarts. Applies to HTTP (middleware) and WebSocket paths.
- The dev router (`/api/v1/dev/*` — mint, seed, delete, direct agent runs) is mounted only when `ENV=development` and `DEV_AUTH_BYPASS_EMAIL` is set; it 404s otherwise. It is excluded from the auth bypass so minting the first user is possible before any user exists.
- Direct layer invocation for tests: `POST /api/v1/dev/executor` runs the executor without the comms front door; `POST /api/v1/dev/subagents/{id}` runs one subagent without comms or the executor (`GET /api/v1/dev/subagents` lists ids). Both reuse the production preparation paths (`prepare_executor_execution` / `prepare_subagent_execution`) — see the `driving-gaia` skill §5.
- Development only: `get_settings()` raises at startup if the var is set with `ENV=production` — never weaken that check.
- The bypass user context carries `dev_bypass=True` for anything that needs to tell.
- WorkOS is never called under the bypass, but `DevelopmentSettings` still requires the `WORKOS_*` keys — dummy values are fine locally.
- On Windows with a native Redis (Memurai), use `REDIS_URL=redis://127.0.0.1:6379` — Memurai binds IPv4 only and `localhost` resolves to `::1` first, which makes the ARQ/lifespan services time out and startup fail.
- A `dev_bypass_user` cookie overrides the configured email per request, so two browser profiles can act as different users against one API instance (test free vs pro side by side).

## Pre-commit Hooks & Security Scanners

The API pre-commit config (`.pre-commit-config.yaml`) runs: **ruff**, **ruff-format**, **bandit**, **pip-audit**, **mypy**, and **gaia-python-lints** (the custom AST rules in `tools/lints/` — route contract, no service classes, wide-events logging).

### Bandit

Bandit runs `uvx bandit -r app` on every commit. When it flags a genuine false positive:

1. Confirm it is actually a false positive — read the rule, understand why Bandit is triggering.
2. Suppress inline using `# nosec B<rule_id>` (prefer explicit rule IDs over bare `# nosec`).
3. Always add a comment on the line above explaining why it is a false positive — do not suppress silently.

Common rules: `B101` (assert), `B106` (hardcoded password — often env var defaults), `B311` (random for non-crypto use), `B603/B607` (subprocess), `B324` (md5/sha1 for non-security purposes).

### SonarQube

SonarQube scans run in CI. Suppress false positives with `# NOSONAR` (all rules) or `# NOSONAR python:S<id>` (specific rule) on the offending line. Only suppress after confirming it is a false positive, and add a comment explaining why.

### After Major Changes

Always run these before considering work complete:

```bash
# Backend
nx type-check api
nx lint api

# Frontend
nx run-many -t type-check --projects=web,desktop
nx run-many -t lint --projects=web,desktop
```

## Non-Obvious Patterns

- **`app/patches.py`** is imported at the top of `main.py` with `# noqa: F401` — it applies monkey-patches to third-party libraries at startup. Do not remove this import.
- **Docs are disabled in production**: `/docs` and `/redoc` return 404 when `ENV=production`. Use `ENV=development` locally.
- **`app/core/lazy_loader.py` `providers` is a global singleton** — unique provider names are critical. Use UUID suffixes in tests to avoid cross-test pollution (the registry is never reset between tests).
- **LangGraph checkpointer**: Uses PostgreSQL (`langgraph-checkpoint-postgres`) in production, falls back to in-memory `InMemorySaver` if the checkpointer manager is unavailable.
- **Background memory storage**: memory ingestion (`memory_node.py`) is fire-and-forget on the end-of-graph hook. Spawn it — and all fire-and-forget work — via `spawn_background_task()` (`app/utils/background_tasks.py`) so the task isn't garbage-collected mid-flight (see Anti-Patterns).
- **`UJSONResponse`** is the default response class (faster JSON serialization). Custom error handlers in `app_factory.py` return plain `JSONResponse` to avoid double-serialization issues.
- **`ENABLE_LAZY_LOADING=true`** (default) means startup blocks until services initialize. Setting it to `false` makes the server start immediately and warm up in the background — safe for requests because `LazyLoader` uses per-provider locks.
- **Context-assembly sections are the one deliberate exception to "fail loud" (root `CLAUDE.md`).** Every fetcher in `app/agents/context/fetchers.py` catches broadly and returns `""` instead of raising — a context section is enrichment, and failing a user's whole turn because a memory recall or a knowledge-base lookup timed out trades a degraded answer for no answer. The exception is narrow and enforced: only these fetchers and `assemble_context`'s outer catch swallow; every swallow still calls `log.warning`/`log.error` so the failure is visible in the wide event, and a persistent failure degrades to a byte-stable empty block rather than a different one every call (which would itself invalidate the prompt cache). Do not generalize this pattern to other services — see `app/agents/context/fetchers.py`'s module docstring for the full reasoning.
- **Sandbox user has no `sudo`.** The `gaia-coder` template strips the sandbox user from the `sudo` and `wheel` groups (see `apps/api/scripts/build_e2b_template.py`). Drive root-needing operations (mount.sh, accesslog tail) through e2b's `sbx.commands.run(..., user="root")` parameter — never prefix shell commands with `sudo` in API code, the call will fail. JuiceFS itself runs under `/etc/gaia/jfs_launcher.py` which marks the daemon non-dumpable (`PR_SET_DUMPABLE=0`) so its `/proc/<pid>/{environ,cmdline}` are unreadable to the unprivileged user. `/proc` is mounted `hidepid=invisible` so even PID enumeration is denied. Verify after template rebuilds with `apps/api/scripts/verify_sandbox_hardening.sh`.
