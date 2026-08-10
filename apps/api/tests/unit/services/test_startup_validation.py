"""validate_startup_requirements must HALT startup when setup is incomplete.

It is a ``strategy=ERROR`` lazy provider, so raising propagates through the
strict auto-initializer and aborts a blocking boot. A prior broad ``except``
swallowed its own ``RuntimeError`` and the check never halted anything.
"""

import ast
import importlib
from pathlib import Path
import re
from unittest.mock import AsyncMock, patch

import pytest

from app.services import startup_validation

API_ROOT = Path(startup_validation.__file__).parents[2]

MODULE = "app.services.startup_validation"

# @lazy_provider replaces the module name with a registration callable; calling it
# (re)registers the provider and returns the LazyLoader whose loader_func is the raw
# coroutine under test. Re-registering under the same name overwrites harmlessly.
validate_startup_requirements = startup_validation.validate_startup_requirements().loader_func


class TestValidateStartupRequirements:
    async def test_passes_when_models_and_payment_are_seeded(self) -> None:
        with (
            patch(f"{MODULE}.are_models_seeded", AsyncMock(return_value=True)),
            patch(f"{MODULE}.is_payment_setup", AsyncMock(return_value=True)),
        ):
            assert await validate_startup_requirements() is None

    async def test_raises_when_models_are_not_seeded(self) -> None:
        with (
            patch(f"{MODULE}.are_models_seeded", AsyncMock(return_value=False)),
            patch(f"{MODULE}.is_payment_setup", AsyncMock(return_value=True)),
            pytest.raises(RuntimeError, match="Startup requirements not met"),
        ):
            await validate_startup_requirements()

    async def test_raises_when_payment_is_not_set_up(self) -> None:
        with (
            patch(f"{MODULE}.are_models_seeded", AsyncMock(return_value=True)),
            patch(f"{MODULE}.is_payment_setup", AsyncMock(return_value=False)),
            pytest.raises(RuntimeError, match="Startup requirements not met"),
        ):
            await validate_startup_requirements()

    @pytest.mark.parametrize(
        ("models_ok", "payment_ok"),
        [(False, True), (True, False), (False, False)],
    )
    async def test_remediation_names_scripts_that_actually_exist(
        self, models_ok: bool, payment_ok: bool
    ) -> None:
        # The guidance is the whole value of this check — it previously pointed at
        # ./scripts/setup.sh, which does not exist in the repo, so an operator who
        # followed it got "no such file" instead of a seeded database.
        with (
            patch(f"{MODULE}.are_models_seeded", AsyncMock(return_value=models_ok)),
            patch(f"{MODULE}.is_payment_setup", AsyncMock(return_value=payment_ok)),
            pytest.raises(RuntimeError) as excinfo,
        ):
            await validate_startup_requirements()

        referenced = re.findall(r"scripts/[\w./-]+", str(excinfo.value))
        assert referenced, f"error names no runnable script: {excinfo.value}"
        for script in referenced:
            assert (API_ROOT / script).is_file(), f"error points at missing {script}"

    def test_remediation_scripts_still_resolve_their_app_imports(self) -> None:
        # payment_setup.py imported PlanDB long after it was renamed to PlanDocument,
        # so the command this error recommends died on ImportError and
        # subscription_plans stayed empty — making the check fail forever. Nothing
        # imports these scripts, so only running them surfaced the drift.
        commands = [
            startup_validation.SEED_MODELS_COMMAND,
            startup_validation.SEED_PLANS_COMMAND,
        ]
        checked = 0
        for command in commands:
            script = API_ROOT / re.search(r"scripts/[\w./-]+\.py", command).group()
            tree = ast.parse(script.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if not (node.module or "").startswith("app."):
                    continue
                module = importlib.import_module(node.module)
                for alias in node.names:
                    assert hasattr(module, alias.name), (
                        f"{script.name} imports {alias.name} from {node.module}, "
                        "which no longer defines it"
                    )
                    checked += 1
        assert checked, "no app.* imports were verified — the check is vacuous"

    async def test_a_check_error_propagates_rather_than_being_swallowed(self) -> None:
        # A real failure of the check itself (e.g. a Mongo error) must also surface,
        # not be logged and ignored — the broad except that did that is gone.
        with (
            patch(f"{MODULE}.are_models_seeded", AsyncMock(side_effect=ConnectionError("mongo"))),
            pytest.raises(ConnectionError),
        ):
            await validate_startup_requirements()
