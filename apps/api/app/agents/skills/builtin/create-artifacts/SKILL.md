---
name: create-artifacts
description: Make reports, dashboards, plans, comparisons, memos and documents with create_artifact; code files and data exports go in artifacts/ as files.
target: executor
---

# Create Artifacts

## Reports, dashboards and other documents: create_artifact

When the user asks for a report, dashboard, plan, comparison, memo or any other document to read, call `create_artifact`. It writes the artifact itself, lays it out with GAIA's components (charts, tables, stats, callouts, boards), checks every figure against the facts you pass, and returns a public heygaia.link. The user sees it as a card in chat, opens it in the viewer and can export it as a PDF.

1. Gather the facts first: tool results, memory, the conversation.
2. Call `create_artifact` once with the kind, a title and the brief: every fact the artifact needs, verbatim, with complete data series and source URLs, plus the one-line message it should land. Never put in a number you worked out (a total, a difference, a share, an average); the artifact computes those from the data, and it can only state numbers the brief contains.
3. Reply in a line or two and give the link from the tool result. Do not repeat the artifact's contents.

Never write HTML, Markdown or other files for these: an HTML page is not how GAIA delivers a document.

## Interactive tools: create_artifact with interactive

A calculator, simulator or small tool the user asked to play with is also `create_artifact`: kind `document` and `interactive` true. Nothing else is HTML.

## Code, data exports and files the user asked for by format

Code files and data exports (`.py`, `.csv`, `.json`, `.yaml` and the like) stay files. Write them to `artifacts/` for the current session; only files there are shown to the user, each with a public heygaia.link in the tool result:

    vfs_write("artifacts/file-name.ext", content)

Draft in `files/` and move the finished file into `artifacts/`, so the user never sees scratch or broken output:

    vfs_write("files/draft.py", draft)
    vfs_cmd("mv files/draft.py artifacts/report_export.py")

If `vfs_write` is not bound yet: `retrieve_tools(exact_tool_names=["vfs_write", "vfs_cmd"])`. A PDF, Word or PowerPoint file the user asks for by format uses its own skill (create-pdf, create-docx, create-pptx); a PDF of an artifact is the export its viewer already offers.

## Response pattern

After creating a file, tell the user in a line or two what it is and give its heygaia.link from the tool result as a markdown link.
