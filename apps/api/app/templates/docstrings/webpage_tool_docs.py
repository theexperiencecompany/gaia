"""Docstrings for webpage-related tools."""

FETCH_WEBPAGES = """
Fetch content from provided URLs concurrently and return a formatted summary.

Renders each URL to markdown by trying engines in order until one succeeds:
Crawl4AI (headless-Chromium render, handles JS) -> Firecrawl (managed scraper,
retries through a stealth proxy if the first attempt looks blocked) -> httpx
(keyless raw HTTP, no JS rendering, final backstop). Automatically adds
'https://' to URLs missing a protocol prefix. Results are cached per URL.

Args:
    urls: A list of website URLs to fetch content from.

Returns:
    A dictionary with either successful webpage data (in markdown format) or an error message
"""
