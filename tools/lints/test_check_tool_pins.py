"""The pin-skew guard must pass on the real tree and fail on drift.

The fixture-based tests point the module's path constants at tmp files via
monkeypatch (``PRE_COMMIT`` / ``CODE_QUALITY``), then drive
``main()`` end to end: consistent pins return rc 0, and a pin deleted from
its invocation but still mentioned in a comment returns rc 1 naming the
tool. A mention in a comment is prose, not a pin — it can never satisfy the
guard.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_tool_pins
import pytest

PRE_COMMIT_YAML = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.14.13
    hooks:
      - id: ruff
  - repo: local
    hooks:
      - id: bandit
        entry: bash -c "uvx --no-build bandit@1.9.4 -r app"
      - id: pip-audit
        entry: bash -c "uv export --frozen | uvx --no-build pip-audit@2.10.1"
      - id: gaia-mypy
        entry: bash -c 'uvx --no-build mypy@1.19.1 "$@"' --
"""

CODE_QUALITY_YML = """\
jobs:
  python-ruff:
    steps:
      - name: Ruff lint
        run: |
          uvx --no-build ruff@0.14.13 check .
  python-interrogate:
    steps:
      - name: Docstring coverage
        run: |
          uvx interrogate==1.7.0 -c pyproject.toml apps/api
  python-xenon:
    steps:
      - name: Complexity scan
        run: |
          uvx xenon==0.9.3 --max-absolute F apps/api
  python-bandit:
    steps:
      - name: Bandit security scan
        run: |
          uvx --no-build bandit@1.9.4 -c pyproject.toml -r apps/api/app
  python-pip-audit:
    steps:
      - name: pip-audit
        run: |
          uvx --no-build pip-audit==2.10.1 --strict
"""


UV_LOCK_TOML = """\
[[package]]
name = "mypy"
version = "1.19.1"

[[package]]
name = "ruff"
version = "0.14.13"
"""


@pytest.fixture
def pinned_surfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Fixture surfaces carrying every EXPECTED pin, as module constants."""
    files = {
        "PRE_COMMIT": tmp_path / "pre-commit-config.yaml",
        "CODE_QUALITY": tmp_path / "code-quality.yml",
        "UV_LOCK": tmp_path / "uv.lock",
    }
    files["PRE_COMMIT"].write_text(PRE_COMMIT_YAML, encoding="utf-8")
    files["CODE_QUALITY"].write_text(CODE_QUALITY_YML, encoding="utf-8")
    files["UV_LOCK"].write_text(UV_LOCK_TOML, encoding="utf-8")
    for name, path in files.items():
        monkeypatch.setattr(check_tool_pins, name, path)
    return files


def _run(capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    rc = check_tool_pins.main([])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_real_tree_is_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["python3", "tools/lints/check_tool_pins.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_consistent_pins_return_0(
    pinned_surfaces: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    # The patched files must be what the guard read — without this, a broken
    # monkeypatch would silently pass against the real tree instead.
    assert all(path.exists() for path in pinned_surfaces.values())
    rc, out, err = _run(capsys)
    assert rc == 0, err
    assert "OK" in out


def test_deleted_pin_mentioned_in_comment_fails(
    pinned_surfaces: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The real pin is gone; only the comment still names it.

    The old whole-file substring search was satisfied by that comment alone —
    this is the spoof that must fail.
    """
    pinned_surfaces["CODE_QUALITY"].write_text(
        CODE_QUALITY_YML.replace(
            "uvx --no-build ruff@0.14.13 check .",
            "          # uvx --no-build ruff@0.14.13 check .",
        ),
        encoding="utf-8",
    )
    rc, out, err = _run(capsys)
    assert rc == 1
    assert "ruff is not pinned to 0.14.13" in err
    assert "code-quality.yml" in err
    assert "1 unpinned tool invocation" in err


