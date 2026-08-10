-- Test database for the API suite's real-infra tier (checkpointing tests,
-- contracts, HIL e2e). The suite defaults DATABASE_URL to
-- postgresql://postgres:postgres@localhost:5432/gaia_test; without this DB
-- the real-infra Postgres tests silently skip locally while passing in CI.
-- Runs once on first postgres boot (postgres-image init mechanism).
CREATE DATABASE gaia_test;
