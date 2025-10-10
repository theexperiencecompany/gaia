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

DEEP_RESEARCH_TOOL = """
Conduct an in-depth search by retrieving and analyzing the full content of web pages.

This tool should only be used when a user specifically requests:
- A deep dive into a topic
- Thorough research or full article content
- Technical documentation or context-rich explanations
- Clean, structured content from websites

Do NOT use this tool for:
- Simple questions or fact lookups
- Quick overviews or general summaries
- Casual or exploratory queries
- Speed-sensitive responses

It consumes more time and resources than a standard web search, so use it only when depth and detail
are explicitly needed.

Examples:
✅ "Can you analyze the full content of this article?"
✅ "I need detailed technical documentation about Kubernetes networking."
✅ "Give me the complete breakdown from credible sources on how the 2024 AI Act works."
❌ "What's the capital of Sweden?"
❌ "Tell me a bit about quantum computing."

Args:
    query_text: The search query intended for comprehensive exploration.

Returns:
    A JSON string with full content, summaries, and structured data for deep understanding.
"""
