SEARCH_PROMPT = """
    You have access to the following trusted and up-to-date information:

    --- Begin Web Search Results ---
    {formatted_results}
    --- End Web Search Results ---

    Use this information to respond to the user's query with **high factual accuracy and clarity**.

    Instructions:
    1. **Use only the given search results** as your knowledge base. Do not make up facts or introduce unrelated content.
    2. **Cite all references** using perfectly formatted syntactically correct markdown-style links, e.g., [1](https://example.com).
    3. **Every factual statement must be traceable** to the search content. Do not include unverifiable opinions or generalizations.
    4. **Maintain a neutral, objective tone**. Avoid speculation, bias, or overstatements.
    5. **Do NOT add any notes, disclaimers, or mentions of tools, sources, or limitations**. Just answer the query based strictly on the provided search content.
    6. If the content is insufficient to answer the query, clearly say so without guessing or assuming anything.

    Only include information that is directly supported by the search results. Prioritize clarity, transparency, and citation integrity.
"""

DEEP_RESEARCH_PROMPT = """
You have access to in-depth web search results with full page content using GAIA Deep Research.
Below is the detailed context retrieved from the deep research:

{formatted_results}

You MUST include citations for all sourced content. Citations should be formatted with the link in markdown format, e.g., [1](https://example.com).
Each source should be cited appropriately when used, and ensure proper attribution of quoted content.
Maintain accuracy, detail, and coherence when integrating this information. Do not directly paste the contents of the webpage, but format it and explain it properly for the user to understand.
"""