@pytest.mark.parametrize(
    "run_block",
    [
        # A full-line comment names the pin; the invocation itself is unpinned.
        "          # ruff@0.14.13\n          uvx --no-build ruff check .",
        # The only mention rides a trailing comment on an unpinned invocation.
        "          uvx --no-build ruff check .  # ruff@0.14.13",
    ],
)
def test_comment_only_mention_never_satisfies(
    pinned_surfaces: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    run_block: str,
) -> None:
    pinned_surfaces["CODE_QUALITY"].write_text(
        CODE_QUALITY_YML.replace("          uvx --no-build ruff@0.14.13 check .", run_block),
        encoding="utf-8",
    )
    rc, out, err = _run(capsys)
    assert rc == 1
    assert "ruff is not pinned to 0.14.13" in err


def test_real_pin_with_trailing_comment_still_counts(
    pinned_surfaces: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Cutting each line at its first ``#`` must not discard a genuine pin."""
    pinned_surfaces["CODE_QUALITY"].write_text(
        CODE_QUALITY_YML.replace(
            "uvx --no-build ruff@0.14.13 check .",
            "uvx --no-build ruff@0.14.13 check .  # pinned — bump with EXPECTED",
        ),
        encoding="utf-8",
    )
    rc, out, err = _run(capsys)
    assert rc == 0, err


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("  '@biomejs/biome@2.5.7':\n    resolution: {}", True),
        (
            "  '@biomejs/biome@2.5.6':\n    resolution: {}",
            False,
        ),  # the lockfile resolved another release
        ('{"$schema": "https://biomejs.dev/schemas/2.5.7/schema.json"}', True),
        ('{"$schema": "https://biomejs.dev/schemas/2.5.6/schema.json"}', False),
    ],
)
def test_biome_pin_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
    ok: bool,
) -> None:
    """A lockfile resolving another release and a stale $schema both drift."""
    surface = tmp_path / "biome-surface.json"
    surface.write_text(text, encoding="utf-8")
    monkeypatch.setattr(check_tool_pins, "PNPM_LOCK", surface)
    monkeypatch.setattr(check_tool_pins, "BIOME_CONFIGS", ())
    rc, _out, err = _run(capsys)
    assert (rc == 0) is ok, err
    assert ("biome is not pinned to 2.5.7" in err) is not ok


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ('[tools]\nuv = "0.12.23"\n', True),
        ('[tools]\nuv = "latest"\n', False),
        ("COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/\n", True),
        ("COPY --from=ghcr.io/astral-sh/uv:0.11.0 /uv /uvx /bin/\n", False),
        ('inputs:\n  version:\n    default: "0.12.23"\n', True),
    ],
)
def test_uv_pin_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
    ok: bool,
) -> None:
    """A local uv on "latest" or another release drifts from the uv CI locks with."""
    surface = tmp_path / "uv-surface"
    surface.write_text(text, encoding="utf-8")
    monkeypatch.setattr(check_tool_pins, "ROOT_MISE", surface)
    monkeypatch.setattr(check_tool_pins, "SETUP_UV", surface)
    monkeypatch.setattr(check_tool_pins, "UV_DOCKERFILES", ())
    # mise.toml also carries ruff's pin, so only uv's verdict is this test's to judge.
    _rc, _out, err = _run(capsys)
    assert ("uv is not pinned to 0.12.23" in err) is not ok


