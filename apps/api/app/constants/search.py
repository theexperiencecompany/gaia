"""
Search Constants.

Constants for search service operations including content limits and timeouts.
"""

from app.constants.cache import ONE_DAY_TTL

# Content length limits
MAX_CONTENT_LENGTH = 8000  # Max characters per webpage
MAX_TOTAL_CONTENT = 20000  # Max total characters for all webpages combined

# Request timeouts (seconds)
URL_TIMEOUT = 20.0

# Cache settings
SEARCH_CACHE_TTL = ONE_DAY_TTL
