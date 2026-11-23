"""A data script writes only when --apply is passed, and refuses a flag it does not know."""

import pytest
from scripts._cli import apply_requested


@pytest.mark.unit
class TestApplyRequested:
    @pytest.mark.parametrize(("argv", "applies"), [(["--apply"], True), ([], False)])
    def test_only_apply_writes(
        self, monkeypatch: pytest.MonkeyPatch, argv: list[str], applies: bool
    ) -> None:
        monkeypatch.setattr("sys.argv", ["migrate", *argv])

        assert apply_requested("Migrate things.") is applies

    @pytest.mark.parametrize("typo", ["--aply", "apply", "--apply=yes"])
    def test_a_mistyped_flag_stops_the_run_instead_of_dry_running_it(
        self, monkeypatch: pytest.MonkeyPatch, typo: str
    ) -> None:
        """A membership check on sys.argv ran a mistyped --apply as a silent dry run."""
        monkeypatch.setattr("sys.argv", ["migrate", typo])

        with pytest.raises(SystemExit) as exited:
            apply_requested("Migrate things.")

        assert exited.value.code == 2
