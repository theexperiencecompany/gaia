"""
Cache Constants.

Centralized cache-related constants including TTL values and key prefixes.
Import these instead of defining local constants in services.
"""

# Time-to-live values (in seconds)
ONE_YEAR_TTL = 31_536_000
ONE_DAY_TTL = 86_400
ONE_HOUR_TTL = 3_600
THIRTY_MINUTES_TTL = 1_800
TEN_MINUTES_TTL = 600

# Default cache TTLs by use case
DEFAULT_CACHE_TTL = ONE_HOUR_TTL
STATS_CACHE_TTL = THIRTY_MINUTES_TTL

# Cache key prefixes
TEAM_CACHE_PREFIX = "team"
