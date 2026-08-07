"""Docstrings for file-related tools."""

SEARCH_UPLOADED_FILES = """
Semantic search across the files the user uploaded **in this conversation**.

Runs a vector similarity search over the uploaded files' indexed content and returns the most relevant passages. Scope is strictly the current conversation's uploads — it never reaches files from other conversations, system files, or the web.

### When to Use:
- The user asks something that spans several uploaded files and you need to find which one(s) are relevant ("which of these mentions the Q3 budget?").
- You need the most relevant passages across uploads without reading each file end-to-end.

### When **Not** to Use:
- You already know the single file you need — read it directly at its `/workspace/.../user-uploaded/<file>` path, or read its `<file>.summary.md` for the full summary. Don't route a known-file read through this tool.
- The question is general knowledge unrelated to the uploaded files, or needs the live web — use the appropriate web/research tool instead.

### Query Input Guidelines:
Pass a clear, information-seeking phrase that reflects the goal, e.g.:
- "key takeaways from the report"
- "where the contract defines payment terms"
- "mentions of project timelines"

### Returns:
    str: The most relevant passages from the conversation's uploaded files, or a
         message when nothing relevant is found.
"""
