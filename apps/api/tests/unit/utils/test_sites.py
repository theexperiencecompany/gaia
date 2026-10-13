"""One reading of what site an address is on, and of a secret's placeholder."""

import pytest

from app.utils.sites import PLACEHOLDER, UserSites, host_of, on_site, site_of

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("address", "host"),
    [
        ("https://sub.Example.com/path", "sub.example.com"),
        ("example.com", "example.com"),
        ("github.com/login", "github.com"),
        ("localhost:3000/x", "localhost"),
        # A URL whose scheme carries no host names no site.
        ("about:blank", None),
        ("mailto:ada@mail.test", None),
        ("", None),
        (None, None),
        ("https://", None),
        ("https://[::1", None),  # unparseable (unbalanced IPv6 bracket)
    ],
)
def test_host_of(address: str | None, host: str | None) -> None:
    assert host_of(address) == host


def test_a_written_www_names_the_whole_site() -> None:
    assert (site_of("https://WWW.Example.com/x"), site_of("www.example.com")) == (
        "example.com",
        "example.com",
    )
    assert site_of("https://") is None


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


@pytest.mark.parametrize(
    ("page", "named"),
    [
        # Written in the task, bare or with a scheme, in any case; "www." names the whole site.
        ("https://booking.com/hotels", True),
        ("https://secure.booking.com/pay", True),
        ("https://news.ycombinator.com/item?id=1", True),
        # The page the run starts on, and the site a secret was given for.
        ("https://shop.test/cart", True),
        ("https://bank.test/login", True),
        # Anything else, and a host that only ends in the same letters.
        ("https://ads.test/x", False),
        ("https://notbooking.com/", False),
        # An email's domain is someone's address, not a site to open.
        ("https://mail.test/", False),
        ("about:blank", False),
        (None, False),
    ],
)
def test_a_page_is_on_a_named_site_only_when_the_task_named_it(
    page: str | None, named: bool
) -> None:
    sites = UserSites(
        "Compare prices on WWW.Booking.com and https://news.ycombinator.com/ then mail ada@mail.test",
        "https://www.shop.test/",
        ["bank.test"],
    )

    assert sites.named(page) is named


def test_a_task_that_names_no_site_names_none() -> None:
    assert UserSites("find a cheap flight", None, ()).named("https://flights.test/") is False
