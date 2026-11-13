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

import comment_slop
import docstring_slop
import no_service_classes
import pytest
import repository_boundaries
import route_contract
import run as lint_runner
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


def test_bson_import_in_scripts_is_exempt(tmp_path: Path) -> None:
    # Operational one-shot scripts work on raw documents across every store by
    # design (run manually, never on a request path) — the boundary is exempt.
    src = "from bson import ObjectId\n"
    path = _write(tmp_path, "app/scripts/delete_user_account.py", src)
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
# runner (run.py) — one rule crashing must not hide the others
# --------------------------------------------------------------------------- #


def test_rule_crash_reports_rule_and_file_and_remaining_rules_still_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report a crashed rule with its file, keep running the rest, and still exit non-zero."""
    _write(
        tmp_path,
        f"{_ENDPOINT_DIR}/x.py",
        "@router.get('/x')\n"
        "async def get_x(user):\n"
        "    result = await do_work()\n"
        "    return JSONResponse(result)\n",
    )  # route-contract violation — a rule that runs BEFORE the crash
    _write(
        tmp_path,
        "app/services/leaky.py",
        "from app.db.mongodb.collections import todos_collection\n",
    )  # repository-boundaries violation — a rule that runs AFTER the crash
    _write(
        tmp_path,
        "app/services/new_service.py",
        "class NewService:\n    def f(self):\n        pass\n",
    )

    parse_failure = SyntaxError("invalid syntax")
    parse_failure.filename = str(tmp_path / f"{_ENDPOINT_DIR}/x.py")
    parse_failure.lineno = 2

    import no_service_classes  # noqa: PLC0415 -- test-local import for patch target

    with patch.object(no_service_classes, "check", side_effect=parse_failure):
        code = lint_runner.main([str(tmp_path)])

    err = capsys.readouterr().err
    assert code == 1  # a crashed rule fails the run, like violations do
    assert "no-service-classes" in err  # the crashed rule is named
    assert f"{_ENDPOINT_DIR}/x.py:2" in err  # with the file and line it died on
    assert "SyntaxError: invalid syntax" in err  # an ast.parse failure, not a silent skip
    assert "route-contract" in err  # rules before the crash still ran
    assert "repository-boundaries" in err  # rules after the crash still ran
    assert "rule(s) crashed" in err  # the crash is in the failure summary


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
    """Flag a new bare dump that pushes an allowlisted function past its audited count."""
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


# --------------------------------------------------------------------------- #
# docstring-content
# --------------------------------------------------------------------------- #


def _docstring_codes(tmp_path: Path, rel: str, src: str) -> list[str]:
    violations = docstring_slop.check([_write(tmp_path, rel, src)])
    return sorted(v.detail.split(":")[0] for v in violations)


def _same_named_bases(tmp_path: Path) -> list[Path]:
    # memory_db_models.MemoryDocument is SQLAlchemy; memory_models.MemoryDocument is Pydantic.
    return [
        _write(
            tmp_path, "app/models/memory_db_models.py", "class MemoryDocument(Base):\n    pass\n"
        ),
        _write(
            tmp_path, "app/models/memory_models.py", "class MemoryDocument(BaseModel):\n    pass\n"
        ),
    ]


def test_a_subclass_of_a_non_runtime_twin_is_still_checked(tmp_path: Path) -> None:
    row = _write(
        tmp_path,
        "app/models/rows.py",
        "from app.models.memory_db_models import MemoryDocument\n\n\n"
        'class Row(MemoryDocument):\n    """Row with ``markup``."""\n',
    )
    violations = docstring_slop.check([*_same_named_bases(tmp_path), row])
    assert sorted(v.detail.split(":")[0] for v in violations) == ["DS2", "DS3"]


def test_a_subclass_of_the_runtime_twin_stays_exempt(tmp_path: Path) -> None:
    view = _write(
        tmp_path,
        "app/models/views.py",
        "from app.models.memory_models import MemoryDocument\n\n\n"
        'class View(MemoryDocument):\n    """View with ``markup``."""\n',
    )
    assert docstring_slop.check([*_same_named_bases(tmp_path), view]) == []


def test_a_base_named_through_its_module_resolves_to_that_module(tmp_path: Path) -> None:
    view = _write(
        tmp_path,
        "app/models/views.py",
        "from app.models import memory_models\n\n\n"
        'class View(memory_models.MemoryDocument):\n    """View with ``markup``."""\n',
    )
    assert docstring_slop.check([*_same_named_bases(tmp_path), view]) == []


def test_a_base_named_through_an_aliased_module_import_is_still_checked(tmp_path: Path) -> None:
    row = _write(
        tmp_path,
        "app/models/rows.py",
        "import app.models.memory_db_models as db_models\n\n\n"
        'class Row(db_models.MemoryDocument):\n    """Row with ``markup``."""\n',
    )
    violations = docstring_slop.check([*_same_named_bases(tmp_path), row])
    assert sorted(v.detail.split(":")[0] for v in violations) == ["DS2", "DS3"]


def test_docstring_over_the_function_cap_is_ds1(tmp_path: Path) -> None:
    body = "\n".join(f"    line {i}." for i in range(7))
    src = f'def f():\n    """Summary.\n\n{body}\n    """\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == ["DS1"]


def test_class_and_module_caps_are_wider_than_the_function_cap(tmp_path: Path) -> None:
    body = "\n".join(f"    line {i}." for i in range(7))
    src = f'"""Module.\n\n{body}\n"""\n\nclass C:\n    """Summary.\n\n{body}\n    """\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == []


def test_backticks_and_rst_markup_are_ds2_and_ds3(tmp_path: Path) -> None:
    src = 'def f():\n    """Read ``x`` from :param y:."""\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == ["DS2", "DS3"]


def test_multi_line_test_docstring_is_ds4_only_in_test_files(tmp_path: Path) -> None:
    src = 'def test_x():\n    """Summary.\n\n    More.\n    """\n'
    assert _docstring_codes(tmp_path, "tests/unit/test_x.py", src) == ["DS4"]
    assert _docstring_codes(tmp_path, "app/x.py", src) == []


def test_test_module_docstring_is_capped_by_ds1_not_ds4(tmp_path: Path) -> None:
    # The module's name is its file stem (test_x); DS4 is about test functions.
    src = '"""Summary.\n\nThree stub seams, and why seam B must patch at each importer.\n"""\n'
    assert _docstring_codes(tmp_path, "tests/unit/test_x.py", src) == []


def test_one_line_test_docstring_is_clean(tmp_path: Path) -> None:
    src = 'def test_x():\n    """Regression for #859: a cancelled executor left a stale tool result."""\n'
    assert _docstring_codes(tmp_path, "tests/unit/test_x.py", src) == []


