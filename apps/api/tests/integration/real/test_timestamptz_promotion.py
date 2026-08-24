"""Real-Postgres coverage for the naive-timestamp -> timestamptz promotion.

``_ensure_timestamptz_columns`` runs on every startup (``init_postgresql``
calls it right after ``create_all``) and had no test at all. The whitelist it
walks happens to hold only lowercase, non-reserved identifiers, so the old
unquoted ``ALTER TABLE {table} ALTER COLUMN {column}`` worked by luck: the
moment an entry needs quoting — a mixed-case column, or one named after a
reserved word — Postgres case-folds the identifier, the ALTER fails against a
column that "does not exist", and startup dies.

Real Postgres, not a mock: the behaviour under test *is* Postgres identifier
resolution and type promotion.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import os

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.schema import DDL

from app.db import postgresql

pytestmark = [pytest.mark.service, pytest.mark.db]

# Per-worker table: the main CI run collects this file under `-n auto`, and
# xdist's default `load` distribution can hand two tests from one file to two
# workers — which would then CREATE/ALTER/DROP the same table concurrently.
TABLE = f"tz_promotion_probe_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"
# Mixed-case on purpose: unquoted, Postgres folds it to lowercase and the
# statement resolves against a column that does not exist.
COLUMN = "probeCreatedAt"
_QUALIFIED = f'"{TABLE}"'
_QUOTED_COLUMN = f'"{COLUMN}"'


@pytest.fixture
def connection(postgres_url: str) -> Iterator[Connection]:
    engine = create_engine(postgres_url)
    with engine.begin() as conn:
        yield conn
    engine.dispose()


@pytest.fixture
def legacy_table(connection: Connection) -> Iterator[None]:
    """A table holding a naive ``timestamp`` column whose name requires quoting."""
    connection.execute(DDL(f"DROP TABLE IF EXISTS {_QUALIFIED}"))
    connection.execute(
        DDL(f"CREATE TABLE {_QUALIFIED} (id serial PRIMARY KEY, {_QUOTED_COLUMN} timestamp)")
    )
    yield
    connection.execute(DDL(f"DROP TABLE IF EXISTS {_QUALIFIED}"))


@pytest.fixture
def promote_probe_column(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(postgresql, "_TIMESTAMPTZ_COLUMNS", ((TABLE, COLUMN),))


def _column_type(conn: Connection) -> str | None:
    return conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": TABLE, "column": COLUMN},
    ).scalar()


@pytest.mark.regression
@pytest.mark.usefixtures("legacy_table", "promote_probe_column")
def test_promotes_naive_column_whose_name_requires_quoting(connection: Connection) -> None:
    assert _column_type(connection) == "timestamp without time zone"

    postgresql._ensure_timestamptz_columns(connection)

    assert _column_type(connection) == "timestamp with time zone"


@pytest.mark.regression
@pytest.mark.usefixtures("legacy_table", "promote_probe_column")
def test_promotion_reinterprets_the_stored_value_as_utc(connection: Connection) -> None:
    """A naive value is UTC wall-clock, so promotion must reinterpret, not shift."""
    # _QUALIFIED/_QUOTED_COLUMN are hardcoded test constants, not user input.
    connection.execute(
        text(f"INSERT INTO {_QUALIFIED} ({_QUOTED_COLUMN}) VALUES (:value)"),  # noqa: S608 -- hardcoded test constants, not user input
        {"value": "2026-01-02 03:04:05"},
    )

    postgresql._ensure_timestamptz_columns(connection)

    stored = connection.execute(
        text(f"SELECT {_QUOTED_COLUMN} FROM {_QUALIFIED}")  # noqa: S608 -- hardcoded test constants, not user input
    ).scalar()
    assert stored is not None
    assert stored.tzinfo is not None, "column should be tz-aware after promotion"
    assert stored.astimezone(UTC).replace(tzinfo=None) == datetime(2026, 1, 2, 3, 4, 5)


@pytest.mark.regression
@pytest.mark.usefixtures("legacy_table", "promote_probe_column")
def test_is_idempotent_across_restarts(connection: Connection) -> None:
    """Startup runs this every boot; the second pass must be a no-op."""
    postgresql._ensure_timestamptz_columns(connection)
    postgresql._ensure_timestamptz_columns(connection)

    assert _column_type(connection) == "timestamp with time zone"


def test_absent_column_is_skipped_rather_than_erroring(
    connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh DB has no legacy table; create_all already made it correct."""
    monkeypatch.setattr(
        postgresql, "_TIMESTAMPTZ_COLUMNS", (("table_that_does_not_exist", "whenever"),)
    )

    postgresql._ensure_timestamptz_columns(connection)
