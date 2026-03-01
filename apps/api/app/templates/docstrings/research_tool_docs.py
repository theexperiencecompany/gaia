"""Docstrings for deep research tools."""

DEEP_RESEARCH = """
Conduct comprehensive, multi-source deep research on any topic with parallel search and full content analysis.

This tool orchestrates multiple targeted searches, fetches and reads full web pages, and returns structured
research findings ready for synthesis. It is significantly more thorough than a basic web search.

⚠️ IMPORTANT — ASK BEFORE CALLING:
Before invoking this tool, you MUST ask the user these clarifying questions (if not already answered):
1. **Scope**: What specific angle or aspect matters most? (e.g., "technical implementation", "business impact", "latest news")
2. **Depth**: How thorough should the research be? (1=quick, 2=standard, 3=exhaustive deep dive)
4. **Focus areas**: Any specific subtopics or aspects to prioritize? (optional)

⚠️ OUTPUT EXPECTATIONS:
This tool returns full page content, not snippets. Your response MUST be long and comprehensive —
detailed sections with specific facts, data, and examples from every source. Never give a brief summary.

✅ USE THIS TOOL WHEN:
- The user explicitly asks for "deep research", "thorough analysis", or "comprehensive investigation"
- The topic requires synthesis across many sources (academic, news, technical docs)
- You need full article/page content, not just snippets
- The user wants a structured report with citations
- Comparing products, technologies, approaches, or events

❌ DO NOT USE FOR:
- Quick fact lookups → Use `web_search_tool` instead
- Single URL content → Use `fetch_webpages` instead
- Simple questions with known answers
- Casual conversation or personal questions

Examples:
✅ "Research the current state of quantum computing and its commercial applications"
✅ "Give me a comprehensive analysis of the 2024 EU AI Act — technical, legal, and business implications"
✅ "Deep dive into Rust vs Go for systems programming — performance, ecosystem, adoption"
✅ "Research the best approaches for building RAG systems at scale"
❌ "What year was Python created?" (use web_search_tool)
❌ "Summarize this one article" (use fetch_webpages)

Args:
    query: The main research question or topic.
    scope: Specific angle to focus on (e.g., "technical implementation", "market trends", "historical context").
    depth: Research depth — 1=quick (3 queries, 5 sources), 2=standard (6 queries, 10 sources), 3=deep (9 queries, 20 sources).
    focus_areas: Optional list of specific subtopics or aspects to prioritize.

Returns:
    Structured research data with full source content, rankings, and synthesis-ready findings.
"""
