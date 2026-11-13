"""Startup and warmup constants.

This module centralizes constants related to process startup and background
warmup.

Notes:
- Keep warmup concurrency low by default. These tasks may build agent graphs,
  connect to multiple services, and perform indexing.
- When adjusting concurrency, consider CPU, memory, and downstream rate limits.
"""

# Background warmup for all registered providers, run after the server starts
# accepting requests; kept modest to avoid CPU/memory spikes from compiling
# multiple agent graphs at once.
PROD_PROVIDER_WARMUP_CONCURRENCY = 5


# Auto-initialized providers are typically a smaller subset (core services).
# We run these with similar concurrency so they complete quickly.
AUTO_PROVIDER_CONCURRENCY = 5


#: Where the ARQ worker's startup hook records the event-loop time it booted at,
#: in the ctx ARQ hands both lifecycle hooks; shutdown reads it back for runtime.
WORKER_STARTUP_TIME_CTX_KEY = "startup_time"
