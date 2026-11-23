"""Docstrings for the artifact tool."""

CREATE_ARTIFACT = """
Create a polished artifact the user can open, share and export as a PDF: a report,
dashboard, plan, comparison, memo or document. It renders as a card in chat and opens in
GAIA's artifact viewer, with charts, tables, stats and text laid out by the app.

Use it whenever the user asks for one of those deliverables. Do not write HTML, markdown or
files for them: this tool writes the artifact itself from the facts you pass. Code, CSVs and
data exports still go in files.

Gather the facts first (tools, memory, the conversation), then call it once with:
- kind: dashboard (metrics, trends, funnels, boards), report (findings and a
  recommendation), plan (steps, owners, dates), comparison (options side by side),
  memo (a short decision note) or document (anything else).
- title: the artifact's title, in the user's words where they gave one.
- brief: every fact the artifact needs, verbatim from tool results and memory: numbers,
  series, names, dates, quotes and source URLs, plus the one-line message it should land.
  Pass the numbers as the sources state them and never add ones you worked out (totals,
  differences, shares, averages): the artifact computes those from the data itself, and
  it can only state numbers the brief contains. Include complete data series rather than
  summaries of them.

- interactive: true only when the user asked for something to play with (a calculator,
  a mortgage or pricing simulator, a small tool); use kind document for those.

The result says whether the artifact was made and gives its link; hand the link to the
user. On failure it says why; do not retry with the same brief.
"""