@pytest.mark.parametrize(
    ("content", "ok"),
    [
        ("24.22.1\n", True),
        # A bare major is the shape that drifted: it resolves to whatever the
        # registry serves, so local and CI disagree with no commit to blame.
        ("24\n", False),
        ("v24.22.1\n", False),
        ("", False),
    ],
)
def test_node_version_file_must_be_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: str,
    ok: bool,
) -> None:
    """.node-version is the one declaration, so it must hold one exact version."""
    version_file = tmp_path / ".node-version"
    version_file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(check_tool_pins, "NODE_VERSION_FILE", version_file)
    monkeypatch.setattr(check_tool_pins, "NODE_FILE_REFERENCE_SURFACES", ())
    monkeypatch.setattr(check_tool_pins, "NODE_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "NODE_DOCKERFILES", ())
    monkeypatch.setattr(check_tool_pins, "NODE_LITERAL_SCAN", ())
    _rc, _out, err = _run(capsys)
    assert (".node-version is missing or is not a bare x.y.z version" in err) is not ok


def test_node_hardcoded_literal_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A second declaration anywhere in the scanned set is a failure."""
    version_file = tmp_path / ".node-version"
    version_file.write_text("24.22.1\n", encoding="utf-8")
    stray = tmp_path / "mise.toml"
    stray.write_text('[tools]\nnode = "22"\n', encoding="utf-8")
    monkeypatch.setattr(check_tool_pins, "NODE_VERSION_FILE", version_file)
    monkeypatch.setattr(check_tool_pins, "NODE_FILE_REFERENCE_SURFACES", ())
    monkeypatch.setattr(check_tool_pins, "NODE_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "NODE_DOCKERFILES", ())
    monkeypatch.setattr(check_tool_pins, "NODE_LITERAL_SCAN", ("**/mise.toml",))
    monkeypatch.setattr(check_tool_pins, "REPO_ROOT", tmp_path)
    _rc, _out, err = _run(capsys)
    assert "hardcodes a node version" in err
    assert 'node = "22"' in err


def test_node_dockerfile_arg_must_mirror_the_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Docker cannot read a file in FROM, so its one default must still match."""
    version_file = tmp_path / ".node-version"
    version_file.write_text("24.22.1\n", encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG NODE_VERSION=24.21.0\nFROM node:${NODE_VERSION}-alpine\n", encoding="utf-8"
    )
    monkeypatch.setattr(check_tool_pins, "NODE_VERSION_FILE", version_file)
    monkeypatch.setattr(check_tool_pins, "NODE_FILE_REFERENCE_SURFACES", ())
    monkeypatch.setattr(
        check_tool_pins,
        "NODE_MIRRORS",
        ((dockerfile, r"^ARG\s+NODE_VERSION=(\d+\.\d+\.\d+)\s*$"),),
    )
    monkeypatch.setattr(check_tool_pins, "NODE_DOCKERFILES", (dockerfile,))
    monkeypatch.setattr(check_tool_pins, "NODE_LITERAL_SCAN", ())
    _rc, _out, err = _run(capsys)
    assert "mirrors node 24.21.0, .node-version is 24.22.1" in err


def test_node_second_stage_hardcode_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A parameterised base stage must not excuse a hardcoded runner stage."""
    version_file = tmp_path / ".node-version"
    version_file.write_text("24.22.1\n", encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG NODE_VERSION=24.22.1\n"
        "FROM node:${NODE_VERSION}-alpine AS base\n"
        "FROM node:24-alpine AS runner\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_tool_pins, "NODE_VERSION_FILE", version_file)
    monkeypatch.setattr(check_tool_pins, "NODE_FILE_REFERENCE_SURFACES", ())
    monkeypatch.setattr(
        check_tool_pins,
        "NODE_MIRRORS",
        ((dockerfile, r"^ARG\s+NODE_VERSION=(\d+\.\d+\.\d+)\s*$"),),
    )
    monkeypatch.setattr(check_tool_pins, "NODE_DOCKERFILES", (dockerfile,))
    monkeypatch.setattr(check_tool_pins, "NODE_LITERAL_SCAN", ())
    _rc, _out, err = _run(capsys)
    assert "hardcodes a node version outside the mirror" in err


def test_node_reference_surface_must_read_the_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Restating the version in a workflow is the drift being designed out."""
    version_file = tmp_path / ".node-version"
    version_file.write_text("24.22.1\n", encoding="utf-8")
    surface = tmp_path / "action.yml"
    surface.write_text('node-version: "24.22.1"\n', encoding="utf-8")
    monkeypatch.setattr(check_tool_pins, "NODE_VERSION_FILE", version_file)
    monkeypatch.setattr(check_tool_pins, "NODE_FILE_REFERENCE_SURFACES", (surface,))
    monkeypatch.setattr(check_tool_pins, "NODE_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "NODE_DOCKERFILES", ())
    monkeypatch.setattr(check_tool_pins, "NODE_LITERAL_SCAN", ())
    _rc, _out, err = _run(capsys)
    assert "does not read the node version from .node-version" in err


def test_eas_cli_must_match_mise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """eas.json refuses a CLI that mise does not install, so the two must agree."""
    mise = tmp_path / "mise.toml"
    mise.write_text('[tools]\n"npm:eas-cli" = "25.3.0"\n', encoding="utf-8")
    eas = tmp_path / "eas.json"
    eas.write_text('{"cli": {"version": "16.28.0"}}', encoding="utf-8")
    monkeypatch.setattr(check_tool_pins, "ROOT_MISE", mise)
    monkeypatch.setattr(check_tool_pins, "EAS_JSON", eas)
    monkeypatch.setattr(check_tool_pins, "PYTHON_VERSION_FILE", tmp_path / "absent")
    monkeypatch.setattr(check_tool_pins, "PYTHON_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "RUST_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "RUNTIME_SCAN", ())
    _rc, _out, err = _run(capsys)
    assert "cli.version is '16.28.0', mise pins 25.3.0" in err


def test_python_mirror_must_match_declaration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Python is declared in .python-version; the images mirror it."""
    version_file = tmp_path / ".python-version"
    version_file.write_text("3.12.15\n", encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG PYTHON_VERSION=3.12.11\nFROM python:${PYTHON_VERSION}-slim\n", encoding="utf-8"
    )
    monkeypatch.setattr(check_tool_pins, "PYTHON_VERSION_FILE", version_file)
    monkeypatch.setattr(
        check_tool_pins,
        "PYTHON_MIRRORS",
        ((dockerfile, r"ARG\s+PYTHON_VERSION=(\d+\.\d+\.\d+)"),),
    )
    monkeypatch.setattr(check_tool_pins, "RUST_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "RUNTIME_SCAN", ())
    _rc, _out, err = _run(capsys)
    assert "mirrors python 3.12.11, declared 3.12.15" in err


def test_rust_mirror_must_match_mise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rust has no idiomatic file, so mise.toml declares it and the image mirrors it."""
    mise = tmp_path / "mise.toml"
    mise.write_text('[tools]\nrust = "1.99.1"\n', encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "ARG RUST_VERSION=1.98.0\nFROM rust:${RUST_VERSION}-slim-bookworm\n", encoding="utf-8"
    )
    monkeypatch.setattr(check_tool_pins, "ROOT_MISE", mise)
    monkeypatch.setattr(check_tool_pins, "PYTHON_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "PYTHON_VERSION_FILE", tmp_path / "absent")
    monkeypatch.setattr(
        check_tool_pins,
        "RUST_MIRRORS",
        ((dockerfile, r"ARG\s+RUST_VERSION=(\d+\.\d+\.\d+)"),),
    )
    monkeypatch.setattr(check_tool_pins, "RUNTIME_SCAN", ())
    _rc, _out, err = _run(capsys)
    assert "mirrors rust 1.98.0, declared 1.99.1" in err


def test_pnpm_mirror_must_match_package_manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Corepack reads packageManager, so a Dockerfile mirroring it must agree."""
    package_json = tmp_path / "package.json"
    package_json.write_text('{\n  "packageManager": "pnpm@10.17.1"\n}\n', encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("RUN corepack prepare pnpm@10.16.0 --activate\n", encoding="utf-8")
    monkeypatch.setattr(check_tool_pins, "ROOT_PACKAGE_JSON", package_json)
    monkeypatch.setattr(
        check_tool_pins,
        "_PNPM_MIRRORS",
        ((dockerfile, r"corepack prepare pnpm@(\d+\.\d+\.\d+)"),),
    )
    monkeypatch.setattr(check_tool_pins, "REPO_ROOT", tmp_path)
    _rc, _out, err = _run(capsys)
    assert "mirrors pnpm 10.16.0, package.json declares 10.17.1" in err


def test_pnpm_action_setup_explicit_version_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit `version:` overrides packageManager, so it is a second pin."""
    package_json = tmp_path / "package.json"
    package_json.write_text('{\n  "packageManager": "pnpm@10.17.1"\n}\n', encoding="utf-8")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "release.yml").write_text(
        "      - uses: pnpm/action-setup@abc123 # v6.0.10\n"
        "        with:\n"
        "          version: 10.17.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_tool_pins, "ROOT_PACKAGE_JSON", package_json)
    monkeypatch.setattr(check_tool_pins, "_PNPM_MIRRORS", ())
    monkeypatch.setattr(check_tool_pins, "REPO_ROOT", tmp_path)
    _rc, _out, err = _run(capsys)
    assert "pnpm/action-setup pins version 10.17.1 explicitly" in err
