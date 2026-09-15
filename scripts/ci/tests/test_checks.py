"""The file-walking hygiene gates (scripts/ci/checks.mjs).

These gates decide what gets scanned, and getting that wrong is invisible: a
scan over zero files prints "✓ All files within size limits" and exits 0, which
reads exactly like a clean repo. That is the failure this file exists to catch —
the lane cannot tell you it checked nothing, so a test has to.

Driven as the real script against throwaway git repos: `checks.mjs` resolves its
file list with `git ls-files` relative to the working directory, so pointing it
at a sandbox repo scopes the whole gate without stubbing anything.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKS = REPO_ROOT / "scripts" / "ci" / "checks.mjs"

# checks.mjs's own hard cap; a file past it must fail the gate outright.
HARD_LIMIT = 1200


def _repo(tmp_path: Path) -> Path:
    """A throwaway git repo — `git ls-files` is the gate's full-scan source."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _add(repo: Path, rel: str, lines: int) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"export const v{i} = {i};" for i in range(lines)))
    subprocess.run(["git", "add", rel], cwd=repo, check=True)


NODE = shutil.which("node")


def _run(repo: Path, *args: str, changed_files: str | None = None):
    # PATH inherited: node and git come from the mise-managed toolchain, not a
    # fixed system path. CHANGED_FILES is set explicitly per case so a value
    # leaking in from the surrounding lane cannot silently rescope the gate.
    env = {"PATH": os.environ["PATH"], "CHANGED_FILES": changed_files or ""}
    return subprocess.run(
        [NODE, str(CHECKS), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_the_full_scan_actually_scans(tmp_path: Path) -> None:
    """A full scan must look at the repo, not at an empty list.

    The regression: `explicitFileList()` read `process.argv` itself, so once the
    gates became subcommands of checks.mjs it picked up the subcommand NAME
    ("file-sizes") as an explicitly-scoped file. That list filtered to zero real
    paths, so every full scan took the explicit path over nothing and reported
    success — a green gate that had checked no files at all.
    """
    repo = _repo(tmp_path)
    _add(repo, "src/huge.ts", HARD_LIMIT + 50)

    process = _run(repo, "file-sizes")

    assert process.returncode == 1, f"gate passed over an oversized file\n{process.stdout}"
    assert "src/huge.ts" in process.stdout + process.stderr


def test_a_flag_does_not_switch_the_gate_to_explicit_mode(tmp_path: Path) -> None:
    # Same trap one step along: a bare `--quiet` must stay a flag. Counted as a
    # file it would filter to nothing and hand back the same vacuous green.
    repo = _repo(tmp_path)
    _add(repo, "src/huge.ts", HARD_LIMIT + 50)

    process = _run(repo, "file-sizes", "--quiet")

    assert process.returncode == 1, f"gate passed over an oversized file\n{process.stdout}"


def test_changed_files_still_scopes_the_scan(tmp_path: Path) -> None:
    # The other half of the contract: when a lane DOES name its files, the gate
    # must honour that and ignore everything else in the repo.
    repo = _repo(tmp_path)
    _add(repo, "src/huge.ts", HARD_LIMIT + 50)
    _add(repo, "src/small.ts", 10)

    process = _run(repo, "file-sizes", changed_files="src/small.ts")

    assert process.returncode == 0, process.stdout + process.stderr
    assert "src/huge.ts" not in process.stdout


def test_components_per_file_full_scan_reaches_the_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    components = "\n".join(f"export function Widget{i}() {{ return null; }}" for i in range(4))
    # One directory below the scanned root: the gate's full-scan pathspec is
    # `apps/web/src/**/*.tsx`, whose literal `/` after `**` needs a nested path.
    (repo / "apps/web/src/features").mkdir(parents=True)
    (repo / "apps/web/src/features/many.tsx").write_text(components)
    subprocess.run(["git", "add", "apps/web/src/features/many.tsx"], cwd=repo, check=True)

    process = _run(repo, "components-per-file")

    assert process.returncode == 1, f"gate passed over a 4-component file\n{process.stdout}"
    assert "apps/web/src/features/many.tsx" in process.stderr


def test_types_location_full_scan_reaches_the_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    types = "\n".join(f"export type T{i} = {{ a: number }};" for i in range(4))
    (repo / "apps/web/src").mkdir(parents=True)
    (repo / "apps/web/src/many.ts").write_text(types)
    subprocess.run(["git", "add", "apps/web/src/many.ts"], cwd=repo, check=True)

    process = _run(repo, "types-location", "--enforce")

    assert process.returncode == 1, f"gate passed over a 4-type file\n{process.stdout}"
    assert "apps/web/src/many.ts" in process.stdout


@pytest.mark.parametrize("sub", ["file-sizes", "components-per-file", "types-location"])
def test_an_unknown_subcommand_exits_two(tmp_path: Path, sub: str) -> None:
    # Guards the dispatch itself: a typo'd subcommand must be a hard error, not
    # a silent no-op that the lane would read as a pass.
    process = _run(_repo(tmp_path), f"{sub}-typo")

    assert process.returncode == 2
    assert "unknown subcommand" in process.stderr


# ---------------------------------------------------------------------------
# api-schema / api-schema-types
# ---------------------------------------------------------------------------

OPENAPI_JSON = "apps/api/openapi.json"
GENERATED_TYPES = "libs/shared/ts/src/api/generated/schema.d.ts"

# The two generators, faked: each writes what the test hands it through the
# environment, so a case decides whether regeneration reproduces the commit.
UV_STUB = """\
#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$REC/uv.log"
mkdir -p apps/api && printf '%s' "$FAKE_OPENAPI" > apps/api/openapi.json
"""
PNPM_STUB = """\
#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$REC/pnpm.log"
mkdir -p libs/shared/ts/src/api/generated
printf '%s' "$FAKE_TYPES" > libs/shared/ts/src/api/generated/schema.d.ts
"""


def _repo_beside_stubs(tmp_path: Path) -> Path:
    """The sandbox repo, apart from the stub bin dir the same tmp_path holds."""
    path = tmp_path / "repo"
    path.mkdir()
    return _repo(path)


def _commit(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", rel],
        cwd=repo,
        check=True,
    )


def _stub_generators(tmp_path: Path, openapi: str, types: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("uv", UV_STUB), ("pnpm", PNPM_STUB)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    rec = tmp_path / "rec"
    rec.mkdir()
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REC": str(rec),
        "FAKE_OPENAPI": openapi,
        "FAKE_TYPES": types,
        "CHANGED_FILES": "",
    }


def _run_env(repo: Path, env: dict[str, str], *args: str):
    return subprocess.run(
        [NODE, str(CHECKS), *args], cwd=repo, capture_output=True, text=True, check=False, env=env
    )


def test_api_schema_passes_when_regeneration_reproduces_the_commit(tmp_path: Path) -> None:
    repo = _repo_beside_stubs(tmp_path)
    _commit(repo, OPENAPI_JSON, '{"paths": {}}')
    _commit(repo, GENERATED_TYPES, "export interface paths {}\n")
    env = _stub_generators(tmp_path, '{"paths": {}}', "export interface paths {}\n")

    process = _run_env(repo, env, "api-schema")

    assert process.returncode == 0, process.stdout + process.stderr
    # Both generators ran — a check that diffed without regenerating passes vacuously.
    assert (tmp_path / "rec" / "uv.log").exists()
    assert (tmp_path / "rec" / "pnpm.log").exists()


def test_api_schema_fails_on_drift_with_the_one_line_fix(tmp_path: Path) -> None:
    repo = _repo_beside_stubs(tmp_path)
    _commit(repo, OPENAPI_JSON, '{"paths": {}}')
    _commit(repo, GENERATED_TYPES, "export interface paths {}\n")
    env = _stub_generators(
        tmp_path, '{"paths": {"/api/v1/new": {}}}', "export interface paths {}\n"
    )

    process = _run_env(repo, env, "api-schema")

    assert process.returncode == 1, "a stale openapi.json passed the drift gate"
    assert "API schema drifted — run `mise api:types` and commit" in process.stderr
    assert OPENAPI_JSON in process.stdout


def test_api_schema_write_regenerates_without_judging(tmp_path: Path) -> None:
    repo = _repo_beside_stubs(tmp_path)
    _commit(repo, OPENAPI_JSON, '{"paths": {}}')
    env = _stub_generators(tmp_path, '{"paths": {"/changed": {}}}', "// types\n")

    process = _run_env(repo, env, "api-schema", "--write")

    assert process.returncode == 0, process.stdout + process.stderr
    assert (repo / OPENAPI_JSON).read_text() == '{"paths": {"/changed": {}}}'


def _schema_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path)
    _commit(repo, OPENAPI_JSON, '{"components": {"schemas": {"TodoResponse": {}, "Todo": {}}}}')
    return repo


def test_a_hand_written_twin_of_a_schema_type_fails(tmp_path: Path) -> None:
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/types.ts",
        "export interface TodoResponse { id: string }\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 1, f"a hand-written TodoResponse passed\n{process.stdout}"
    assert "apps/web/src/features/todo/types.ts: TodoResponse" in process.stdout
    assert 'import type { TodoResponse } from "@gaia/shared/api/generated"' in process.stdout


def test_a_type_that_is_not_a_schema_name_is_fine(tmp_path: Path) -> None:
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/types.ts",
        "export interface TodoRowProps { id: string }\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_an_alias_onto_the_generated_type_is_not_a_twin(tmp_path: Path) -> None:
    # `type Todo = TodoResponse` names the generated type for a feature's
    # consumers; it has no fields of its own, so it cannot drift.
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/types.ts",
        'import type { TodoResponse } from "@shared/api/generated";\n'
        "export type TodoResponse = TodoResponse;\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_an_alias_of_an_imported_generated_binding_is_not_a_twin(tmp_path: Path) -> None:
    # A type-plus-const pair needs a local alias of a renamed import.
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/types.ts",
        'import type { TodoResponse as TodoRow } from "@shared/api/generated";\n'
        "export type TodoResponse = TodoRow;\n"
        'export const TodoResponse = { id: "" } as const satisfies TodoRow;\n',
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_an_alias_of_a_hand_written_type_is_a_twin(tmp_path: Path) -> None:
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/types.ts",
        "interface TodoRow { id: string }\nexport type TodoResponse = TodoRow;\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 1, process.stdout


def test_an_untyped_api_service_call_in_web_feature_code_fails(tmp_path: Path) -> None:
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/api/todoApi.ts",
        'import { apiService } from "@/lib/api/service";\n'
        'export const list = () => apiService.get<{ id: string }[]>("/todos");\n',
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 1, f"an untyped apiService call passed\n{process.stdout}"
    assert "apps/web/src/features/todo/api/todoApi.ts:1,2" in process.stdout
    assert '"@/lib/api/typed"' in process.stdout


def test_the_api_layer_itself_may_use_api_service(tmp_path: Path) -> None:
    # lib/api owns the request engine (the typed client and the shared todo
    # adapter are built on it); tests may mock it.
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/lib/api/typed.ts",
        'import { apiService } from "./service";\nexport const api = apiService;\n',
    )
    _add_text(
        repo,
        "apps/web/src/__tests__/todo.test.ts",
        'vi.mock("@/lib/api/service", () => ({ apiService: {} }));\n',
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_an_import_list_entry_is_not_a_declaration(tmp_path: Path) -> None:
    # `  type TodoResponse,` inside a multi-line `import type {...}` is a use,
    # not a declaration — the first version of the regex flagged it.
    repo = _schema_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/Row.tsx",
        'import {\n  type TodoResponse,\n  todoApi,\n} from "./api";\n\nexport const x = todoApi;\n',
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_the_generated_dir_is_exempt(tmp_path: Path) -> None:
    repo = _schema_repo(tmp_path)
    _add_text(repo, GENERATED_TYPES, "export interface TodoResponse { id: string }\n")
    _add_text(
        repo, "libs/shared/ts/src/api/generated/index.ts", "export type Todo = { id: string };\n"
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def _add_text(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
