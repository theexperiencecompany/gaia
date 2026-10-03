"""The sites a task names: where a bot check is put to the user instead of skipped."""

import pytest

from app.services.browser.user_sites import UserSites

pytestmark = pytest.mark.unit


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
