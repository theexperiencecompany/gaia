"""validate_startup_requirements must HALT startup when setup is incomplete.

It is a ``strategy=ERROR`` lazy provider, so raising propagates through the
strict auto-initializer and aborts a blocking boot. A prior broad ``except``
swallowed its own ``RuntimeError`` and the check never halted anything.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services import startup_validation

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

    async def test_a_check_error_propagates_rather_than_being_swallowed(self) -> None:
        # A real failure of the check itself (e.g. a Mongo error) must also surface,
        # not be logged and ignored — the broad except that did that is gone.
        with (
            patch(f"{MODULE}.are_models_seeded", AsyncMock(side_effect=ConnectionError("mongo"))),
            pytest.raises(ConnectionError),
        ):
            await validate_startup_requirements()
