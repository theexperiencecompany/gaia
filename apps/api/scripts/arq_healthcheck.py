#!/usr/bin/env python
"""Liveness probe for the ARQ worker, invoked by the Docker healthcheck.

The worker refreshes arq's ``arq:health`` key from its poll loop every
``health_check_interval`` seconds with a TTL of ``interval + 1`` (see arq's
``Worker.record_health``), so the key disappears within ~31s if the loop wedges
or the process dies. Checking that key is exactly what ``arq --check`` does
internally — but ``arq --check`` first imports the whole application, which a
Docker healthcheck cannot do: it runs outside the entrypoint, so it has no
``INFISICAL_TOKEN`` and the import dies during settings bootstrap.

This probe imports nothing from ``app`` (so no application change can break it)
and talks only to Redis — the worker's own job substrate.
"""

from __future__ import annotations

import sys

import redis

# Stable Swarm overlay alias; a healthcheck cannot read the Infisical-injected
# REDIS_URL, so it targets the well-known service name directly.
REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_TIMEOUT_SECONDS = 5

# Must match WorkerSettings.health_check_key in
# app/workers/config/worker_settings.py.
ARQ_HEALTH_KEY = "arq:health"


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
