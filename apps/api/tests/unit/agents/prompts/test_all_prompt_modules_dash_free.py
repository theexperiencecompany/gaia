"""Every model-visible prompt/doc/tool-description module must stay dash-free.

test_comms_prompt_hygiene.py proved a prompt is a style sample before it is a
rulebook: the model imitates the dashes sitting in its own prose more than it
obeys the rule banning them. This test extends the same guard past the comms
and executor prompts to every other module whose string constants are read by
a model: the subagent system prompts, the onboarding prompts, the memory
prompts, the workspace docs served by ``read_manual``, and the tool
descriptions bound to ``@tool`` functions via ``@with_doc``.

``comms_prompts`` is deliberately excluded: it has its own dedicated test file
that already covers this ground with the one legitimate exception (the
banned-literals line, which cannot ban a literal without naming it).
"""

import importlib
import pkgutil
from types import ModuleType

import pytest

EM_DASH = "—"
EN_DASH = "–"

#: Packages to walk in full (every submodule, minus explicit exclusions below).
PACKAGES_TO_WALK: tuple[str, ...] = (
    "app.agents.prompts",
    "app.agents.core.subagents",
    "app.templates.docstrings",
)

#: Modules that hold their own dedicated hygiene test with a documented
#: exception, so they are not re-checked (blindly) here.
EXCLUDED_MODULES: frozenset[str] = frozenset({"app.agents.prompts.comms_prompts"})

#: Single modules (not whole packages) whose string constants are model-visible.
EXTRA_MODULES: tuple[str, ...] = (
    "app.memory.prompts",
    "app.agents.workspace.operational_docs",
)


def _iter_package_modules(package_name: str) -> list[str]:
    package = importlib.import_module(package_name)
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        return [package_name]
    return [
        f"{package_name}.{modinfo.name}"
        for modinfo in pkgutil.iter_modules(package_path)
        if not modinfo.ispkg
    ]


def _discover_module_names() -> list[str]:
    names: set[str] = set(EXTRA_MODULES)
    for package_name in PACKAGES_TO_WALK:
        names.update(_iter_package_modules(package_name))
    return sorted(names - EXCLUDED_MODULES)


MODULE_NAMES = _discover_module_names()


def _dict_entry_strings(name: str, key: object, entry: object) -> dict[str, str]:
    """Every str reachable from one dict value: the value itself, or, for a
    NamedTuple record (e.g. operational_docs' ``ManualDoc``), each str field."""
    if isinstance(entry, str):
        return {f"{name}[{key!r}]": entry}
    if isinstance(entry, tuple) and hasattr(entry, "_fields"):
        return {
            f"{name}[{key!r}].{field}": field_value
            for field, field_value in zip(entry._fields, entry, strict=True)
            if isinstance(field_value, str)
        }
    return {}


def _string_constants(module: ModuleType) -> dict[str, str]:
    """Every module-level str constant, plus every str reachable inside a
    module-level dict constant (dict-of-str, or dict-of-NamedTuple-of-str)."""
    found: dict[str, str] = {}
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            found[name] = value
        elif isinstance(value, dict):
            for key, inner in value.items():
                found.update(_dict_entry_strings(name, key, inner))
    return found


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_module_string_constants_have_no_dashes(module_name: str) -> None:
    module = importlib.import_module(module_name)
    offenders = [
        (const_name, line)
        for const_name, value in _string_constants(module).items()
        for line in value.splitlines()
        if EM_DASH in line or EN_DASH in line
    ]
    assert not offenders, (
        f"{module_name} has {len(offenders)} dash-containing line(s) in a "
        f"model-visible string constant, first: {offenders[0][0]!r} -> {offenders[0][1]!r}"
    )


def test_discovery_actually_found_the_known_modules() -> None:
    """Guards the discovery mechanism itself: if pkgutil ever silently found
    zero submodules (e.g. a namespace-package path resolution regression),
    every parametrized case above would vacuously pass without checking
    anything. Pin a lower bound so that failure mode is loud instead of a
    silently-green suite."""
    assert len(MODULE_NAMES) >= 30, (
        f"only discovered {len(MODULE_NAMES)} modules, expected at least 30 "
        "across app.agents.prompts, app.agents.core.subagents, "
        "app.templates.docstrings plus the two standalone modules; "
        "module discovery may be broken"
    )


def test_operational_docs_manual_docs_dict_was_actually_checked() -> None:
    """MANUAL_DOCS is the whole reason operational_docs is in scope: pin that
    the dict-of-str branch of _string_constants actually walked it, not just
    that the module happened to import cleanly."""
    module = importlib.import_module("app.agents.workspace.operational_docs")
    manual_docs = module.MANUAL_DOCS
    assert isinstance(manual_docs, dict)
    assert len(manual_docs) > 0
    constants = _string_constants(module)
    assert any(key.startswith("MANUAL_DOCS[") and ".body" in key for key in constants), (
        "MANUAL_DOCS entries were not enumerated by _string_constants"
    )
