"""Tests for the evlog map scanner — one per rule that has been, or could go, wrong.

Run from the repo root:

    uv run --no-project --with pytest pytest tools/evlog_map -q

This suite is deliberately small. It is not coverage for its own sake: every
test here pins a rule whose inversion is *silent* — the scanner keeps running,
keeps printing a score, and the number it prints is wrong. Two such inversions
shipped in one day (an ``except`` matrix that passed 92 handlers which discarded
the caught error, and route resolution that resolved 2 of 283 paths), and the
gate that these rules feed did not notice either.

Each test drives real fixture source through the real scanner — ``scan.scan``
and the CLI's own ``main`` — never a re-implementation of a rule. Fixtures are
written under an ``apps/api/app`` prefix inside ``tmp_path`` because
``facts.repo_relative`` anchors on the ``apps``/``libs`` segment, so the paths
the scanner classifies on look exactly like real repo paths.

Every test is mutation-verified: inverting the rule it covers makes it fail.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from facts import repo_relative
import pytest
from routers import collect_router_mounts
from scan import MapResult, RouteEntry, collect_worker_registry, scan
from schema import canonical_fields
from voice import collect_voice_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
# The live schema, exactly as a real run reads it.
FIELDS = canonical_fields(REPO_ROOT)
APP_ROOT = "apps/api/app"


def _write(base: Path, rel: str, source: str) -> Path:
    """Write a fixture module under ``tmp_path/apps/api/app/<rel>``."""
    path = base / APP_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _scan(paths: list[Path], mounts: dict[str, str] | None = None) -> MapResult:
    """Run the real scanner over fixture files with no worker/voice registry."""
    return scan(paths, FIELDS, frozenset(), {}, mounts or {})


def _by_name(result: MapResult) -> dict[str, RouteEntry]:
    return {entry.handler.name: entry for entry in result.entries}


def _status(entry: RouteEntry, check_id: str) -> str:
    result = entry.checks.get(check_id)
    return result.status if result else "absent"


def _load_cli() -> ModuleType:
    """Import ``__main__.py`` under its own name — the CLI, gates included."""
    spec = importlib.util.spec_from_file_location(
        "evlog_map_cli", Path(__file__).resolve().parent / "__main__.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# error-handling — the six `except` shapes
#
# The matrix that was wrong: three shapes that *look* handled destroy the type
# and message of the real exception before anything can record them, so the
# request 500s with zero telemetry about what actually failed. The rule that
# accepted them scored 92 such handlers as clean.
# --------------------------------------------------------------------------- #

_EXCEPT_SHAPES = '''\
from fastapi import APIRouter, HTTPException

from shared.py.wide_events import log

router = APIRouter()


@router.get("/bare-raise")
async def bare_raise():
    """Re-raises the caught exception itself."""
    try:
        return await work()
    except ValueError:
        raise


@router.get("/raise-bound-name")
async def raise_bound_name():
    """Raises the bound name — the same object."""
    try:
        return await work()
    except ValueError as exc:
        raise exc


@router.get("/raise-from-bound")
async def raise_from_bound():
    """Chains the caught error, so __cause__ survives."""
    try:
        return await work()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="failed") from exc


@router.get("/records-then-returns")
async def records_then_returns():
    """Records the error on the event, then returns."""
    try:
        return await work()
    except ValueError as exc:
        log.error("work failed", error_type=type(exc).__name__)
        return {"ok": False}


@router.get("/raise-unchained")
async def raise_unchained():
    """Replaces the error with a fresh one — the original is gone."""
    try:
        return await work()
    except ValueError:
        raise HTTPException(status_code=500, detail="failed")


@router.get("/raise-from-none")
async def raise_from_none():
    """Deletes the cause on purpose."""
    try:
        return await work()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="failed") from None


@router.get("/returns-nothing")
async def returns_nothing():
    """Swallows: records nothing, re-raises nothing."""
    try:
        return await work()
    except ValueError:
        return {"ok": False}
'''

# The whole contract in one table — the shape of the bug that shipped.
_EXPECTED_EXCEPT_STATUS = {
    "bare_raise": "pass",
    "raise_bound_name": "pass",
    "raise_from_bound": "pass",
    "records_then_returns": "pass",
    "raise_unchained": "fail",
    "raise_from_none": "fail",
    "returns_nothing": "fail",
}


def test_every_except_shape_is_judged_by_whether_the_caught_error_survives(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "api/v1/endpoints/shapes.py", _EXCEPT_SHAPES)
    entries = _by_name(_scan([path]))

    assert set(entries) == set(_EXPECTED_EXCEPT_STATUS)
    actual = {name: _status(entry, "error-handling") for name, entry in entries.items()}
    assert actual == _EXPECTED_EXCEPT_STATUS


# --------------------------------------------------------------------------- #
# nested boundaries — a log_context() inside a nested helper is a real boundary
#
# _iter_own_scope stops at nested scopes for the route-contract facts, but a
# boundary inside an inline coroutine / generator (an SSE stream body, a
# fire-and-forget helper) is a real wide-event boundary. Without _iter_nested
# a worker whose boundary lives inside a nested def-in-block reads as dark.
# --------------------------------------------------------------------------- #

_NESTED_BOUNDARY_SOURCE = '''\
from shared.py.wide_events import log, log_context

async def run():
    """Worker entry with the boundary inside a nested coroutine."""
    try:
        async def _relay():
            async with log_context("nested_relay"):
                await work()
        await _relay()
    except Exception:
        raise
'''


def test_a_boundary_inside_a_nested_helper_is_credited(tmp_path: Path) -> None:
    path = _write(tmp_path, "workers/tasks/nested_boundary.py", _NESTED_BOUNDARY_SOURCE)
    # Worker entries are only scored when registered (worker.py wires them);
    # pass a registry containing the task so discovery actually sees it.
    result = scan([path], FIELDS, frozenset({"run"}), {}, {})
    entry = _by_name(result)["run"]
    assert _status(entry, "wide-event") == "pass"
    assert entry.checks["wide-event"].message == ""


# --------------------------------------------------------------------------- #
# route paths — resolved through the whole include_router chain
#
# A decorator's path is the last third of what the server serves. When the
# mount chain is not walked, ~90 handlers get a path the server never serves,
# and everything path-based (sensitivity, CREDENTIAL_ROUTES, the infra
# exemption, every printed path) is judged on a fiction.
# --------------------------------------------------------------------------- #


def _write_router_tree(tmp_path: Path) -> tuple[Path, Path, list[Path]]:
    """app → v1 → integrations → gmail, the real three-level nesting."""
    factory = _write(
        tmp_path,
        "core/app_factory.py",
        "from fastapi import FastAPI\n"
        "from app.api.v1.routes import router as api_router\n"
        "\n"
        "app = FastAPI()\n"
        'app.include_router(api_router, prefix="/api/v1")\n',
    )
    _write(
        tmp_path,
        "api/v1/routes.py",
        "from fastapi import APIRouter\n"
        "from app.api.v1.endpoints import memory\n"
        "from app.api.v1.endpoints.integrations import routes as integration_routes\n"
        "\n"
        "router = APIRouter()\n"
        "router.include_router(memory.router)\n"
        'router.include_router(integration_routes.router, prefix="/integrations")\n',
    )
    memory = _write(
        tmp_path,
        "api/v1/endpoints/memory.py",
        "from fastapi import APIRouter\n"
        "\n"
        'router = APIRouter(prefix="/memory")\n'
        "\n"
        "\n"
        '@router.get("/{memory_id}")\n'
        "async def get_memory(memory_id: str):\n"
        "    return {}\n",
    )
    _write(
        tmp_path,
        "api/v1/endpoints/integrations/routes.py",
        "from fastapi import APIRouter\n"
        "from app.api.v1.endpoints.integrations import gmail\n"
        "\n"
        "router = APIRouter()\n"
        'router.include_router(gmail.router, prefix="/gmail")\n',
    )
    gmail = _write(
        tmp_path,
        "api/v1/endpoints/integrations/gmail.py",
        "from fastapi import APIRouter\n"
        "\n"
        'router = APIRouter(prefix="/messages")\n'
        "\n"
        "\n"
        '@router.post("/{message_id}/archive")\n'
        "async def archive_message(message_id: str):\n"
        "    return {}\n",
    )
    return factory, tmp_path / "apps/api", [memory, gmail]


def test_route_paths_resolve_through_nested_include_router_prefixes(tmp_path: Path) -> None:
    factory, package_root, endpoints = _write_router_tree(tmp_path)

    mounts = collect_router_mounts(factory, package_root)
    assert mounts[repo_relative(endpoints[0])] == "/api/v1"
    assert mounts[repo_relative(endpoints[1])] == "/api/v1/integrations/gmail"

    entries = _by_name(_scan(endpoints, mounts))
    assert entries["get_memory"].handler.route_path == "/api/v1/memory/{memory_id}"
    assert (
        entries["archive_message"].handler.route_path
        == "/api/v1/integrations/gmail/messages/{message_id}/archive"
    )


def test_a_prefix_the_scanner_cannot_resolve_raises_instead_of_dropping_the_branch(
    tmp_path: Path,
) -> None:
    factory = _write(
        tmp_path,
        "core/app_factory.py",
        "from fastapi import FastAPI\n"
        "from app.api.v1.routes import router as api_router\n"
        "\n"
        "app = FastAPI()\n"
        "app.include_router(api_router, prefix=settings.API_PREFIX)\n",
    )
    _write(tmp_path, "api/v1/routes.py", "from fastapi import APIRouter\n\nrouter = APIRouter()\n")

    with pytest.raises(ValueError, match="not a string literal"):
        collect_router_mounts(factory, tmp_path / "apps/api")


# --------------------------------------------------------------------------- #
# sensitivity — what counts as a credential/auth surface
#
# High sensitivity buys the 25-point audit requirement and doubles the entry's
# weight in the global score. Both directions are silent when wrong: dropping
# CREDENTIAL_ROUTES stops asking account-takeover surfaces for an audit trail,
# and loosening the whole-word match relabels dozens of innocent routes.
# --------------------------------------------------------------------------- #

_DEVICE_ROUTES = '''\
from fastapi import APIRouter

from shared.py.wide_events import log

router = APIRouter(prefix="/device")


@router.post("/token")
async def rotate_refresh_token(payload: dict):
    """Refresh-token rotation — no auth word anywhere in the path."""
    log.set(user={"id": payload["user_id"]})
    return {}


@router.post("/pair/start")
async def start_device_pairing(payload: dict):
    """Device pairing, with the audit trail the rule asks for."""
    log.set(user={"id": payload["user_id"]})
    log.audit("device_pair_start", user_id=payload["user_id"])
    return {}
'''

_AUTHORS_ROUTES = '''\
from fastapi import APIRouter

from shared.py.wide_events import log

router = APIRouter(prefix="/authors")


@router.get("/{author_id}")
async def get_author(author_id: str):
    """`authors` contains `auth` but is not an auth route."""
    log.set(user={"id": author_id})
    return {}
'''

_PAYMENT_ROUTES = '''\
from fastapi import APIRouter

from shared.py.wide_events import log

router = APIRouter(prefix="/payments")


@router.post("/checkout")
async def start_checkout(payload: dict):
    """Money route, no audit trail."""
    log.set(payment={"plan": payload["plan"]})
    return {}
'''


def test_credential_and_money_routes_are_high_sensitivity_and_owe_an_audit_trail(
    tmp_path: Path,
) -> None:
    files = [
        _write(tmp_path, "api/v1/endpoints/device.py", _DEVICE_ROUTES),
        _write(tmp_path, "api/v1/endpoints/authors.py", _AUTHORS_ROUTES),
        _write(tmp_path, "api/v1/endpoints/payments.py", _PAYMENT_ROUTES),
    ]
    mounts = dict.fromkeys((repo_relative(f) for f in files), "/api/v1")
    entries = _by_name(_scan(files, mounts))

    classified = {
        name: (entry.sensitivity.level, entry.sensitivity.label) for name, entry in entries.items()
    }
    assert classified == {
        # Named in CREDENTIAL_ROUTES by its mounted path — no term matches it.
        "rotate_refresh_token": ("high", "auth"),
        "start_device_pairing": ("high", "auth"),
        # Whole-word matching: "authors" is not "auth".
        "get_author": ("low", ""),
        "start_checkout": ("high", "money"),
    }

    audit = {name: _status(entry, "audit") for name, entry in entries.items()}
    assert audit == {
        "rotate_refresh_token": "fail",
        "start_device_pairing": "pass",
        "get_author": "n/a",
        "start_checkout": "fail",
    }


# --------------------------------------------------------------------------- #
# discovery — and the "empty map scores 100" trap
#
# A score gate cannot see what was never discovered. Every registry must fail
# loudly when its wiring moves, because the alternative is a perfect score over
# an empty map, which every downstream gate waves through as an improvement.
# --------------------------------------------------------------------------- #

_MIXED_REGISTRATION = '''\
from fastapi import APIRouter

from shared.py.wide_events import log

router = APIRouter()


@router.get("/decorated")
async def decorated_handler():
    """Registered by decorator."""
    log.set(user={"id": 1})
    return {}


async def imperative_handler():
    """Registered imperatively — FastAPI serves it identically."""
    log.set(user={"id": 1})
    return {}


router.add_api_route("/imperative", imperative_handler, methods=["POST"])
'''


def test_both_decorator_and_add_api_route_registration_are_discovered(tmp_path: Path) -> None:
    path = _write(tmp_path, "api/v1/endpoints/mixed.py", _MIXED_REGISTRATION)
    entries = _by_name(_scan([path]))

    assert set(entries) == {"decorated_handler", "imperative_handler"}
    assert entries["decorated_handler"].handler.route_path == "/decorated"
    assert entries["imperative_handler"].handler.route_path == "/imperative"
    assert entries["imperative_handler"].handler.methods == ("post",)


def test_a_registry_whose_wiring_moved_raises_instead_of_finding_nothing(tmp_path: Path) -> None:
    worker = _write(tmp_path, "worker.py", "from app.core.config import settings\n")
    with pytest.raises(ValueError, match="registry moved"):
        collect_worker_registry(worker)

    agent = _write(tmp_path, "voice/agent.py", "def entrypoint(ctx):\n    return None\n")
    llm = _write(
        tmp_path, "voice/llm.py", "class VoiceLLM(LLM):\n    def chat(self):\n        ...\n"
    )
    with pytest.raises(ValueError, match="registry moved"):
        collect_voice_registry(agent, llm)

    factory = _write(tmp_path, "core/app_factory.py", "app = FastAPI()\n")
    with pytest.raises(ValueError, match="app factory moved"):
        collect_router_mounts(factory, tmp_path / "apps/api")


def test_a_map_with_no_entry_points_scores_zero_not_100(tmp_path: Path) -> None:
    """An empty map is the scanner going blind, not a perfect score — it must
    fail the --min-score gate instead of reporting 100 over nothing."""
    path = _write(
        tmp_path,
        "services/helpers.py",
        "async def not_an_entry_point():\n    return None\n",
    )
    cli = _load_cli()

    # The gate must FAIL an empty map (score 0, below --min-score 100)…
    assert cli.main([str(path), "--no-write", "--min-score", "100"]) == 1
    # …and the bare scan still exits 0 (the score is reported, not gated).
    assert cli.main([str(path), "--no-write"]) == 0


# --------------------------------------------------------------------------- #
# suppressions — a waiver needs a name attached to it
#
# The reason is the whole mechanism: without it, dropping a 40-point
# requirement is a bare comment nobody is accountable for.
# --------------------------------------------------------------------------- #

_SUPPRESSIONS = '''\
from fastapi import APIRouter

router = APIRouter()


# evlog-map-disable-next-line wide-event -- pure proxy, the upstream call owns the event
@router.get("/waived")
async def waived_handler():
    """Dark, but waived with a recorded reason."""
    return await proxy()


# evlog-map-disable-next-line wide-event
@router.get("/reasonless")
async def reasonless_handler():
    """Dark, and the directive names no reason — so it waives nothing."""
    return await proxy()
'''


def test_a_waiver_needs_a_reason_or_it_waives_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path, "api/v1/endpoints/waivers.py", _SUPPRESSIONS)
    result = _scan([path])
    entries = _by_name(result)

    waived = entries["waived_handler"].checks["wide-event"]
    assert (waived.status, waived.suppressed) == ("n/a", True)
    assert "pure proxy" in waived.message
    assert entries["waived_handler"].score == 100

    reasonless = entries["reasonless_handler"].checks["wide-event"]
    assert (reasonless.status, reasonless.suppressed) == ("fail", False)
    assert entries["reasonless_handler"].score == 60  # 100 - the wide-event weight
    assert any("no '-- <reason>'" in warning for warning in result.warnings)