def test_summary_restating_the_name_is_ds5(tmp_path: Path) -> None:
    src = 'def get_user_profile(user_id):\n    """Get the user profile."""\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == ["DS5"]


def test_summary_saying_more_than_the_name_is_clean(tmp_path: Path) -> None:
    src = 'def get_user_profile(user_id):\n    """Read the profile through the per-user cache; misses hit Mongo."""\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == []


def test_args_entry_restating_its_name_and_carrying_a_type_is_ds6_and_ds7(tmp_path: Path) -> None:
    src = (
        "def f(user_id, limit):\n"
        '    """Fetch rows.\n\n'
        "    Args:\n"
        "        user_id: The user ID.\n"
        "        limit (int): Rows per page; the last page may be short.\n"
        '    """\n'
    )
    assert _docstring_codes(tmp_path, "app/x.py", src) == ["DS6", "DS7"]


def test_examples_section_is_ds8(tmp_path: Path) -> None:
    src = 'def f():\n    """Do a thing.\n\n    Examples:\n        f()\n    """\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == ["DS8"]


@pytest.mark.parametrize(
    "decorator",
    ["@tool", "@composio.tools.custom_tool(toolkit='X')", "@router.get('/x')", "@with_doc(DOC)"],
)
def test_runtime_docstrings_are_never_checked(tmp_path: Path, decorator: str) -> None:
    body = "\n".join(f"    line {i} with ``markup``." for i in range(9))
    src = f'{decorator}\ndef f():\n    """Summary.\n\n{body}\n    """\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == []


