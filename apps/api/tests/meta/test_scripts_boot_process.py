"""Every runnable API script boots through boot_process, never by hand.

A script has no app lifespan. boot_process is the one bootstrap: it captures the running loop
(worker threads reach Mongo and Redis on it) and registers the lazy providers. A script that
registered providers by hand skipped the loop capture, and one that skipped both failed in prod
on its first Composio call while printing success.
"""

import ast
from pathlib import Path

import pytest

# Read from the checkout, not via app/: the mutation lane runs a relocated app/ with no repo around it.
API_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_TREES = (API_ROOT / "scripts", API_ROOT / "app" / "scripts")
HAND_BOOTSTRAP = {"register_lazy_providers", "capture_running_loop", "unified_startup"}
# Overriding a provider after boot_process is fine (the evals swap in a per-case graph).
REGISTRY_CALLS = {"register", "get", "aget"}


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_registry_call(call: ast.Call, attrs: set[str]) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in attrs
        and isinstance(func.value, ast.Name)
        and func.value.id == "providers"
    )


def boot_violations(source: str) -> list[str]:
    """Return why a script's source bootstraps wrongly; empty when it boots through boot_process."""
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    found = [
        f"line {call.lineno}: {_called_name(call)}() by hand"
        for call in calls
        if _called_name(call) in HAND_BOOTSTRAP
    ]
    if any(_called_name(call) == "boot_process" for call in calls):
        return found
    return found + [
        f"line {call.lineno}: providers.{_called_name(call)}() without boot_process()"
        for call in calls
        if _is_registry_call(call, REGISTRY_CALLS)
    ]


def _scripts() -> list[Path]:
    return sorted(path for tree in SCRIPT_TREES for path in tree.rglob("*.py"))


@pytest.mark.regression
def test_no_script_bootstraps_by_hand_or_reads_providers_unbooted() -> None:
    offenders = {
        str(path.relative_to(API_ROOT)): problems
        for path in _scripts()
        if (problems := boot_violations(path.read_text()))
    }

    assert offenders == {}, (
        "call boot_process(<context>) from the script's running loop instead; it captures the "
        f"loop and registers every provider: {offenders}"
    )


def test_the_script_trees_are_found() -> None:
    assert len(_scripts()) > 50


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("register_lazy_providers('main_app')", ["line 1: register_lazy_providers() by hand"]),
        (
            "providers.register(name='x', loader_func=f)",
            ["line 1: providers.register() without boot_process()"],
        ),
        ("boot_process('arq_worker')\nproviders.register(name='x', loader_func=f)", []),
        (
            "boot_process('main_app')\nregister_lazy_providers('main_app')",
            ["line 2: register_lazy_providers() by hand"],
        ),
        ("capture_running_loop()", ["line 1: capture_running_loop() by hand"]),
        (
            "async def main():\n    await providers.aget('chromadb_constructor')",
            ["line 2: providers.aget() without boot_process()"],
        ),
        ("boot_process('main_app')\nproviders.get('x')", []),
        ("other.register(x)\nsettings.get('x')", []),
    ],
)
def test_the_check_names_each_wrong_form(source: str, expected: list[str]) -> None:
    assert boot_violations(source) == expected
