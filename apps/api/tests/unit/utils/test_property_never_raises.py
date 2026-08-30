"""Property-based never-raises tests for string parsers.

Each parser is documented as having a defined outcome on arbitrary input
(return a value or raise a specific ``ValueError``). Hypothesis sweeps all of
``str`` — including the strings no unit test would think to write — to prove
no unexpected exception type can leak out of these boundaries.

The fail-case each property guards: a parser change that lets a new exception
escape (a raw ``httpx`` error, a ``ZoneInfo`` lookup failure, a bare
``AttributeError`` on a malformed URL) would surface here as an unexpected
exception type.
"""

from datetime import UTC, datetime
import string
from typing import Any

from hypothesis import given, settings, strategies as st

from app.utils.timezone import Timezone
from app.utils.url_safety import _parse_http_host_port, assert_safe_url_shape

DEFINED_EXCEPTIONS = (ValueError,)


class TestParseHttpHostPortNeverRaisesUnexpectedly:
    @settings(deadline=None)
    @given(url=st.text())
    def test_arbitrary_text_yields_tuple_or_value_error(self, url: str) -> None:
        try:
            host, port = _parse_http_host_port(url)
        except DEFINED_EXCEPTIONS:
            return
        assert isinstance(host, str) and host != ""
        assert isinstance(port, int) and port > 0

    @settings(deadline=None)
    @given(
        scheme=st.sampled_from(["http", "https"]),
        host=st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=50),
        path=st.text(
            alphabet=string.ascii_lowercase + string.digits + "/", min_size=0, max_size=50
        ),
    )
    def test_well_formed_urls_yield_host_and_default_port(
        self, scheme: str, host: str, path: str
    ) -> None:
        url = f"{scheme}://{host}/{path}"
        parsed_host, port = _parse_http_host_port(url)
        assert parsed_host == host
        assert port == (443 if scheme == "https" else 80)


class TestAssertSafeUrlShapeNeverRaisesUnexpectedly:
    @settings(deadline=None)
    @given(url=st.text())
    def test_arbitrary_text_returns_none_or_value_error(self, url: str) -> None:
        try:
            result = assert_safe_url_shape(url)
        except DEFINED_EXCEPTIONS:
            return
        assert result is None


class TestTimezoneParseNeverRaises:
    @settings(deadline=None)
    @given(name=st.text())
    def test_arbitrary_text_parses_or_falls_back(self, name: str) -> None:
        # The documented contract: parsing must never raise into
        # format/notification paths — invalid input falls back to UTC.
        tz = Timezone.parse(name)
        assert isinstance(tz, Timezone)
        if tz.is_utc:
            assert tz.tzinfo is UTC

    @settings(deadline=None)
    @given(name=st.text())
    def test_any_timezone_yields_aware_datetimes(self, name: str) -> None:
        instant = Timezone.parse(name).localize(datetime(2026, 6, 13, tzinfo=UTC))
        assert instant.tzinfo is not None

    @settings(deadline=None)
    @given(name=st.text())
    def test_try_parse_never_raises(self, name: str) -> None:
        result: Any = Timezone.try_parse(name)
        assert result is None or isinstance(result, Timezone)
