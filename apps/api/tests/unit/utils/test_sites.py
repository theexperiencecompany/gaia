"""One reading of what site an address is on, and of a secret's placeholder."""

import pytest

from app.utils.sites import PLACEHOLDER, host_of, on_site

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("address", "host"),
    [
        ("https://sub.Example.com/path", "sub.example.com"),
        ("example.com", "example.com"),
        ("github.com/login", "github.com"),
        ("", None),
        (None, None),
        ("https://", None),
        ("https://[::1", None),  # unparseable (unbalanced IPv6 bracket)
    ],
)
def test_host_of(address: str | None, host: str | None) -> None:
    assert host_of(address) == host


def test_a_site_covers_itself_and_its_subdomains_never_a_lookalike() -> None:
    assert on_site("github.com", "github.com")
    assert on_site("gist.github.com", "github.com")
    assert not on_site("notgithub.com", "github.com")
    assert not on_site("github.com.evil.test", "github.com")


def test_a_placeholder_is_read_as_browser_use_reads_it_and_never_spans_two() -> None:
    # Browser-Use fills any name between the tags, spaces included.
    assert PLACEHOLDER.findall('{"text": "<secret>my pass</secret> <secret>pin</secret>"}') == [
        "my pass",
        "pin",
    ]
    assert PLACEHOLDER.fullmatch("<secret>a</secret> and <secret>b</secret>") is None