def test_bare_mock_patch_is_not_a_route_decorator(tmp_path: Path) -> None:
    # `@patch(...)` is unittest.mock; only `@router.patch(...)` is a route.
    src = '@patch("x.y")\ndef test_x(m):\n    """Summary.\n\n    More.\n    """\n'
    assert _docstring_codes(tmp_path, "tests/unit/test_x.py", src) == ["DS4"]


def test_indirect_pydantic_subclass_docstring_is_never_checked(tmp_path: Path) -> None:
    # CamelModel lives in another file; its subclasses are schema descriptions too.
    base = _write(tmp_path, "app/models/base.py", "class CamelModel(BaseModel):\n    pass\n")
    body = "\n".join(f"    line {i} with ``markup``." for i in range(14))
    model = _write(
        tmp_path,
        "app/models/x.py",
        "from app.models.base import CamelModel\n\n\n"
        f'class M(CamelModel):\n    """Summary.\n\n{body}\n    """\n',
    )
    assert docstring_slop.check([base, model]) == []


def test_pydantic_model_docstring_is_never_checked(tmp_path: Path) -> None:
    body = "\n".join(f"    line {i}." for i in range(14))
    src = f'class M(BaseModel):\n    """Summary.\n\n{body}\n    """\n'
    assert _docstring_codes(tmp_path, "app/x.py", src) == []


def test_ten_line_test_module_docstring_is_clean(tmp_path: Path) -> None:
    # A cross-file map lives on the module, not on any one test function.
    body = "\n".join(f"line {i} of the map." for i in range(9))
    src = f'"""{body}\n"""\n\n\ndef test_x():\n    pass\n'
    assert _docstring_codes(tmp_path, "tests/unit/test_x.py", src) == []


def test_three_line_test_function_docstring_is_ds4(tmp_path: Path) -> None:
    src = 'def test_x():\n    """Summary.\n\n    More.\n    """\n'
    assert _docstring_codes(tmp_path, "tests/unit/test_x.py", src) == ["DS4"]


def test_module_docstring_is_exempt_when_the_file_reads___doc__(tmp_path: Path) -> None:
    # apps/api/app/scripts/*.py feed the module docstring to argparse as the
    # CLI's --help text; it is runtime data, not review prose.
    body = "\n".join(f"line {i} of the CLI help text." for i in range(20))
    src = (
        f'"""{body}\n"""\n\n'
        "import argparse\n\n\n"
        "def main() -> None:\n"
        "    argparse.ArgumentParser(description=__doc__)\n"
    )
    assert _docstring_codes(tmp_path, "app/scripts/x.py", src) == []


def test_module_docstring_is_still_capped_when_the_file_does_not_read___doc__(
    tmp_path: Path,
) -> None:
    body = "\n".join(f"line {i} of the CLI help text." for i in range(20))
    src = f'"""{body}\n"""\n'
    assert _docstring_codes(tmp_path, "app/scripts/x.py", src) == ["DS1"]


def test_typeddict_referenced_by_with_structured_output_is_exempt(tmp_path: Path) -> None:
    body = "\n".join(f"    line {i}." for i in range(14))
    schema = _write(
        tmp_path,
        "app/schemas/x.py",
        f'class FooSchema(TypedDict):\n    """Summary.\n\n{body}\n    """\n',
    )
    caller = _write(
        tmp_path,
        "app/services/y.py",
        "from app.schemas.x import FooSchema\n\n\n"
        "def call(llm):\n    return llm.with_structured_output(FooSchema)\n",
    )
    assert docstring_slop.check([schema, caller]) == []


