"""The runner's shared pieces: output capping and ~/ path resolution."""

import pytest

from app.constants.sandbox import SANDBOX_USER_HOME
from app.services.connectors.runner import CappedOutput, runner_path


def test_output_under_the_cap_is_kept_whole() -> None:
    out = CappedOutput(max_bytes=10)
    out.add("hello")
    out.add("world")

    assert (out.text, out.capped) == ("helloworld", False)


def test_output_past_the_cap_is_cut_at_the_cap_and_later_output_dropped() -> None:
    out = CappedOutput(max_bytes=8)
    out.add("12345")
    out.add("67890")
    out.add("more")

    assert (out.text, out.capped) == ("12345678", True)


def test_a_cut_mid_character_drops_the_partial_character() -> None:
    out = CappedOutput(max_bytes=4)
    out.add("ab€")

    assert (out.text, out.capped) == ("ab", True)
    assert len(out.text.encode()) <= 4


def test_a_home_path_resolves_under_the_runner_home() -> None:
    assert runner_path("~/.config/gh/hosts.yml") == f"{SANDBOX_USER_HOME}/.config/gh/hosts.yml"
    assert runner_path("/etc/x") == "/etc/x"


def test_a_relative_path_is_refused() -> None:
    with pytest.raises(ValueError, match="absolute or starts with ~/"):
        runner_path("config/x")
