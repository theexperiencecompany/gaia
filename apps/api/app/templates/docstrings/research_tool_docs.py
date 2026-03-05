"""Docstrings for deep research tools."""

DEEP_RESEARCH = """
Conduct comprehensive, multi-source deep research on any topic.

Orchestrates parallel targeted searches across multiple sub-queries, fetches and reads full web page
content (not just snippets), deduplicates and ranks sources by relevance, then returns structured
findings ready for long-form synthesis. Significantly more thorough than a basic web search.

Pipeline:
  1. Decompose the query into N targeted sub-queries (N = 3/6/9 based on depth)
  2. Run all sub-queries in parallel via DuckDuckGo
  3. Deduplicate and rank URLs by combined relevance + appearance frequency
  4. Fetch full page content for top sources (crawl4ai → httpx fallback chain)
  5. Return structured result with sources, content, and citations metadata

⚠️ ASK BEFORE CALLING (if not already clear from context):
  - Scope: What angle matters most? (e.g. "technical", "market trends", "historical")
  - Depth: How thorough? 1=quick, 2=standard, 3=exhaustive
  - Focus areas: Any specific subtopics to prioritize? (optional)

⚠️ OUTPUT EXPECTATIONS:
  Match output length to requested depth:
  - depth=1 (quick): concise but complete
  - depth=2 (standard): detailed
  - depth=3 (deep): exhaustive, long-form
  Cite inline with [1], [2] notation and include a full numbered reference list at the end.

USE THIS TOOL WHEN:
  - User asks for "deep research", "thorough analysis", or "comprehensive investigation"
  - Topic requires synthesis across many sources (academic, news, technical docs)
  - User wants a structured report with citations
  - Comparing products, technologies, approaches, or events in depth

DO NOT USE FOR:
  - Quick fact lookups → use `web_search_tool` instead
  - Single URL content → use `fetch_webpages` instead
  - Simple questions with known answers
  - Casual conversation or personal questions

Examples:
  ✅ "Research the current state of quantum computing and its commercial applications"
  ✅ "Comprehensive analysis of the EU AI Act — technical, legal, and business implications"
  ✅ "Deep dive into Rust vs Go for systems programming — performance, ecosystem, adoption"
  ✅ "Best approaches for building RAG systems at scale"
  ❌ "What year was Python created?" → use web_search_tool
  ❌ "Summarize this one article" → use fetch_webpages

Args:
    query: The main research question or topic to investigate.
    scope: Specific angle or focus (e.g. "technical implementation", "market trends", "historical context").
    depth: Research depth — 1=quick (3 queries, 5 sources), 2=standard (6 queries, 10 sources),
           3=deep (9 queries, 20 sources). Defaults to 2.
    focus_areas: Specific subtopics or aspects to prioritize (e.g. ["performance", "cost", "adoption"]).

Returns:
    Structured research data with full source content, sub-queries used, source rankings,
    elapsed time, and synthesis-ready findings.
"""

RESEARCH_INSTRUCTIONS = (
    "You have full page content from multiple research sources. "
    "Match response depth to the requested research depth (quick, standard, deep). "
    "The user explicitly requested deep research, so they expect depth and completeness, not a short overview. "
    "Cover every important aspect thoroughly: explain concepts in detail, include specific data points, "
    "statistics, examples, quotes, technical details, and nuances from the sources. "
    "Structure the response with clear headings and subheadings. Each section should be substantive — "
    "multiple paragraphs, not a single sentence. "
    "Reproduce key data, numbers, and specific findings directly from the sources rather than vaguely referencing them. "
    "Highlight agreements and contradictions across sources. "
    "Always cite with [1], [2] notation inline and include a full numbered reference list at the end. "
    "Use length appropriate to the selected depth and topic complexity."
)
