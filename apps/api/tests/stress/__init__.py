"""Stress-test tier: adversarial, battle-style tests excluded from the fast default run.

Every test here is deterministic and in-process (no real sleeps, no network, no
Docker): concurrency is driven by ``asyncio`` task scheduling, and Redis/Mongo
seams are replaced with in-process fakes that preserve the real invariants
(atomic SET-NX, cursor-ordered streams, idempotency markers). Each test asserts
a production invariant under adversarial scheduling — not merely "doesn't raise".
"""
