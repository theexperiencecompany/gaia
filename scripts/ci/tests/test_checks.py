"""The file-walking hygiene gates (scripts/ci/checks.mjs).

These gates decide what gets scanned, and getting that wrong is invisible: a
scan over zero files prints "✓ All files within size limits" and exits 0, which
reads exactly like a clean repo. That is the failure this file exists to catch —
the lane cannot tell you it checked nothing, so a test has to.

Driven as the real script against throwaway git repos: `checks.mjs` resolves its
file list with `git ls-files` relative to the working directory, so pointing it
at a sandbox repo scopes the whole gate without stubbing anything.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKS = REPO_ROOT / "scripts" / "ci" / "checks.mjs"

# checks.mjs's own hard cap; a file past it must fail the gate outright.
HARD_LIMIT = 1200


def _repo(tmp_path: Path) -> Path:
    """Return a throwaway git repo — `git ls-files` is the gate's full-scan source."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _add(repo: Path, rel: str, lines: int) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"export const v{i} = {i};" for i in range(lines)))
    subprocess.run(["git", "add", rel], cwd=repo, check=True)


NODE = shutil.which("node")


def _run(
    repo: Path, *args: str, changed_files: str | None = None
) -> subprocess.CompletedProcess[str]:
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


def _add_source(repo: Path, rel: str, src: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src)
    subprocess.run(["git", "add", rel], cwd=repo, check=True)


