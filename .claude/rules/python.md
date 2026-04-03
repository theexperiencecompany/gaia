---
description: Python and backend architecture standards for this codebase
paths:
  - "**/*.py"
---

# Python / Backend Standards

## Tooling

- **Ruff** for linting and formatting — never black, flake8, or isort
- **MyPy** for type checking — strict mode, full annotations required
- Run `nx lint api` and `nx type-check api` after every change
- Python 3.11+ — use modern syntax (`X | Y` unions, `match` statements)

## Imports

- All imports at the **top of the file** — no inline imports, no `import` inside functions
- Order (Ruff enforces):
  1. Standard library
  2. Third-party
  3. Internal (`app.*`, `shared.*`)
- Blank line between each group
- No wildcard imports (`from module import *`)

```python
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.todo_models import TodoModel
from shared.py.logging import get_contextual_logger
```

## Type Annotations

- **Every function and method must have full annotations** — parameters and return type
- Use `X | None` not `Optional[X]`
- Use `X | Y` not `Union[X, Y]`
- Use lowercase generics: `list[X]`, `dict[K, V]`, `tuple[X, ...]`
- Annotate `-> None` on functions that return nothing
- Use `Any` only when interfacing with untyped third-party code — never as a shortcut

## File & Structural Organization

Never create monolithic files. Keep every file focused on a single domain.

- `app/models/` — SQLAlchemy / MongoDB document models. One file per domain (`todo_models.py`).
- `app/schemas/` — Pydantic request/response schemas. One file per domain. Separate `CreateRequest`, `UpdateRequest`, `Response`.
- `app/services/` — Business logic. One file per domain. No route handling.
- `app/api/v1/endpoints/` — Route handlers. One file per domain. No business logic.
- `app/db/` — DB client setup and connection utilities only.
- `app/constants/` — Constants organized by domain (`cache.py`, `llm.py`, `auth.py`, `notifications.py`). Never hardcode values.
- `libs/shared/py/` — Code reused across `api`, `voice-agent`, and `bots`. If logic is duplicated in two apps, it belongs here.

## Pydantic Models

- Use `BaseModel` for all schemas
- Use `model_config = ConfigDict(from_attributes=True)` on ORM-mapped models
- `Field(description="...")` on all fields that appear in API docs
- Validation constraints inline: `Field(min_length=1, max_length=255)`
- Naming: `CreateTodoRequest`, `UpdateTodoRequest`, `TodoResponse`, `TodoModel`

## FastAPI — Route Handlers

One `APIRouter` per domain with `prefix` and `tags`. Every handler follows the same 3-step contract:

1. `log.set()` with everything known at the start (user, operation, IDs)
2. Delegate all work to a service function
3. `log.set()` again with result IDs, then return `JSONResponse`

```python
@router.post("/todos", response_model=TodoResponse, status_code=201)
async def create_todo(
    payload: CreateTodoRequest,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    log.set(user={"id": user["user_id"]}, todo={"operation": "create"})
    result = await create_todo_service(payload, user)
    log.set(todo={"id": result["_id"]})
    return JSONResponse(content=result)
```

- Always set `response_model=` on route decorators
- Correct status codes: `201` create, `204` delete, `404` not found
- Never return raw dicts — always `JSONResponse` or a Pydantic response model

## Service Layer

Services are async module-level functions, not classes.

- Do not create service classes with `__init__`, instance methods, or injected dependencies
- If grouping is needed, use a class with `@staticmethod` methods only — never `self`
- Services access MongoDB collections directly via `app.db.mongodb.collections` — no repository layer
- Keep query logic in the service function where it is used — do not extract one-off query helpers
- Return domain models, not raw DB documents

```python
# wrong
class TodoService:
    def __init__(self, db):
        self.db = db
    async def get_todo(self, todo_id: str): ...

# correct
async def get_todo(todo_id: str, user_id: str) -> TodoModel | None:
    return await todos_collection.find_one({"_id": todo_id, "user_id": user_id})
```

## Error Handling

Two error types, depending on context:

- **`HTTPException`** — for simple auth/validation failures where no extra context is needed
- **`AppError`** (`app.utils.errors`) — for external service failures, unexpected states, or data worth capturing

