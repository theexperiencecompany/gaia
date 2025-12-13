"""Docstrings for webpage-related tools."""

FETCH_WEBPAGES = """
Fetch content from provided URLs using Firecrawl and return a formatted summary.

This tool retrieves web content from multiple URLs concurrently using Firecrawl's advanced scraping capabilities.
It automatically adds 'https://' to URLs missing a protocol prefix and uses intelligent proxy strategies:
- First attempts with 'auto' proxy (basic -> stealth retry if needed)
- Falls back to stealth proxy for sites with advanced anti-bot protection
- Stealth proxy costs 5 credits per request when used

Args:
    urls: A list of website URLs to fetch content from. If not provided, will try to use URLs from the state.

Returns:
    A dictionary with either successful webpage data (in markdown format) or an error message
"""