def test_doc_comments_flags_a_narrating_jsdoc_and_an_in_function_banner(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    narration = "\n".join(f" * line {i}" for i in range(7))
    _add_source(
        repo,
        "src/a.ts",
        f"/**\n{narration}\n */\nexport function f() {{\n  // ---- Step 1 ----\n  return 1;\n}}\n",
    )

    process = _run(repo, "doc-comments")

    assert process.returncode == 1, process.stdout + process.stderr
    assert "src/a.ts:1  DS1" in process.stderr
    assert "src/a.ts:11  CM2" in process.stderr


def test_doc_comments_allows_file_headers_and_module_level_banners(tmp_path: Path) -> None:
    # The header block scripts/ci/CLAUDE.md requires, and the section banners
    # a registry file is made of, are the shape — not the slop.
    repo = _repo(tmp_path)
    header = "\n".join(f"// header line {i}" for i in range(10))
    _add_source(
        repo,
        "src/registry.ts",
        f"{header}\nexport const A = 1;\n// ---- Section two ----\nexport const B = 2;\n",
    )

    process = _run(repo, "doc-comments")

    assert process.returncode == 0, process.stdout + process.stderr


def test_doc_comments_flags_a_jsdoc_that_restates_its_declaration(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_source(repo, "src/b.ts", "/** The user id. */\nexport const userId = 1;\n")

    process = _run(repo, "doc-comments")

    assert process.returncode == 1
    assert "src/b.ts:1  DS5" in process.stderr


def test_doc_comments_reads_comments_not_strings_and_honours_a_shebang_header(
    tmp_path: Path,
) -> None:
    # A glob in a string ("src/**/*.tsx") once parsed as a 100-line JSDoc, and
    # a shebang line hid the header block the CI scripts are required to carry.
    repo = _repo(tmp_path)
    header = "\n".join(f" * header line {i}" for i in range(10))
    _add_source(
        repo,
        "scripts/tool.mjs",
        f'#!/usr/bin/env node\n/**\n{header}\n */\nimport {{ x }} from "./x.mjs";\n'
        'const globs = ["apps/web/src/**/*.tsx", "libs/**/*.ts"];\n'
        "const later = 1; // and a trailing comment */\n",
    )

    process = _run(repo, "doc-comments")

    assert process.returncode == 0, process.stdout + process.stderr


def test_doc_comments_skips_the_generated_agent_plugin(tmp_path: Path) -> None:
    # `entire enable` writes it and overwrites any edit on reinstall.
    repo = _repo(tmp_path)
    story = "\n".join(f"  // narrative line {i}" for i in range(6))
    body = f"export const x = 1;\nfunction f() {{\n{story}\n  return 1;\n}}\n"
    _add_source(repo, ".opencode/plugins/entire.ts", body)

    process = _run(repo, "doc-comments")

    assert process.returncode == 0, process.stdout + process.stderr


def test_doc_comments_changed_files_scopes_the_scan(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_source(repo, "src/bad.ts", "function f() {\n  // ==== Step 1 ====\n  return 1;\n}\n")
    _add_source(repo, "src/good.ts", "export const ok = 1;\n")

    process = _run(repo, "doc-comments", changed_files="src/good.ts")

    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.parametrize(
    "sub", ["file-sizes", "components-per-file", "types-location", "doc-comments"]
)
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
    """Return the sandbox repo, apart from the stub bin dir the same tmp_path holds."""
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
    # The api-schema check runs the codegen binary directly (it lives outside the
    # workspace); GAIA_OPENAPI_TS points it at this stub, which writes FAKE_TYPES
    # to whatever --output names.
    codegen = bin_dir / "openapi-typescript"
    codegen.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "$*" >> "$REC/codegen.log"
            out=""
            while [[ $# -gt 0 ]]; do
              case "$1" in
                --output) out="$2"; shift ;;
              esac
              shift
            done
            mkdir -p "$(dirname "$out")"
            printf '%s' "$FAKE_TYPES" > "$out"
            """
        )
    )
    codegen.chmod(0o755)
    rec = tmp_path / "rec"
    rec.mkdir()
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REC": str(rec),
        "FAKE_OPENAPI": openapi,
        "FAKE_TYPES": types,
        "CHANGED_FILES": "",
        "GAIA_OPENAPI_TS": str(bin_dir / "openapi-typescript"),
    }


def _run_env(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
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
    assert (tmp_path / "rec" / "codegen.log").exists()


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


# ---------------------------------------------------------------------------
# api-schema-types: the API-type directories, the shape twins, the baselines
# ---------------------------------------------------------------------------

# Properties, not just names: the shape rule compares field SETS, so a schema
# with no `properties` cannot be twinned by anything.
SHAPE_OPENAPI = (
    '{"components": {"schemas": {"TodoResponse": {"properties": '
    '{"id": {}, "created_at": {}, "is_done": {}}}}}}'
)


def _shape_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path)
    _commit(repo, OPENAPI_JSON, SHAPE_OPENAPI)
    return repo


def _baseline(repo: Path, name: str, lines: str) -> None:
    _add_text(repo, f"scripts/ci/baselines/{name}", lines)


def test_a_declaration_in_an_api_type_directory_is_banned_whatever_it_is_called(
    tmp_path: Path,
) -> None:
    # The name gate misses it (TodoRow is no schema's name) and so does the
    # shape gate (one field). The directory is what makes it a twin.
    repo = _shape_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/api/todoApi.ts",
        "export interface TodoRow { id: string }\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 1, f"a hand-declared type in an api/ dir passed\n{process.stdout}"
    assert "apps/web/src/features/todo/api/todoApi.ts:TodoRow" in process.stdout


def test_a_re_export_in_an_api_type_directory_is_allowed(tmp_path: Path) -> None:
    repo = _shape_repo(tmp_path)
    _add_text(
        repo,
        "apps/mobile/src/features/todo/api/todo-api.ts",
        'export type { TodoResponse } from "@gaia/shared/api/generated";\n',
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_an_alias_of_a_generated_name_in_an_api_type_directory_is_allowed(
    tmp_path: Path,
) -> None:
    repo = _shape_repo(tmp_path)
    _add_text(
        repo,
        "libs/shared/ts/src/types/todo.ts",
        'import type { TodoResponse } from "../api/generated";\nexport type Todo = TodoResponse;\n',
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_a_baselined_declaration_does_not_fail_and_a_stale_line_does_not_either(
    tmp_path: Path,
) -> None:
    # The ratchet: a known violation passes, and emptying the baseline must not
    # red the PR that empties it — the stale line is reported, not failed.
    repo = _shape_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/features/todo/api/todoApi.ts",
        "export interface TodoRow { id: string }\n",
    )
    _baseline(
        repo,
        "api-declared-types.txt",
        "# known\napps/web/src/features/todo/api/todoApi.ts:TodoRow\n"
        "apps/web/src/features/todo/api/todoApi.ts:AlreadyFixed\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout
    assert "AlreadyFixed" in process.stdout, "a stale baseline line was not reported"


def test_a_type_with_a_schemas_fields_under_another_name_is_a_twin(
    tmp_path: Path,
) -> None:
    # Renamed AND re-cased: `created_at` and `createdAt` are one field.
    repo = _shape_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/components/TodoCard.tsx",
        "export interface TodoCardModel {\n"
        "  id: string;\n"
        "  createdAt: string;\n"
        "  isDone: boolean;\n"
        "}\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 1, f"a renamed twin passed\n{process.stdout}"
    assert "apps/web/src/components/TodoCard.tsx:TodoCardModel=TodoResponse" in process.stdout


def test_a_type_that_shares_too_few_fields_is_not_a_twin(tmp_path: Path) -> None:
    repo = _shape_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/components/TodoCard.tsx",
        "export interface TodoCardProps {\n"
        "  id: string;\n"
        "  onToggle: () => void;\n"
        "  className: string;\n"
        "}\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 0, process.stdout


def test_a_hand_written_d_ts_is_scanned(tmp_path: Path) -> None:
    # `.d.ts` is in the size gates' global ignore list. This gate must not
    # inherit it: the generated file is exempt by path, so every other `.d.ts`
    # is hand-written and drifts exactly like a `.ts`.
    repo = _shape_repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/types/legacy.d.ts",
        "export interface TodoResponse { id: string }\n",
    )

    process = _run(repo, "api-schema-types")

    assert process.returncode == 1, f"a twin in a .d.ts passed\n{process.stdout}"
    assert "apps/web/src/types/legacy.d.ts: TodoResponse" in process.stdout


# ---------------------------------------------------------------------------
# api-client-imports
# ---------------------------------------------------------------------------


def test_a_raw_mobile_api_client_import_fails(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        "apps/mobile/src/features/todo/api/todo-api.ts",
        'import { apiService } from "@/lib/api";\n'
        'export const list = () => apiService.get("/todos");\n',
    )

    process = _run(repo, "api-client-imports")

    assert process.returncode == 1, f"a raw client import passed\n{process.stdout}"
    assert "apps/mobile/src/features/todo/api/todo-api.ts:1" in process.stdout


def test_a_relative_import_of_the_raw_mobile_client_fails_too(tmp_path: Path) -> None:
    # Import STATEMENTS, not an identifier grep: the relative spelling reaches
    # the same module and must be caught the same way.
    repo = _repo(tmp_path)
    _add_text(
        repo,
        "apps/mobile/src/features/todo/api/todo-api.ts",
        'import { apiService } from "../../../lib/api";\nexport const x = apiService;\n',
    )

    process = _run(repo, "api-client-imports")

    assert process.returncode == 1, process.stdout


def test_a_mention_of_api_service_that_is_not_an_import_is_not_a_violation(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        "apps/mobile/src/features/todo/api/todo-api.ts",
        "// apiService is the raw client; this module must not reach it.\n"
        "const apiService = null;\nexport const x = apiService;\n",
    )

    process = _run(repo, "api-client-imports")

    assert process.returncode == 0, process.stdout


def test_the_mobile_api_lib_may_import_itself(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        "apps/mobile/src/lib/query-provider.ts",
        'import { apiService } from "./api";\nexport const x = apiService;\n',
    )

    process = _run(repo, "api-client-imports")

    assert process.returncode == 0, process.stdout


def test_a_baselined_raw_client_import_does_not_fail(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        "apps/mobile/src/features/todo/api/todo-api.ts",
        'import { apiService } from "@/lib/api";\nexport const x = apiService;\n',
    )
    _baseline(
        repo,
        "mobile-api-client-imports.txt",
        "apps/mobile/src/features/todo/api/todo-api.ts\n",
    )

    process = _run(repo, "api-client-imports")

    assert process.returncode == 0, process.stdout


# ---------------------------------------------------------------------------
# bot-handles: one canonical handle per platform, every spoken-of link agrees
# ---------------------------------------------------------------------------

BOT_HANDLES_SOURCE = "libs/shared/bot-identity.json"
WHATSAPP = "12038429512"
TELEGRAM = "heygaia_bot"
DISCORD = "puRWnQ7hV5"


def _handles_repo(
    tmp_path: Path,
    whatsapp: str = WHATSAPP,
    telegram: str = TELEGRAM,
    discord: str = DISCORD,
) -> Path:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        BOT_HANDLES_SOURCE,
        json.dumps(
            {
                "whatsappNumber": whatsapp,
                "telegramUsername": telegram,
                "discordInviteCode": discord,
                "discordCommunityUrl": "https://discord.heygaia.io",
            }
        ),
    )
    return repo


def test_matching_links_pass(tmp_path: Path) -> None:
    repo = _handles_repo(tmp_path)
    _add_text(repo, "README.md", "[WhatsApp](https://wa.me/12038429512)\n")
    _add_text(repo, "docs/telegram.mdx", "[Telegram](https://t.me/heygaia_bot)\n")
    _add_text(repo, "docs/GAIA.md", "[Discord](https://discord.com/invite/puRWnQ7hV5)\n")

    process = _run(repo, "bot-handles")

    assert process.returncode == 0, process.stderr


def test_a_stale_whatsapp_link_fails_and_names_the_file(tmp_path: Path) -> None:
    repo = _handles_repo(tmp_path)
    _add_text(repo, "docs/quick-start.mdx", "[WhatsApp](https://wa.me/12762088737)\n")

    process = _run(repo, "bot-handles")

    assert process.returncode == 1
    assert "docs/quick-start.mdx" in process.stderr
    assert "12762088737" in process.stderr


def test_a_stale_telegram_username_fails(tmp_path: Path) -> None:
    repo = _handles_repo(tmp_path)
    _add_text(repo, "README.md", "[Telegram](https://t.me/some_other_bot)\n")

    process = _run(repo, "bot-handles")

    assert process.returncode == 1
    assert "some_other_bot" in process.stderr


def test_a_stale_discord_invite_fails(tmp_path: Path) -> None:
    repo = _handles_repo(tmp_path)
    _add_text(repo, "libs/help.ts", 'url: "https://discord.gg/gaia"\n')

    process = _run(repo, "bot-handles")

    assert process.returncode == 1
    assert "gaia" in process.stderr


def test_telegram_usernames_compare_case_insensitively(tmp_path: Path) -> None:
    repo = _handles_repo(tmp_path)
    _add_text(repo, "README.md", "[Telegram](https://t.me/HeyGaia_Bot)\n")

    process = _run(repo, "bot-handles")

    assert process.returncode == 0, process.stderr


def test_changing_a_canonical_handle_flags_every_copy(tmp_path: Path) -> None:
    repo = _handles_repo(tmp_path)
    _add_text(repo, "README.md", "[Telegram](https://t.me/heygaia_bot)\n")
    _add_text(
        repo,
        BOT_HANDLES_SOURCE,
        json.dumps(
            {
                "whatsappNumber": WHATSAPP,
                "telegramUsername": "other_bot",
                "discordInviteCode": DISCORD,
                "discordCommunityUrl": "https://discord.heygaia.io",
            }
        ),
    )

    process = _run(repo, "bot-handles")

    assert process.returncode == 1
    assert "README.md" in process.stderr


def test_api_test_fixtures_are_not_treated_as_links(tmp_path: Path) -> None:
    repo = _handles_repo(tmp_path)
    _add_text(
        repo,
        "apps/api/tests/unit/services/test_platform_link_service.py",
        'assert result == "https://wa.me/15551234567"\n',
    )

    process = _run(repo, "bot-handles")

    assert process.returncode == 0, process.stderr


def test_a_missing_canonical_handle_fails_loudly(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(repo, "README.md", "[Telegram](https://t.me/heygaia_bot)\n")

    process = _run(repo, "bot-handles")

    assert process.returncode == 1
    assert BOT_HANDLES_SOURCE in process.stderr


# ---------------------------------------------------------------------------
# heroui-style-overrides: the design system owns a HeroUI component's look
# ---------------------------------------------------------------------------

HERO_FILE = "apps/web/src/features/demo/Card.tsx"


def _hero_component(jsx: str, imports: str = "Button, Chip, Modal") -> str:
    return f'import {{ {imports} }} from "@heroui/react";\n\nexport function Demo() {{\n  return {jsx};\n}}\n'


@pytest.mark.parametrize(
    ("jsx", "entry"),
    [
        ('<Button className="bg-zinc-800">x</Button>', "Button:bg-zinc-800"),
        ('<Button className="hover:text-zinc-400">x</Button>', "Button:hover:text-zinc-400"),
        ('<Chip className="border-zinc-700">x</Chip>', "Chip:border-zinc-700"),
        ('<Chip className="border-t-red-500">x</Chip>', "Chip:border-t-red-500"),
        ('<Chip className="rounded-full">x</Chip>', "Chip:rounded-full"),
        ('<Chip className="!px-2">x</Chip>', "Chip:!px-2"),
        ('<Modal.Body className="p-0">x</Modal.Body>', "Modal.Body:p-0"),
        (
            '<Button className={cn("w-full", open && "bg-[#00bbff]")}>x</Button>',
            "Button:bg-[#00bbff]",
        ),
        ('<Button className={`w-full ${a ? "rounded-xl" : ""}`}>x</Button>', "Button:rounded-xl"),
        ("<Button style={{ borderRadius: 8 }}>x</Button>", "Button:style.borderRadius"),
        ("<Button style={{ color: 'red' }}>x</Button>", "Button:style.color"),
        (
            '<Chip className={toneVariants({ tone: "muted", className: "bg-zinc-800" })}>x</Chip>',
            "Chip:bg-zinc-800",
        ),
    ],
)
def test_a_heroui_style_override_fails(tmp_path: Path, jsx: str, entry: str) -> None:
    repo = _repo(tmp_path)
    _add_text(repo, HERO_FILE, _hero_component(jsx))

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 1, f"{jsx} passed\n{process.stdout}"
    assert f"{HERO_FILE}:{entry}" in process.stdout


@pytest.mark.parametrize(
    "source",
    [
        'const CARD = "w-full bg-zinc-800";\n\nexport const Demo = () => <Modal.Body className={CARD} />;\n',
        'const STYLES = { body: "bg-zinc-800" };\n\nexport const Demo = () => <Modal.Body className={STYLES.body} />;\n',
        'const CARD = "bg-zinc-800";\n\nexport const Demo = () => <Modal.Body className={`w-full ${CARD}`} />;\n',
        'import { CARD } from "./styles";\n\nexport const Demo = () => <Modal.Body className={CARD} />;\n',
    ],
)
def test_a_heroui_override_held_in_a_constant_fails(tmp_path: Path, source: str) -> None:
    repo = _repo(tmp_path)
    _add_text(repo, "apps/web/src/features/demo/styles.ts", 'export const CARD = "bg-zinc-800";\n')
    _add_text(repo, HERO_FILE, 'import { Modal } from "@heroui/react";\n' + source)

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 1, process.stdout
    assert f"{HERO_FILE}:Modal.Body:bg-zinc-800" in process.stdout


def test_a_variant_slot_call_is_not_an_override(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        HERO_FILE,
        'import { Tabs } from "@heroui/react";\n'
        'import { tabsVariants } from "@/components/shared/tabsVariants";\n\n'
        'const tabs = tabsVariants({ variant: "solid" });\n\n'
        'export const Demo = () => <Tabs.List className={tabs.tabList({ className: "w-full" })} />;\n',
    )

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 0, process.stdout


def test_an_aliased_heroui_import_is_still_checked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        HERO_FILE,
        _hero_component(
            '<HeroButton className="rounded-lg">x</HeroButton>', "Button as HeroButton"
        ),
    )

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 1, process.stdout
    assert f"{HERO_FILE}:Button:rounded-lg" in process.stdout


WRAPPER_FILE = "apps/web/src/components/shared/GaiaThing.tsx"


@pytest.mark.parametrize(
    "wrapper",
    [
        "export function GaiaThing({ className, ...props }) {\n"
        "  return <Button className={shapeVariants({ className })} {...props} />;\n}\n",
        "export function GaiaThing(props) {\n  return <Chip {...props} />;\n}\n",
        "export function GaiaThing({ className }) {\n"
        "  return <NextLink className={buttonVariants({ className })} />;\n}\n",
    ],
)
def test_a_gaia_wrapper_is_checked_like_heroui(tmp_path: Path, wrapper: str) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        WRAPPER_FILE,
        'import { Button, Chip } from "@heroui/react";\n'
        'import { buttonVariants } from "./buttonVariants";\n'
        'import { shapeVariants } from "./shape";\n' + wrapper,
    )
    _add_text(
        repo,
        HERO_FILE,
        'import { GaiaThing } from "@/components/shared/GaiaThing";\n\n'
        'export const Demo = () => <GaiaThing className="text-zinc-300 w-full" />;\n',
    )

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 1, process.stdout
    assert f"{HERO_FILE}:GaiaThing:text-zinc-300" in process.stdout
    assert "GaiaThing:w-full" not in process.stdout


def test_a_shared_component_that_keeps_its_classname_is_not_a_wrapper(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        WRAPPER_FILE,
        'import { Button } from "@heroui/react";\n'
        "export function GaiaThing({ className }) {\n"
        '  return <div className={className}><Button variant="ghost">x</Button></div>;\n}\n',
    )
    _add_text(
        repo,
        HERO_FILE,
        'import { GaiaThing } from "@/components/shared/GaiaThing";\n\n'
        'export const Demo = () => <GaiaThing className="bg-zinc-800" />;\n',
    )

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 0, process.stdout


@pytest.mark.parametrize(
    "jsx",
    [
        '<Button className="w-full h-10 min-w-0 max-w-sm mt-2 flex grid gap-2 order-1 self-end justify-between items-center">x</Button>',
        '<Chip className="text-sm border border-2 border-dashed">x</Chip>',
        "<Button style={{ width: 20, marginTop: 4 }}>x</Button>",
        '<div className="bg-zinc-800 rounded-xl p-4">x</div>',
    ],
)
def test_layout_and_non_heroui_elements_pass(tmp_path: Path, jsx: str) -> None:
    repo = _repo(tmp_path)
    _add_text(repo, HERO_FILE, _hero_component(jsx))

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 0, process.stdout


def test_a_component_not_from_heroui_is_not_checked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        HERO_FILE,
        'import { Button } from "@/components/ui/button";\n\n'
        'export const Demo = () => <Button className="bg-zinc-800 rounded-xl">x</Button>;\n',
    )

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 0, process.stdout


def test_the_sanctioned_variant_files_may_style_heroui(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/components/shared/GaiaButton.tsx",
        _hero_component('<Button className="bg-zinc-700 rounded-full">x</Button>'),
    )

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 0, process.stdout


def test_a_baselined_heroui_override_passes_and_a_stale_line_is_only_reported(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _add_text(repo, HERO_FILE, _hero_component('<Chip className="bg-[#00bbff]/15">x</Chip>'))
    stale = "apps/web/src/features/gone/Old.tsx:Button:rounded-xl"
    _add_text(
        repo,
        "scripts/ci/baselines/heroui-style-overrides.txt",
        f"# header\n{HERO_FILE}:Chip:bg-[#00bbff]/15\n{stale}\n",
    )

    process = _run(repo, "heroui-style-overrides")

    assert process.returncode == 0, process.stdout
    assert stale in process.stdout


# ---------------------------------------------------------------------------
# heroui-usage: v3 APIs only, controls with their parts, GAIA wrappers over bare HeroUI
# ---------------------------------------------------------------------------

V2_VARIANT_NAMES = [
    "flat",
    "light",
    "bordered",
    "faded",
    "solid",
    "shadow",
    "underlined",
    "splitted",
]


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('import { Button } from "@heroui/button";\n', "import from @heroui/button"),
        ('import { cn } from "@heroui/theme";\n', "import from @heroui/theme"),
        ('import { useDisclosure } from "@heroui/react";\n', "useDisclosure from @heroui"),
        ('import { HeroUIProvider } from "@heroui/system";\n', "HeroUIProvider from @heroui"),
        (_hero_component("<Chip classNames={{ base: 'x' }}>x</Chip>"), "<Chip classNames>"),
        (_hero_component('<Chip labelPlacement="outside">x</Chip>'), "<Chip labelPlacement>"),
        (
            _hero_component('<Modal.Dialog variant={open ? "underlined" : "primary"} />'),
            'variant="underlined"',
        ),
        (_hero_component("<Button>x</Button>"), "<Button>: use GaiaButton"),
        (_hero_component("<Select.Value />", "Select"), "<Select.Value>: use GaiaSelectValue"),
        (
            _hero_component('<ListBox.Item id="a">a</ListBox.Item>', "ListBox"),
            "<ListBox.Item>: use GaiaListBoxItem",
        ),
        (
            _hero_component("<Switch isSelected />", "Switch"),
            "<Switch />: render its Switch.Control",
        ),
        (_hero_component("<Checkbox />", "Checkbox"), "<Checkbox />: render its Checkbox.Control"),
        (
            _hero_component(
                '<Table.Header><Table.Column id="a">A</Table.Column></Table.Header>', "Table"
            ),
            "<Table.Column>: mark one column isRowHeader",
        ),
        (
            'import { GaiaButton } from "@/components/shared/GaiaButton";\n\n'
            "export const Demo = () => <GaiaButton isIconOnly><svg /></GaiaButton>;\n",
            "isIconOnly button without aria-label",
        ),
        (_hero_component("<B />", "Button as B"), "<Button>: use GaiaButton"),
        (
            _hero_component(
                '<Accordion.Panel className="py-2 text-sm">x</Accordion.Panel>', "Accordion"
            ),
            '<Accordion.Panel className="py-2">: it keeps this when collapsed',
        ),
        *[
            (_hero_component(f'<Chip variant="{v}">x</Chip>'), f'<Chip variant="{v}">')
            for v in V2_VARIANT_NAMES
        ],
    ],
)
def test_a_heroui_usage_error_fails(tmp_path: Path, source: str, message: str) -> None:
    repo = _repo(tmp_path)
    _add_text(repo, HERO_FILE, source)

    process = _run(repo, "heroui-usage")

    assert process.returncode == 1, f"{source} passed\n{process.stdout}"
    assert message in process.stdout


@pytest.mark.parametrize(
    "button_prop",
    [
        "isLoading",
        "onClick={go}",
        "startContent={<i />}",
        "endContent={<i />}",
        'radius="full"',
        'color="primary"',
    ],
)
def test_a_v2_button_prop_fails_even_inside_gaia_button(tmp_path: Path, button_prop: str) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        "apps/web/src/components/shared/GaiaButton.tsx",
        _hero_component(f"<Button {button_prop}>x</Button>", "Button"),
    )

    process = _run(repo, "heroui-usage")

    assert process.returncode == 1, process.stdout
    assert f"<Button {button_prop.split('=')[0]}>" in process.stdout
    assert "use GaiaButton" not in process.stdout


def test_v3_usage_and_each_wrapper_in_its_own_file_pass(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _add_text(
        repo,
        HERO_FILE,
        'import { Accordion, Chip, Switch } from "@heroui/react";\n'
        'import { buttonVariants } from "@heroui/styles";\n'
        'import { GaiaButton } from "@/components/shared/GaiaButton";\n'
        "export const A = () => (\n"
        '  <GaiaButton variant="primary" isPending onPress={go}>x</GaiaButton>\n'
        '  <Chip variant="soft" color="accent">x</Chip>\n'
        "  <Switch><Switch.Control><Switch.Thumb /></Switch.Control></Switch>\n"
        '  <Accordion.Panel className="text-sm"><div className="py-2">x</div></Accordion.Panel>\n'
        '  <button onClick={go} color="red" type="button" />\n'
        ");\n",
    )
    _add_text(
        repo,
        "apps/web/src/components/shared/GaiaListBoxItem.tsx",
        _hero_component("<ListBox.Item>x<ListBox.ItemIndicator /></ListBox.Item>", "ListBox"),
    )

    process = _run(repo, "heroui-usage")

    assert process.returncode == 0, process.stdout