```python
from app.utils.errors import AppError

raise AppError(
    message="Payment processing failed",
    why="Stripe returned a card_declined error",
    fix="User should update their payment method",
    status_code=402,
    meta={"stripe_code": error.code, "user_id": user_id},
)
```

- `AppError` is consumed by the global exception handler and emitted to the wide event
- Never use bare `except:` — always name the exception type
- Never swallow exceptions silently
- Log unexpected errors with context, then re-raise or convert

## Logging

### Contextual logger — module-level structured logs

```python
from shared.py.logging import get_contextual_logger

log = get_contextual_logger("app.services.todo")
log.info("Todo created", todo_id=todo.id, user_id=user_id)
```

- Use structured key-value pairs — **never f-strings in log messages**
- `log.debug` — dev noise; `log.info` — notable events; `log.warning` — recoverable; `log.error` — failures

### Wide events — request-level canonical log lines

```python
from shared.py.wide_events import log, wide_task

async def process_todo(todo_id: str, user_id: str) -> None:
    async with wide_task("process_todo"):
        log.add(todo_id=todo_id, user_id=user_id)
        result = await do_work()
        log.add(result_count=len(result))
```

- Accumulate context as you go — call `log.set()` / `log.add()` after each significant step, not all at the end
- If an error occurs mid-function, the wide event already has the context leading up to it

## Caching

Use `@Cacheable` and `@CacheInvalidator` decorators from `app.decorators.caching` — no manual Redis get/set.

```python
@Cacheable(key_pattern="user:{user_id}:profile", ttl=USER_PROFILE_CACHE_TTL)
async def get_user_profile(user_id: str) -> UserProfile: ...

@CacheInvalidator(key_patterns=["user:{user_id}:*"])
async def update_user_profile(user_id: str, data: UpdateRequest) -> None: ...
```

- Use `{param_name}` in key patterns; use `smart_hash=True` for complex args
- TTL constants live in `app/constants/cache.py` — never hardcode

## Lazy Providers

Never initialize external clients (Stripe, PostHog, OpenAI, etc.) at import time.

- Decorate init functions with `@lazy_provider` from `app.core.lazy_loader`
- Retrieve via `await providers.aget("name")` — initialization runs once on first access
- `strategy=MissingKeyStrategy.WARN` for optional integrations (missing env vars don't crash startup)
- Register new providers in `app/core/provider_registration.py`

## Background Tasks (ARQ)

Every ARQ worker task wraps its body in `async with wide_task(...)`:

```python
async def process_reminder(ctx: dict, reminder_id: str, user_id: str) -> str:
    async with wide_task("process_reminder", reminder_id=reminder_id, user_id=user_id):
        reminder = await get_reminder(reminder_id)
        log.set(reminder={"title": reminder.title})
        await send_notification(user_id, reminder)
        return "ok"
```

- All I/O must be `async` — no blocking calls
- Never `time.sleep()` — use `asyncio.sleep()`
- Use `asyncio.gather()` for concurrent independent operations

## Lifespan

All startup and shutdown logic goes through `unified_startup()` / `unified_shutdown()` in `app/core/lifespan.py`.

- Do not initialize clients, load models, or connect to databases outside of this lifecycle
- The lifespan context manager emits a structured startup log

## DRY

- Before writing a new utility, service, or model, search the codebase
- Shared logic (logging, settings, secrets) comes from `gaia-shared` — never copy into app code
- If you find duplicated logic while working, consolidate before adding more

## Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Files | `snake_case` | `todo_service.py` |
| Functions / variables | `snake_case` | `def get_todo_by_id` |
| Classes | `PascalCase` | `class TodoService` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_TITLE_LENGTH = 255` |
| Pydantic schemas | `PascalCase` + intent suffix | `CreateTodoRequest`, `TodoResponse` |
| DB models | `PascalCase` + `Model` | `TodoModel` |

## Anti-Patterns

- No mutable default arguments (`def f(items=[])`) — use `None` and initialize inside
- No global mutable state — pass dependencies explicitly
- No sync DB/HTTP calls in async endpoints
- No `print()` — use the structured logger
- No catching and ignoring exceptions
- No monolithic service files that span multiple domains
- No copying logic from `gaia-shared` into app code — import it
