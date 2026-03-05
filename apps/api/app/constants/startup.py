"""Startup and warmup constants.

This module centralizes constants related to process startup and background
warmup.

Notes:
- Keep warmup concurrency low by default. These tasks may build agent graphs,
  connect to multiple services, and perform indexing.
- When adjusting concurrency, consider CPU, memory, and downstream rate limits.
"""

# Production FastAPI: background warmup for all registered providers.
#
# Default: 5
# Rationale: warmup runs after the server starts accepting requests, so we can
# safely do more concurrent work than during blocking startup. Keep this number
# modest to avoid CPU/memory spikes from compiling multiple agent graphs at
# once.
PROD_PROVIDER_WARMUP_CONCURRENCY = 5


# Auto-initialized providers are typically a smaller subset (core services).
# We run these with similar concurrency so they complete quickly.
AUTO_PROVIDER_CONCURRENCY = 5
