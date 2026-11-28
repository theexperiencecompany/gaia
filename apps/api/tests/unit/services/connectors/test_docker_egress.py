"""The self-host egress proxy's allowlist reads hosts exactly as E2B's does, and allows nothing else."""

import re

import pytest

from app.services.connectors.docker_egress import host_pattern, squid_config


@pytest.mark.parametrize(
    ("host", "matches", "misses"),
    [
        (
            "api.github.com",
            ["api.github.com", "API.GITHUB.COM"],
            ["xapi.github.com", "api.github.com.evil.io"],
        ),
        ("*.resend.com", ["api.resend.com", "a.b.resend.com"], ["resend.com", "evilresend.com"]),
    ],
)
def test_a_host_pattern_matches_the_host_and_nothing_that_merely_contains_it(
    host: str, matches: list[str], misses: list[str]
) -> None:
    pattern = re.compile(host_pattern(host), re.IGNORECASE)

    assert all(pattern.search(name) for name in matches)
    assert not any(pattern.search(name) for name in misses)


def test_the_config_tunnels_only_to_listed_hosts_on_443_and_never_by_reverse_dns() -> None:
    config = squid_config(("api.github.com",))

    assert r"acl call_hosts dstdom_regex -n -i ^api\.github\.com$" in config
    assert "http_access allow connect_method https_port call_hosts" in config
    assert config.index("http_access allow") < config.index("http_access deny all")


def test_a_call_with_no_hosts_gets_a_proxy_that_allows_nothing() -> None:
    config = squid_config(())

    assert "http_access allow" not in config
    assert "http_access deny all" in config