def test_typeddict_referenced_by_bind_tools_is_exempt(tmp_path: Path) -> None:
    body = "\n".join(f"    line {i}." for i in range(14))
    schema = _write(
        tmp_path,
        "app/schemas/x.py",
        f'class BarSchema(TypedDict):\n    """Summary.\n\n{body}\n    """\n',
    )
    caller = _write(
        tmp_path,
        "app/services/y.py",
        "from app.schemas.x import BarSchema\n\n\n"
        "def call(llm):\n    return llm.bind_tools(BarSchema)\n",
    )
    assert docstring_slop.check([schema, caller]) == []


def test_typeddict_never_referenced_is_still_checked(tmp_path: Path) -> None:
    # The rule is precise, not a blanket TypedDict exemption: without a real
    # with_structured_output/bind_tools reference somewhere in the tree, the
    # docstring is graded normally.
    body = "\n".join(f"    line {i}." for i in range(14))
    src = f'class UnreferencedSchema(TypedDict):\n    """Summary.\n\n{body}\n    """\n'
    assert _docstring_codes(tmp_path, "app/schemas/x.py", src) == ["DS1"]


def test_with_doc_constant_assignment_is_never_a_docstring(tmp_path: Path) -> None:
    # `NAME = "..."` is an Assign, not an Expr(Constant); ast.get_docstring
    # never sees it regardless of length, decorator, or file.
    body = "\n".join(f"line {i} of tool description." for i in range(20))
    src = f'GATHER_CONTEXT_DOC = """{body}"""\n'
    assert docstring_slop.check([_write(tmp_path, "app/templates/docstrings/x.py", src)]) == []


def test_pyproject_per_file_ignore_with_d_exempts_the_whole_file(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint.per-file-ignores]\n"some/dir/**" = ["D"]\n',
    )
    body = "\n".join(f"    line {i} with ``markup``." for i in range(14))
    exempt = _write(tmp_path, "some/dir/x.py", f'"""Summary.\n\n{body}\n"""\n')
    checked = _write(tmp_path, "other/y.py", f'"""Summary.\n\n{body}\n"""\n')
    violations = docstring_slop.check([exempt, checked])
    assert [v for v in violations if v.path == exempt] == []
    checked_codes = {v.detail.split(":")[0] for v in violations if v.path == checked}
    assert {"DS1", "DS2"} <= checked_codes


def test_pyproject_per_file_ignore_without_d_does_not_exempt(tmp_path: Path) -> None:
    _write(
        tmp_path, "pyproject.toml", '[tool.ruff.lint.per-file-ignores]\n"some/dir/**" = ["DOC"]\n'
    )
    body = "\n".join(f"    line {i}." for i in range(14))
    src = f'"""Summary.\n\n{body}\n"""\n'
    assert _docstring_codes(tmp_path, "some/dir/x.py", src) == ["DS1"]


def test_pyproject_per_file_ignore_literal_path_exempts_that_file_only(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint.per-file-ignores]\n"some/dir/models.py" = ["D"]\n',
    )
    body = "\n".join(f"    line {i}." for i in range(14))
    src = f'"""Summary.\n\n{body}\n"""\n'
    exempt = _write(tmp_path, "some/dir/models.py", src)
    other = _write(tmp_path, "some/dir/other.py", src)
    violations = docstring_slop.check([exempt, other])
    assert [v for v in violations if v.path == exempt] == []
    assert [v for v in violations if v.path == other] != []


def test_pyproject_per_file_ignore_basename_pattern_matches_anywhere(tmp_path: Path) -> None:
    # A bare pattern (no "/") matches the basename anywhere in the tree --
    # ruff's documented "single-path pattern" rule.
    _write(tmp_path, "pyproject.toml", '[tool.ruff.lint.per-file-ignores]\n"models.py" = ["D"]\n')
    body = "\n".join(f"    line {i}." for i in range(14))
    exempt = _write(tmp_path, "deep/nested/models.py", f'"""Summary.\n\n{body}\n"""\n')
    assert docstring_slop.check([exempt]) == []


