"""Behaviour tests for tools/lints/check_typed_boundaries.py.

The scan is exercised directly on throwaway modules; the ratchet mechanics it
runs under are covered by test_check_plr_complexity.py through _ratchet.py.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from check_typed_boundaries import LOOSE_ANNOTATION, STRING_KEY_READ, scan


def _rule_lines(tmp_path: Path, source: str) -> dict[str, list[int]]:
    module = tmp_path / "apps" / "api" / "app" / "services" / "probe.py"
    module.parent.mkdir(parents=True)
    module.write_text(source)
    found = scan([module])
    return {rule: lines for (_, rule), lines in found.items()}


def test_loose_annotations_are_the_any_and_bare_dict_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from typing import Any\n"
        "def a(x: dict[str, Any]) -> None: ...\n"
        "def b(x: dict[str, int]) -> list[dict]: ...\n"
        "def c(x: Any, *args: str, **kw: dict[str, str]) -> dict[str, list[Any]]: ...\n"
        "def d(x: int) -> str: ...\n"
    )
    assert _rule_lines(tmp_path, source)[LOOSE_ANNOTATION] == [2, 3, 4, 4]


def test_string_key_reads_are_get_and_subscript_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from typing import Literal\n"
        "def f(payload, request, os):\n"
        "    a = payload.get('id')\n"
        "    b = payload['id']\n"
        "    payload['id'] = 1\n"
        "    c = request.headers['authorization']\n"
        "    d = request.query_params.get('page')\n"
        "    e = os.environ['HOME']\n"
        "    g: Literal['x'] = 'x'\n"
        "    return payload.get(a)\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [3, 4]


def test_boundary_modules_are_not_scanned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    module = tmp_path / "apps" / "api" / "app" / "patches" / "vendored.py"
    module.parent.mkdir(parents=True)
    module.write_text("def f(x: dict) -> dict: return x['a']\n")
    assert scan([module]) == {}


def test_a_route_decorator_is_not_a_string_key_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = "@router.get('/todos')\nasync def list_todos(payload):\n    return payload.get('id')\n"
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [3]


def test_a_read_on_a_name_annotated_with_a_typeddict_is_not_a_guess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from typing import TypedDict\n"
        "class Probe(TypedDict):\n"
        "    ok: bool\n"
        "class DeepProbe(Probe):\n"
        "    url: str\n"
        "def f(result: Probe, deep: DeepProbe | None, call: ToolCall, raw: dict) -> None:\n"
        "    local: Probe = result\n"
        "    a = result['ok']\n"
        "    b = deep['url']\n"
        "    c = call.get('name')\n"
        "    d = local['ok']\n"
        "    e = raw['ok']\n"
        "    g = result['ok']['x'] if False else None\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [12, 13]


def test_a_typeddict_binding_reaches_closures_but_not_rebindings_or_other_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from typing import TypedDict\n"
        "class Probe(TypedDict):\n"
        "    ok: bool\n"
        "def typed(payload: Probe) -> None:\n"
        "    a = payload['ok']\n"
        "    def closure():\n"
        "        return payload['ok']\n"
        "    def nested(payload):\n"
        "        return payload['ok']\n"
        "def untyped(payload):\n"
        "    return payload['ok']\n"
        "payload['ok']\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [9, 11, 12]
