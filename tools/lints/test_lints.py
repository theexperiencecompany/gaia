"""Unit tests for the custom GAIA Python AST lints.

Run from the repo root:

    uv run --project apps/api pytest tools/lints/test_lints.py -q
    # or, stdlib only:
    python3 -m pytest tools/lints/test_lints.py -q

Each test writes a tiny source snippet into a temp tree whose path carries the
segment the rule filters on (``api/v1/endpoints/``, ``app/services/``, ``app/``)
and asserts on the returned violations.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unittest.mock import patch

import no_service_classes
import repository_boundaries
import route_contract
import tool_dump_boundary
import wide_events_logging


def _write(base: Path, rel: str, src: str) -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# route-contract
# --------------------------------------------------------------------------- #

_ENDPOINT_DIR = "app/api/v1/endpoints"


def test_route_handler_without_log_set_is_flagged(tmp_path: Path) -> None:
    src = (
        "@router.get('/x')\n"
        "async def get_x(user):\n"
        "    result = await do_work()\n"
        "    return JSONResponse(result)\n"
    )
    path = _write(tmp_path, f"{_ENDPOINT_DIR}/x.py", src)
    violations = route_contract.check([path])
    assert len(violations) == 1
    assert violations[0].line == 2  # the `def` line (decorators are separate AST nodes)
    assert "get_x" in violations[0].detail


def test_route_handler_with_log_set_is_clean(tmp_path: Path) -> None:
    src = (
        "@router.post('/x')\n"
        "async def create_x(user):\n"
        "    log.set(user={'id': user['id']})\n"
        "    return JSONResponse(await do_work())\n"
    )
    path = _write(tmp_path, f"{_ENDPOINT_DIR}/x.py", src)
    assert route_contract.check([path]) == []


def test_route_allowlisted_handler_is_clean(tmp_path: Path) -> None:
    # health.py::health_check is in the ratchet allowlist.
    src = "@router.get('/health')\nasync def health_check():\n    return {'ok': True}\n"
    path = _write(tmp_path, f"{_ENDPOINT_DIR}/health.py", src)
    assert route_contract.check([path]) == []


def test_non_route_function_is_ignored(tmp_path: Path) -> None:
    src = "async def helper(user):\n    return await do_work()\n"
    path = _write(tmp_path, f"{_ENDPOINT_DIR}/x.py", src)
    assert route_contract.check([path]) == []


def test_route_rule_ignores_files_outside_endpoints(tmp_path: Path) -> None:
    src = "@router.get('/x')\nasync def get_x():\n    return None\n"
    path = _write(tmp_path, "app/services/x.py", src)
    assert route_contract.check([path]) == []


# --------------------------------------------------------------------------- #
# no-service-classes
# --------------------------------------------------------------------------- #

_SERVICES_DIR = "app/services"


def test_service_class_with_instance_method_is_flagged(tmp_path: Path) -> None:
    src = (
        "class TodoService:\n"
        "    def __init__(self, db):\n"
        "        self.db = db\n"
        "    async def get(self, todo_id):\n"
        "        return await self.db.find(todo_id)\n"
    )
    path = _write(tmp_path, f"{_SERVICES_DIR}/todo.py", src)
    violations = no_service_classes.check([path])
    assert len(violations) == 1
    assert "TodoService" in violations[0].detail


def test_staticmethod_only_service_is_clean(tmp_path: Path) -> None:
    src = (
        "class TodoService:\n"
        "    @staticmethod\n"
        "    async def get(todo_id):\n"
        "        return await find(todo_id)\n"
    )
    path = _write(tmp_path, f"{_SERVICES_DIR}/todo.py", src)
    assert no_service_classes.check([path]) == []


def test_service_pydantic_and_enum_bases_are_clean(tmp_path: Path) -> None:
    src = (
        "class KnowledgeService(BaseModel):\n"
        "    name: str\n"
        "    def label(self):\n"
        "        return self.name\n"
        "\n"
        "class ModeService(StrEnum):\n"
        "    A = 'a'\n"
    )
    path = _write(tmp_path, f"{_SERVICES_DIR}/models.py", src)
    assert no_service_classes.check([path]) == []


def test_service_abc_base_is_clean(tmp_path: Path) -> None:
    src = (
        "class BaseSchedulerService(ABC):\n    def run(self):\n        raise NotImplementedError\n"
    )
    path = _write(tmp_path, f"{_SERVICES_DIR}/base.py", src)
    assert no_service_classes.check([path]) == []


def test_allowlisted_service_is_clean(tmp_path: Path) -> None:
    src = "class ComposioService:\n    def __init__(self, key):\n        self.key = key\n"
    path = _write(tmp_path, f"{_SERVICES_DIR}/composio.py", src)
    assert no_service_classes.check([path]) == []


def test_non_service_named_class_is_ignored(tmp_path: Path) -> None:
    # Stateful infra not named *Service is intentionally out of scope.
    src = "class SandboxPool:\n    def __init__(self):\n        self._lock = Lock()\n"
    path = _write(tmp_path, f"{_SERVICES_DIR}/pool.py", src)
    assert no_service_classes.check([path]) == []


# --------------------------------------------------------------------------- #
# wide-events-logging
# --------------------------------------------------------------------------- #


def test_stdlib_logging_import_is_flagged(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "app/services/x.py", "import logging\nlog = logging.getLogger(__name__)\n"
    )
    violations = wide_events_logging.check([path])
    assert len(violations) == 1
    assert violations[0].line == 1


def test_loguru_import_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "app/services/x.py", "from loguru import logger\n")
    assert len(wide_events_logging.check([path])) == 1


def test_relative_logging_import_is_clean(tmp_path: Path) -> None:
    # `from .logging import ...` is a local module, not stdlib logging.
    path = _write(
        tmp_path, "app/api/v1/middleware/__init__.py", "from .logging import LoggingMiddleware\n"
    )
    assert wide_events_logging.check([path]) == []


def test_wide_events_import_is_clean(tmp_path: Path) -> None:
    path = _write(tmp_path, "app/services/x.py", "from shared.py.wide_events import log\n")
    assert wide_events_logging.check([path]) == []


def test_allowlisted_sentry_path_is_clean(tmp_path: Path) -> None:
    path = _write(tmp_path, "app/config/sentry.py", "from loguru import logger as _loguru\n")
    assert wide_events_logging.check([path]) == []


# --------------------------------------------------------------------------- #
# repository-boundaries
# --------------------------------------------------------------------------- #


def test_collections_import_outside_repository_is_flagged(tmp_path: Path) -> None:
    src = "from app.db.mongodb.collections import todos_collection\n"
    path = _write(tmp_path, "app/services/brand_new_service.py", src)
    violations = repository_boundaries.check([path])
    assert len(violations) == 1
    assert "collections outside the repository layer" in violations[0].detail


def test_collections_import_allowlisted_is_clean(tmp_path: Path) -> None:
    # The one-shot backfill script is the allowlist's last remaining entry.
    src = "from app.db.mongodb.collections import get_async_collection\n"
    path = _write(tmp_path, "app/scripts/backfill_public_workflow_descriptions.py", src)
    assert repository_boundaries.check([path]) == []


def test_collections_import_inside_repositories_is_clean(tmp_path: Path) -> None:
    src = "from app.db.mongodb.collections import get_async_collection\n"
    path = _write(tmp_path, "app/db/repositories/notes.py", src)
    assert repository_boundaries.check([path]) == []


def test_bson_import_outside_db_is_flagged(tmp_path: Path) -> None:
    src = "from bson import ObjectId\n"
    path = _write(tmp_path, "app/services/brand_new_service.py", src)
    violations = repository_boundaries.check([path])
    assert len(violations) == 1
    assert "bson/ObjectId outside app/db/" in violations[0].detail


def test_bson_import_inside_db_is_clean(tmp_path: Path) -> None:
    src = "from bson import ObjectId\n"
    path = _write(tmp_path, "app/db/repositories/base.py", src)
    assert repository_boundaries.check([path]) == []


def test_repository_public_method_returning_any_is_flagged(tmp_path: Path) -> None:
    src = (
        "from typing import Any\n"
        "class TodoRepository:\n"
        "    async def get(self, todo_id: str) -> Any:\n"
        "        return None\n"
    )
    path = _write(tmp_path, "app/db/repositories/todo.py", src)
    violations = repository_boundaries.check([path])
    assert len(violations) == 1
    assert "returns Any" in violations[0].detail


def test_repository_public_method_missing_annotation_is_flagged(tmp_path: Path) -> None:
    src = "class TodoRepository:\n    async def get(self, todo_id):\n        return None\n"
    path = _write(tmp_path, "app/db/repositories/todo.py", src)
    details = " ".join(v.detail for v in repository_boundaries.check([path]))
    assert "arg 'todo_id' has no type annotation" in details
    assert "has no return type annotation" in details


def test_repository_underscore_method_is_exempt(tmp_path: Path) -> None:
    src = (
        "from typing import Any\n"
        "class TodoRepository:\n"
        "    async def _find(self, filter_: Any) -> Any:\n"
        "        return []\n"
    )
    path = _write(tmp_path, "app/db/repositories/todo.py", src)
    assert repository_boundaries.check([path]) == []


def test_repository_fully_typed_method_is_clean(tmp_path: Path) -> None:
    src = (
        "class TodoRepository:\n"
        "    async def get(self, todo_id: str, *, user_id: str) -> str | None:\n"
        "        return None\n"
    )
    path = _write(tmp_path, "app/db/repositories/todo.py", src)
    assert repository_boundaries.check([path]) == []


def test_cache_helper_import_outside_layers_is_flagged(tmp_path: Path) -> None:
    src = "from app.db.redis import get_cache, set_cache\n"
    path = _write(tmp_path, "app/services/brand_new_service.py", src)
    violations = repository_boundaries.check([path])
    assert len(violations) == 1
    assert "entity-cache helpers outside the cache layers" in violations[0].detail


def test_cache_helper_import_allowlisted_is_clean(tmp_path: Path) -> None:
    # mcp_tools_service is the non-entity MCP-tools rollup cache (Decision 2).
    src = "from app.db.redis import get_cache, set_cache, delete_cache\n"
    path = _write(tmp_path, "app/services/mcp/mcp_tools_service.py", src)
    assert repository_boundaries.check([path]) == []


def test_cache_helper_import_inside_db_is_clean(tmp_path: Path) -> None:
    src = "from app.db.redis import get_cache, set_cache\n"
    path = _write(tmp_path, "app/db/repositories/base.py", src)
    assert repository_boundaries.check([path]) == []


def test_cache_helper_import_inside_decorators_is_clean(tmp_path: Path) -> None:
    src = "from app.db.redis import get_cache, set_cache, delete_cache\n"
    path = _write(tmp_path, "app/decorators/caching.py", src)
    assert repository_boundaries.check([path]) == []


def test_raw_redis_cache_client_import_is_not_flagged(tmp_path: Path) -> None:
    # redis_cache is the raw client (locks / rate-limits), not an entity-cache helper.
    src = "from app.db.redis import redis_cache\n"
    path = _write(tmp_path, "app/services/brand_new_service.py", src)
    assert repository_boundaries.check([path]) == []


# --------------------------------------------------------------------------- #
# tool-dump-boundary
# --------------------------------------------------------------------------- #

_TOOL_DIR = "app/agents/tools"


def test_bare_model_dump_in_tool_is_flagged(tmp_path: Path) -> None:
    src = (
        "async def search(config, query):\n"
        "    docs = await list_docs()\n"
        "    return [d.model_dump() for d in docs]\n"
    )
    path = _write(tmp_path, f"{_TOOL_DIR}/reminder_tool.py", src)
    violations = tool_dump_boundary.check([path])
    assert len(violations) == 1
    assert violations[0].line == 3
    assert 'mode="json"' in violations[0].fix


def test_json_mode_model_dump_in_tool_is_clean(tmp_path: Path) -> None:
    src = (
        "async def search(config, query):\n"
        "    doc = await get_doc()\n"
        '    return doc.model_dump(mode="json")\n'
    )
    path = _write(tmp_path, f"{_TOOL_DIR}/reminder_tool.py", src)
    assert tool_dump_boundary.check([path]) == []


def test_non_json_mode_in_tool_is_flagged(tmp_path: Path) -> None:
    # An explicit but wrong mode is exactly the #917 bug with extra steps.
    src = (
        "async def search(config, query):\n"
        "    doc = await get_doc()\n"
        "    return doc.model_dump(mode='python')\n"
    )
    path = _write(tmp_path, f"{_TOOL_DIR}/reminder_tool.py", src)
    assert len(tool_dump_boundary.check([path])) == 1


def test_dynamic_mode_kwargs_in_tool_is_flagged(tmp_path: Path) -> None:
    # **kwargs could carry any mode; the boundary demands the literal.
    src = (
        "async def search(config, query, **kwargs):\n"
        "    doc = await get_doc()\n"
        "    return doc.model_dump(**kwargs)\n"
    )
    path = _write(tmp_path, f"{_TOOL_DIR}/reminder_tool.py", src)
    assert len(tool_dump_boundary.check([path])) == 1


def test_bare_model_dump_outside_tools_scope_is_clean(tmp_path: Path) -> None:
    # Service/repository dumps persist as BSON dates — python mode is correct there.
    src = "async def create(doc):\n    return await repo.insert(doc.model_dump())\n"
    path = _write(tmp_path, "app/services/reminders/service.py", src)
    assert tool_dump_boundary.check([path]) == []


def test_nested_helper_function_still_scoped_by_module(tmp_path: Path) -> None:
    src = "def _serialize(doc):\n    return doc.model_dump()\n"
    path = _write(tmp_path, f"{_TOOL_DIR}/helpers.py", src)
    assert len(tool_dump_boundary.check([path])) == 1


def test_allowlisted_function_at_audited_count_is_clean(tmp_path: Path) -> None:
    src = (
        "async def generate_image(prompt):\n"
        "    result = await api_generate_image(prompt)\n"
        "    return result.model_dump()\n"
    )
    path = _write(tmp_path, f"{_TOOL_DIR}/image_tool.py", src)
    with patch.object(
        tool_dump_boundary, "ALLOWLIST", {"app/agents/tools/image_tool.py::generate_image": 1}
    ):
        assert tool_dump_boundary.check([path]) == []


def test_new_bare_dump_in_allowlisted_function_is_flagged(tmp_path: Path) -> None:
    """The grandfathered count caps the exemption: a NEW bare dump in an
    allowlisted function pushes the count past the audited number."""
    src = (
        "async def generate_image(prompt):\n"
        "    result = await api_generate_image(prompt)\n"
        "    emit(result.model_dump())\n"
        "    return result.model_dump()\n"
    )
    path = _write(tmp_path, f"{_TOOL_DIR}/image_tool.py", src)
    with patch.object(
        tool_dump_boundary, "ALLOWLIST", {"app/agents/tools/image_tool.py::generate_image": 1}
    ):
        violations = tool_dump_boundary.check([path])
    assert len(violations) == 1
    assert "beyond the 1 grandfathered" in violations[0].detail
