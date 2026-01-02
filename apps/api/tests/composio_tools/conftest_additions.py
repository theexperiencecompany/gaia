import pytest


@pytest.fixture(scope="function")
def confirm_action(request):
    """
    Fixture to request user confirmation for destructive actions.
    Requires running pytest with '-s' (no capture) to work interactively.
    """

    def _confirm(message: str) -> None:
        # Check for non-interactive mode flag (optional override)
        if request.config.getoption("--yes", default=False):
            return

        full_msg = f"\n[CONFIRMATION REQUIRED] {message}\nProceed? (y/N): "

        try:
            response = input(full_msg)
        except OSError:
            pytest.fail(
                "Cannot read input. Run pytest with '-s' to enable interactive confirmation."
            )

        if response.lower() not in ["y", "yes"]:
            pytest.skip("Skipped by user")

    return _confirm
