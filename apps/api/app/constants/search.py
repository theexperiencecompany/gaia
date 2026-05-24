"""
Search Constants.

Constants for search service operations including content limits and timeouts.
"""

# Content length limits
MAX_CONTENT_LENGTH = 8000  # Max characters per webpage
MAX_TOTAL_CONTENT = 20000  # Max total characters for all webpages combined

# Request timeouts (seconds)
URL_TIMEOUT = 20.0

# crawl4ai defaults
CRAWL4AI_PAGE_TIMEOUT_MS = 30_000
CRAWL4AI_WAIT_UNTIL = "domcontentloaded"

# Single-page crawl timeout (used by utility fallbacks)
CRAWL4AI_SINGLE_TOTAL_TIMEOUT_SECONDS = 35.0

# Deep research crawl batch settings
DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS = 120.0
DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT = 5
DEEP_RESEARCH_FALLBACK_SEMAPHORE_COUNT = 5

# Profile crawl batch settings
PROFILE_CRAWL4AI_SINGLE_TIMEOUT_SECONDS = 35.0
PROFILE_CRAWL4AI_BATCH_TIMEOUT_SECONDS = 120.0
PROFILE_CRAWL4AI_SEMAPHORE_COUNT = 20
PROFILE_CRAWL_CONTENT_MAX_CHARS = 50_000
