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

⚠️ ANTI-HALLUCINATION RULES (CRITICAL — NEVER VIOLATE):
  - NEVER invent, fabricate, or guess URLs. Every URL in your response MUST come from the
    `sources` list returned by this tool. No exceptions.
  - NEVER make up article titles, author names, publication dates, or statistics.
  - If a source has `fetch_error` or only a snippet, note this and do not fabricate full content.
  - If no sources were found (`source_count` is 0), say clearly: "I couldn't find sources on
    this topic" — do NOT invent fake links or results.
  - Only cite URLs that appear in the `sources` list. Copy them verbatim — do not alter, shorten,
    or reconstruct them.
  - When content is only a snippet (prefixed with "[Snippet only — full page unavailable]"),
    clearly indicate the source was not fully accessible.

⚠️ TRANSPARENCY REQUIREMENTS:
  - Report the sub-queries that were used to search (from `sub_queries` field).
  - Show which URLs were found and successfully fetched vs. those that failed.
  - If search returned fewer results than expected, say so.

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
    elapsed time, and synthesis-ready findings. All URLs in `sources` were returned by actual
    search queries — they are real and were not fabricated.
"""

RESEARCH_INSTRUCTIONS = (
    "You have full page content from multiple research sources. "
    "CRITICAL — ANTI-HALLUCINATION: Only cite and reference URLs that appear in the `sources` list "
    "returned by this tool. NEVER invent, guess, or fabricate URLs, titles, authors, or statistics. "
    "If a source failed to fetch (has fetch_error) or contains only a snippet, note this limitation "
    "clearly rather than making up the missing content. "
    "If source_count is 0 or no results were found, state that clearly — do not hallucinate results. "
    "TRANSPARENCY: Mention what searches were run (sub_queries) and how many sources were found and "
    "fetched successfully. "
    "Match response depth to the requested research depth (quick, standard, deep). "
    "The user explicitly requested deep research, so they expect depth and completeness, not a short overview. "
    "Cover every important aspect thoroughly: explain concepts in detail, include specific data points, "
    "statistics, examples, quotes, technical details, and nuances from the sources. "
    "Structure the response with clear headings and subheadings. Each section should be substantive — "
    "multiple paragraphs, not a single sentence. "
    "Reproduce key data, numbers, and specific findings directly from the sources rather than vaguely referencing them. "
    "Highlight agreements and contradictions across sources. "
    "Always cite with [1], [2] notation inline and include a full numbered reference list at the end "
    "using only the URLs from the `sources` list. "
    "Use length appropriate to the selected depth and topic complexity."
)
