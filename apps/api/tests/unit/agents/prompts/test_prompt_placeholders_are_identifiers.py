"""Every ``{placeholder}`` in a prompt that is ``str.format``-ed must be a kwarg name.

A literal example inside the prose, ``"- {date}: {what happened}"``, is not an
example to the formatter: it is two placeholders nobody passes, and the call
raises ``KeyError``. That shipped: every calendar-triggered workflow run for a
user with tracked todos failed with ``KeyError: 'date'``, 54 times in one day,
and the failure read as a data problem because the message was one bare word.

A placeholder that is not a Python identifier (a space, a quote, a colon)
cannot be satisfied by any ``.format(**kwargs)`` call, so it is always a
literal that forgot its ``{{`` ``}}``. Only constants that actually reach a
``.format(`` call are checked: prompts handed to the model verbatim may carry
JSON examples in single braces, and those are fine.
"""

import importlib
import pathlib
import re
from string import Formatter

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parents[4] / "app"
PROMPTS_PACKAGE = "app.agents.prompts"
FORMAT_CALL = re.compile(r"\b([A-Z][A-Z0-9_]+)\.format\(")


def _formatted_constant_names() -> set[str]:
    """Names that appear as ``NAME.format(`` anywhere under ``app/``."""
    names: set[str] = set()
    for path in APP_ROOT.rglob("*.py"):
        names.update(FORMAT_CALL.findall(path.read_text(encoding="utf-8")))
    return names


def _prompt_constants() -> dict[str, str]:
    package = importlib.import_module(PROMPTS_PACKAGE)
    modules = (
        importlib.import_module(f"{PROMPTS_PACKAGE}.{path.stem}")
        for path in pathlib.Path(package.__path__[0]).glob("*.py")
    )
    return {
        name: value
        for module in modules
        for name, value in vars(module).items()
        if name.isupper() and isinstance(value, str)
    }


def _non_identifier_placeholders(template: str) -> list[str]:
    fields = (field for _, field, _, _ in Formatter().parse(template) if field)
    # ``a.b`` and ``a[0]`` are legal attribute/index forms; only the root must be a name.
    return sorted(
        {field for field in fields if not field.split(".")[0].split("[")[0].isidentifier()}
    )


FORMATTED_PROMPTS = sorted(_formatted_constant_names() & set(_prompt_constants()))


def test_the_guard_found_the_prompts_it_is_meant_to_check() -> None:
    # If the scan ever finds nothing, the test below passes for free.
    assert "SIGNAL_MATCHING_INSTRUCTIONS" in FORMATTED_PROMPTS


@pytest.mark.unit
@pytest.mark.parametrize("name", FORMATTED_PROMPTS)
def test_every_placeholder_in_a_formatted_prompt_is_a_kwarg_name(name: str) -> None:
    offenders = _non_identifier_placeholders(_prompt_constants()[name])
    assert offenders == [], (
        f"{name} is str.format-ed but holds placeholders no kwarg can satisfy; "
        f"a literal example in the prose needs doubled braces: {offenders!r}"
    )
