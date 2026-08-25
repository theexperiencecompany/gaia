"""Docstrings for the URL-download tool."""

DOWNLOAD_TOOL = """
Download a file from a public URL into the workspace and return its path.

For fetching a binary or data file the user points you at (an image, PDF, CSV,
audio clip, archive) so you can then work with it. The file is saved under the
session's `downloads/` directory; the tool returns the workspace path, and you
`read` that path (images come back as pixels you can see, text as text) or open
it with `bash`.

Use this instead of guessing at a file's contents from its URL, and instead of
`bash curl`: this path is faster (it never spins up the sandbox) and it enforces
the size and safety limits `curl` would not.

NOT for web pages. A normal article or HTML page is `fetch_webpages`, which
renders it to readable text; `download` refuses `text/html` and points you there.

Only works for URLs that serve the file directly. A link behind a login (a
private Google Drive / Slack / Notion file) returns a sign-in page, not the file;
reach for the matching integration tool instead.

Args:
    url (str): The direct, public http(s) URL of the file.

Returns:
    The workspace path the file was saved to, e.g.
    `/workspace/sessions/<conv>/downloads/download-<hash>.png`.
"""
