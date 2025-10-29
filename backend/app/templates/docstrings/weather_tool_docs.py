"""Docstrings for weather-related tools."""

GET_WEATHER = """
Fetches and formats the weather report for a given location.

This tool queries OpenWeather API using the provided location name and formats
the data into a user-friendly weather summary using a prompt template. Designed
for LangChain-compatible agents to deliver natural language outputs.

Args:
    location (str): The location for which to retrieve the weather report.

Returns:
    str: A JSON string containing both the formatted weather text and raw weather data.
"""
