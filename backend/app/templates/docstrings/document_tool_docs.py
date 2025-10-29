"""Docstrings for document-related tools."""

GENERATE_DOCUMENT = r"""
Generates downloadable files in various formats (PDF, DOCX, TXT, etc.) that are saved locally.

TOOL SELECTION: Use this when user says "file". Use create_google_doc_tool when user says "doc".

Creates any file format. NO RESTRICTIONS on content for plain text files.

CRITICAL RULES:
- is_plain_text=True: Writes content EXACTLY as provided. Use for ALL code, markup, data, and config files.
- is_plain_text=False: Content is Markdown, converted via Pandoc. You MAY use LaTeX inside Markdown — but ONLY when the output format supports it.

PLAIN TEXT FILES (is_plain_text=True):
- Code: py, js, ts, html, css, php, java, cpp, go, rust, dart, swift, kotlin, etc.
- Data: json, xml, csv, yaml, sql, etc.
- Config: ini, conf, env, etc.
- Text: txt, md, log, etc.
- ANY other text-based format

FORMATTED DOCUMENTS (is_plain_text=False):
- Allowed formats: pdf, docx, odt, epub
- Input must be valid **Markdown**
- You can use **LaTeX commands inside Markdown**, but ONLY for output formats that support it

🚫 DO NOT USE LaTeX when output format is `docx` — it won't render properly. Use pure Markdown only.

✅ Use LaTeX (inside Markdown) when output format is `pdf` and you need:

1. **Page Breaks**
```latex
\newpage
````

2. **Custom Page Numbering**
   Place at the start of your Markdown:

```yaml
---
header-includes:
  - \setcounter{page}{2}
---
```

3. **Header/Footer Configuration**

```yaml
---
header-includes:
  - \usepackage{fancyhdr}
  - \pagestyle{fancy}
  - \fancyhead[L]{Confidential}
  - \fancyfoot[C]{Page \thepage}
---
```

4. **Math and Equations**

* Inline:

  ```markdown
  $E = mc^2$
  ```
* Block:

  ```markdown
  $$\int_0^1 x^2 dx$$
  ```

🧠 IMPORTANT:
If you're using LaTeX features like custom headers/footers or page numbers, you MUST embed the header-includes as YAML metadata inside the Markdown content — NOT in a separate metadata argument.

⚠️ Use LaTeX ONLY when needed. Don't use it for things Markdown already handles (bold, lists, headings, etc.)
"""
