"""Database constants.

Postgres advisory lock ids live here, not beside the engine: importing them
from app.db.postgresql drags sqlalchemy and asyncpg (130 modules, ~140 ms)
into every importer, including the graph builder and the test helpers that
only need the integer.
"""

# Serializes schema bootstrap: concurrent create_all calls (API replicas, xdist
# workers) race on CREATE TYPE for enum columns and fail on pg_type's unique index.
SCHEMA_BOOTSTRAP_LOCK_ID = 743_001_993

# Same race in langgraph's checkpointer/store setup(): its CREATE TABLE IF NOT EXISTS
# collides on pg_type ("checkpoint_migrations") when two starters run it at once.
LANGGRAPH_SETUP_LOCK_ID = 743_001_994
# A waiter for that lock asks again on a timer instead of blocking in a statement:
# setup() builds indexes CONCURRENTLY, which wait for every open transaction, a
# blocked lock wait included, so a blocking waiter and the holder hang each other.
LANGGRAPH_SETUP_LOCK_POLL_SECONDS = 0.5
# Two minutes of asking, then setup fails loud: far beyond one starter's DDL.
LANGGRAPH_SETUP_LOCK_ATTEMPTS = 240

# A transient Mongo failure is retried long enough to outlast a replica-set
# election (~12s): 1+2+4+8s of backoff across five attempts.
MONGO_TRANSIENT_RETRY_ATTEMPTS = 5
MONGO_TRANSIENT_RETRY_INITIAL_SECONDS = 1.0
MONGO_TRANSIENT_RETRY_MAX_SECONDS = 8.0
