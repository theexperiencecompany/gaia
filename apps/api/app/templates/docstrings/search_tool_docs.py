"""Docstrings for search-related tools."""

WEB_SEARCH_TOOL = """
Perform a quick, high-level web search to gather brief and relevant information from multiple sources.

This tool is designed for fast, general-purpose lookups — returning summarized snippets and titles
from various web and news sources. It prioritizes speed and topical variety over detail.

✅ USE THIS TOOL WHEN:
- The user asks a general question requiring current or public knowledge.
- You need a quick overview, definition, or summary from external sources.
- The topic is trending, news-based, or time-sensitive.
- You need to cite multiple perspectives quickly.

❌ DO NOT USE FOR:
- Detailed, in-depth research or full content analysis → Use `deep_research` instead.
- Clean, readable content from websites using Firecrawl.
- Internal knowledge that the assistant should already know.
- Personal or conversational responses unrelated to external facts.

Examples:
✅ "What's the latest news on the Ethereum ETF?"
✅ "Summarize key facts about the Mars 2025 mission."
✅ "What do experts say about intermittent fasting?"
❌ "Summarize this PDF." (Not a web search)
❌ "Who am I?" (Relies on memory, not web)
❌ "Give me the full content of this article." (Use deep research)

Args:
    query_text: A clear and concise search query for finding high-level web results.

Returns:
    A JSON string with summarized search data, formatted text, and raw result structure.
"""
