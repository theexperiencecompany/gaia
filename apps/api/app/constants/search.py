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

# Process-wide cap on concurrent headless-browser instances.
#
# crawl4ai launches a Chromium per ``AsyncWebCrawler`` context; with the worker
# running up to ``max_jobs`` crawl jobs (each profile crawl opening its own
# crawler per URL), unbounded concurrency means dozens of Chromium processes at
# 150–400 MB each — the dominant worker memory spike. Override via the
# ``CRAWL4AI_MAX_BROWSERS`` env var. Minimum 1; 0/negative would deadlock all
# crawler access.
CRAWL4AI_DEFAULT_MAX_BROWSERS = 2
CRAWL4AI_MIN_MAX_BROWSERS = 1

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
