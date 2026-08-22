"""Unit tests for URL query-parameter mutation (app.utils.query_utils)."""

from app.utils.query_utils import add_query_param


def test_add_query_param_to_url_without_query() -> None:
    assert add_query_param("https://example.com/path", "page", "2") == (
        "https://example.com/path?page=2"
    )


def test_add_query_param_replaces_existing_value() -> None:
    assert add_query_param("https://example.com/path?page=1", "page", "2") == (
        "https://example.com/path?page=2"
    )


def test_add_query_param_preserves_other_params_and_fragment() -> None:
    assert (
        add_query_param("https://example.com/path?a=1#section", "b", "x")
        == "https://example.com/path?a=1&b=x#section"
    )