def test_set_repo_root_overrides_auto_detection(tmp_path: Path) -> None:
    # Auto-detection walks UP and stops at the nearest ruff-configured
    # pyproject.toml (one with no per-file-ignores, here) -- an explicit
    # override reaches the outer one instead, matched against ITS root,
    # proving the override takes precedence rather than merely filling a gap
    # auto-detection would have left empty anyway.
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint.per-file-ignores]\n"scan/some/dir/**" = ["D"]\n',
    )
    _write(tmp_path, "scan/pyproject.toml", "[tool.ruff]\n")
    body = "\n".join(f"    line {i}." for i in range(14))
    exempt = _write(tmp_path, "scan/some/dir/x.py", f'"""Summary.\n\n{body}\n"""\n')
    assert docstring_slop.check([exempt]) != []
    try:
        docstring_slop.set_repo_root(tmp_path)
        assert docstring_slop.check([exempt]) == []
    finally:
        docstring_slop.set_repo_root(None)


def test_runner_repo_root_flag_reaches_docstring_content(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint.per-file-ignores]\n"scan/some/dir/**" = ["D"]\n',
    )
    body = "\n".join(f"    line {i}." for i in range(14))
    scan_dir = tmp_path / "scan"
    _write(scan_dir, "some/dir/x.py", f'"""Summary.\n\n{body}\n"""\n')
    try:
        assert lint_runner.main(["--repo-root", str(tmp_path), str(scan_dir)]) == 0
    finally:
        docstring_slop.set_repo_root(None)


# --------------------------------------------------------------------------- #
# comment-content
# --------------------------------------------------------------------------- #


def _comment_codes(tmp_path: Path, src: str) -> list[str]:
    violations = comment_slop.check([_write(tmp_path, "app/x.py", src)])
    return sorted(v.detail.split(":")[0] for v in violations)


def test_four_consecutive_comment_lines_are_cm1_once(tmp_path: Path) -> None:
    src = "# one\n# two\n# three\n# four\n# five\nX = 1\n"
    violations = comment_slop.check([_write(tmp_path, "app/x.py", src)])
    assert [(v.line, v.detail[:3]) for v in violations] == [(1, "CM1")]


def test_three_consecutive_comment_lines_are_clean(tmp_path: Path) -> None:
    assert _comment_codes(tmp_path, "# one\n# two\n# three\nX = 1\n") == []


def test_pragmas_and_trailing_comments_do_not_count(tmp_path: Path) -> None:
    src = (
        "# noqa: E501\n# type: ignore\n# fmt: off\n# pragma: no cover\nX = 1  # why\nY = 2  # why\n"
    )
    assert _comment_codes(tmp_path, src) == []


def test_banner_inside_a_function_is_cm2(tmp_path: Path) -> None:
    src = "def f():\n    # ---- Step 1 ----\n    a = 1\n    # Step 2: go\n    return a\n"
    assert _comment_codes(tmp_path, src) == ["CM2", "CM2"]


def test_module_and_class_level_banners_are_allowed(tmp_path: Path) -> None:
    src = "# ---- Redis keys ----\nX = 1\n\nclass Settings:\n    # ---- Bot config ----\n    y: int = 2\n"
    assert _comment_codes(tmp_path, src) == []


def test_comment_restating_the_next_line_is_cm3(tmp_path: Path) -> None:
    src = "def f(rows):\n    # sort by date\n    rows.sort(key=by_date)\n"
    assert _comment_codes(tmp_path, src) == ["CM3"]


def test_comment_saying_why_is_clean(tmp_path: Path) -> None:
    src = "def f(rows):\n    # stable sort keeps same-day rows in insertion order\n    rows.sort(key=by_date)\n"
    assert _comment_codes(tmp_path, src) == []


def test_runner_hands_test_files_only_to_rules_that_opt_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        tmp_path, "tests/unit/test_x.py", 'def test_x():\n    """Summary.\n\n    More.\n    """\n'
    )
    _write(
        tmp_path,
        "tests/unit/test_y.py",
        "from app.db.mongodb.collections import todos_collection\n",
    )
    code = lint_runner.main([str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 1
    assert "DS4" in err  # docstring-content opted in and saw the test file
    assert "repository-boundaries" not in err  # the boundary rule still skips tests
