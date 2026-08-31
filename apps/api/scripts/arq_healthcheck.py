#!/usr/bin/env python
"""Liveness probe for the ARQ worker, invoked by the Docker healthcheck.

The worker refreshes its own ``arq:health:<hostname>`` key from its poll loop every
``health_check_interval`` seconds with a TTL of ``interval + 1`` (see arq's
``Worker.record_health``), so the key disappears within ~31s if the loop wedges
or the process dies. Checking that key is exactly what ``arq --check`` does
internally — but ``arq --check`` first imports the whole application, which a
Docker healthcheck cannot do: it runs outside the entrypoint, so it has no
Infisical credentials and the import dies during settings bootstrap.

This probe imports nothing from ``app`` (so no application change can break it)
and talks only to Redis — the worker's own job substrate.
"""

from __future__ import annotations

import socket
import sys

import redis

# Stable Swarm overlay alias; a healthcheck cannot read the Infisical-injected
# REDIS_URL, so it targets the well-known service name directly.
REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_TIMEOUT_SECONDS = 5

# Must match WorkerSettings.health_check_key in
# app/workers/config/worker_settings.py — pinned by
# tests/unit/workers/test_worker_lifecycle.py, because this module deliberately
# imports nothing from ``app`` and so cannot share the constant.
#
# Keyed by hostname because this probe runs inside the worker's OWN container.
# A fleet-wide key answers "is any worker alive", which leaves a wedged worker
# green forever behind its healthy siblings.
ARQ_HEALTH_KEY = f"arq:health:{socket.gethostname()}"


def main() -> int:
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
    )
    try:
        return 0 if client.exists(ARQ_HEALTH_KEY) else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
