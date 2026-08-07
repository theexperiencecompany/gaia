"""Dev-only persona thrash harness for the briefing/todo system.

Replays full user days/weeks against a LIVE local stack (see the
``driving-gaia`` skill) and asserts every user-facing behavior through real
surfaces. Run with ``uv run python -m scripts.persona_harness --persona
<name>|all`` from ``apps/api``. See ``openspec/changes/daily-briefing-self-
executing-todos/tasks.md`` I.7.
"""
