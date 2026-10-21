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


def test_a_class_built_on_an_imported_library_typeddict_is_a_typeddict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from langgraph_bigtool.graph import State as _BigtoolState\n"
        "from langgraph.graph import MessagesState\n"
        "from elsewhere.graph import State as _Unlisted\n"
        "class State(_BigtoolState):\n"
        "    todos: list\n"
        "class Other(_Unlisted):\n"
        "    todos: list\n"
        "def f(state: State, plain: MessagesState, other: Other) -> None:\n"
        "    a = state.get('messages')\n"
        "    b = plain['messages']\n"
        "    c = other.get('messages')\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [11]


def test_a_loop_over_a_typeddict_collection_binds_a_typed_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from collections.abc import Iterable, Sequence\n"
        "from typing import Any, TypedDict\n"
        "class Turn(TypedDict):\n"
        "    role: str\n"
        "def f(history: list[Turn], seq: Sequence[Turn], it: Iterable[Turn], s: set[Turn],\n"
        "      fs: frozenset[Turn], tup: tuple[Turn, ...], calls: list[ToolCall],\n"
        "      raw, loose: list[dict[str, Any]]) -> None:\n"
        "    a = [turn.get('role') for turn in history]\n"
        "    for t in seq:\n"
        "        b = t['role']\n"
        "    c = {x['role'] for x in it}\n"
        "    d = {y['role']: 1 for y in s}\n"
        "    e = list(z['role'] for z in tup)\n"
        "    g = [call['name'] for call in calls]\n"
        "    h = [r['role'] for r in raw]\n"
        "    i = [w['role'] for w in loose]\n"
        "    for u in history:\n"
        "        u = u.copy()\n"
        "        j = u['role']\n"
        "    for k, v in enumerate(history):\n"
        "        m = v['role']\n"
        "    n = [q['role'] for q in fs]\n"
        "    def closure():\n"
        "        return [p['role'] for p in history]\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [15, 16, 19, 21]


def test_a_loop_over_a_typeddict_mapping_binds_its_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from collections.abc import Mapping\n"
        "from typing import Any, TypedDict\n"
        "class Entry(TypedDict):\n"
        "    name: str\n"
        "def f(tools: dict[str, Entry], ro: Mapping[str, Entry], raw: dict[str, dict[str, Any]]) -> None:\n"
        "    for v in tools.values():\n"
        "        a = v['name']\n"
        "    for k, e in ro.items():\n"
        "        b = e['name']\n"
        "    c = {k2: w['name'] for k2, w in tools.items()}\n"
        "    d = [x.get('name') for x in ro.values()]\n"
        "    for r in raw.values():\n"
        "        g = r['name']\n"
        "    for key in tools.keys():\n"
        "        h = key['name']\n"
        "    for y in tools.values():\n"
        "        y = {}\n"
        "        i = y['name']\n"
        "    for m, n in tools.values():\n"
        "        j = n['name']\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [13, 15, 18, 20]


def test_chromadb_results_are_library_typeddicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from chromadb.api.types import GetResult, QueryResult\n"
        "def f(got: GetResult, found: QueryResult, other: dict) -> None:\n"
        "    a = got['ids']\n"
        "    b = found.get('documents')\n"
        "    c = other['ids']\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [5]


def test_each_comprehension_is_its_own_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "def f(messages, made: list[ToolCall]) -> None:\n"
        "    raw = [call for m in messages for call in m.tool_calls]\n"
        "    a = [call.get('name') for call in made]\n"
        "    b = [call.get('name') for call in raw]\n"
        "    for call in raw:\n"
        "        d = call['name']\n"
        "    c = [call['name'] for call in made]\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [4, 6]


def test_an_optional_typeddict_collection_still_binds_its_loop_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from typing import Any, Optional, TypedDict\n"
        "class Turn(TypedDict):\n"
        "    role: str\n"
        "def f(history: list[Turn] | None, old: Optional[list[Turn]],\n"
        "      loose: list[dict[str, Any]] | None) -> None:\n"
        "    a = [turn.get('role') for turn in history or []]\n"
        "    b = [turn.get('role') for turn in history]\n"
        "    c = [turn['role'] for turn in old]\n"
        "    d = [w['role'] for w in loose]\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [6, 9]


def test_a_composio_execution_response_is_a_library_typeddict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from composio.core.models.tools import ToolExecutionResponse\n"
        "def f(response: ToolExecutionResponse, other: dict) -> None:\n"
        "    a = response.get('successful')\n"
        "    b = response['error']\n"
        "    c = other['error']\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [5]


def test_a_dom_nodes_attributes_are_a_string_key_read_like_any_other_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "def f(node, request) -> None:\n"
        "    a = node.attributes.get('type')\n"
        "    b = node.attributes['href']\n"
        "    c = request.headers['authorization']\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [2, 3]


def test_playwrights_storage_state_is_a_library_typeddict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from playwright.sync_api import StorageState, StorageStateCookie\n"
        "def f(state: StorageState, cookie: StorageStateCookie, other: dict) -> None:\n"
        "    a = state['cookies']\n"
        "    b = cookie.get('domain')\n"
        "    c = other['cookies']\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [5]


def test_a_storage_state_from_anywhere_but_playwright_is_not_a_known_typeddict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("check_typed_boundaries.REPO_ROOT", tmp_path)
    source = (
        "from elsewhere.state import StorageState\n"
        "def f(state: StorageState) -> None:\n"
        "    a = state['cookies']\n"
    )
    assert _rule_lines(tmp_path, source)[STRING_KEY_READ] == [3]
