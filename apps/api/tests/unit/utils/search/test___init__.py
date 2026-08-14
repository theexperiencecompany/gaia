"""The search package surface — the two cached entry points it re-exports."""

from app.utils import search


def test_package_exports_the_cached_entry_points() -> None:
    assert callable(search.perform_search)
    assert callable(search.search_for_research)
