"""Unit tests for the DB round-trip counter (tests/helpers.assert_num_db_calls).

Uses an in-memory SQLite engine so the counter is proven without any real
infrastructure; the assertion-failure path dumps every captured statement.
"""

import pytest
from sqlalchemy import create_engine, text

from tests.helpers import assert_num_db_calls


def _memory_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER)"))
    return engine


def test_counts_statements_and_warmup() -> None:
    engine = _memory_engine()
    with assert_num_db_calls(2, engine):
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 2"))

    # warmup skips the first captured statement (e.g. a pool warm-up query).
    with assert_num_db_calls(1, engine, warmup=1):
        with engine.connect() as conn:
            conn.execute(text("SELECT 3"))
            conn.execute(text("SELECT 4"))


def test_mismatch_dumps_every_statement() -> None:
    engine = _memory_engine()

    def _run_two_queries() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 2"))

    with pytest.raises(AssertionError, match=r"expected 1 DB query\(ies\), got 2"):
        with assert_num_db_calls(1, engine):
            _run_two_queries()
