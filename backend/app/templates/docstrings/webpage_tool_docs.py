"""Docstrings for webpage-related tools."""

FETCH_WEBPAGES = """
Fetch content from provided URLs and return a formatted summary.

This tool retrieves web content from multiple URLs concurrently.
It automatically adds 'https://' to URLs missing a protocol prefix.

Args:
    urls: A list of website URLs to fetch content from. If not provided, will try to use URLs from the state.

Returns:
    A dictionary with either successful webpage data or an error message
"""
