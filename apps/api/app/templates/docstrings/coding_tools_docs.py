"""Docstrings for the persistent coding tools (bash / read / write / edit).

All four tools operate inside the user's persistent E2B sandbox. The
sandbox's `/workspace` is backed by Cloudflare R2 via JuiceFS, so files,
installed packages, and any state created by the agent survive across
conversations.
"""

BASH_TOOL = """
Run a shell command inside the user's persistent coding sandbox.

The command runs in your session's working directory by default. The
sandbox has Python, Node.js, and common Linux tools. Anything you install
via `pip install` or `npm install` persists across conversations because
the workspace is on a durable filesystem. The sandbox user has no `sudo`
and cannot install system packages — use the language-level package
managers instead.

Path conventions inside your session:
- Relative paths resolve against your session root. Put intermediate work in
  `./scratch/`.
- Files in `./user-uploaded/` are user-attached and read-only — copy them to
  `./scratch/` before modifying.
- Anything you place in `./artifacts/` is shown to the user in the chat
  UI: HTML, Markdown, and images render inline; other types appear as
  download cards.
- `./GUIDE.md` (and `/workspace/INDEX.md`) document the conventions in full;
  `cat` them when you need a refresher.

USE FOR:
- Running scripts: `python solve.py`, `node index.js`
- Installing packages: `pip install pandas`, `npm install lodash`
- Filesystem inspection: `ls`, `tree`, `find`, `grep`
- Git operations: `git clone …`, `git status`, `git diff`
- Quick one-liners and pipelines that don't fit `read`/`write`/`edit`

DO NOT USE FOR:
- Reading a single file when you just want to see it (use `read`)
- Writing a whole file (use `write`)
- Modifying part of a file (use `edit`)
- Interactive commands that need a TTY (will hang)

PARAMETERS:
- command (str): The shell command to run. Use `bash -c "…"` for pipelines.
- cwd (str): Working directory; defaults to your session root. Must be
  inside the workspace unless inspecting system paths.
- timeout (int): Max seconds before the command is killed. Default 300, max 1800.
- background (bool): If true, runs the command detached and returns a `pid`
  plus a log path the agent can `tail` later. Useful for servers, watch
  processes, anything long-running.

OUTPUT:
A formatted string with `exit_code`, the stdout, and the stderr (capped at
~20 KB; full output is also written to `/workspace/.gaia/runs/{run_id}.log`).
Background commands return `{pid, log_path}` instead.

EXAMPLES:
✅ bash("ls -la")
✅ bash("pip install requests && python -c 'import requests; print(requests.__version__)'")
✅ bash("python script.py", cwd="/workspace/project", timeout=60)
✅ bash("python server.py", background=True)  # returns {pid, log_path}
"""

READ_TOOL = """
Read a file from the persistent workspace.

Returns the file's contents with line numbers (cat -n style). Use this to
inspect code you've written, uploaded files, or data. The file must be inside
the workspace.

PARAMETERS:
- path (str): Workspace path. Relative paths resolve against your session
  root (e.g. `user-uploaded/data.csv`, `scratch/out.txt`); absolute paths
  also work.
- offset (int): Optional starting line (1-indexed). Default 0 = start of file.
- limit (int): Max lines to return. Default 2000.

OUTPUT:
File contents with `   1\\tfirst line\\n   2\\tsecond line\\n …` formatting.
If the file is larger than `limit` lines, a footer indicates the remaining
range so you can call again with `offset`.

EXAMPLES:
✅ read("script.py")
✅ read("data/large.csv", offset=1000, limit=200)
"""

WRITE_TOOL = """
Write content to a file in the persistent workspace, overwriting if it exists.

Creates parent directories as needed. Refuses to write outside the workspace.
Use `edit` if you want to change part of an existing file — `write` always
replaces the whole file.

PARAMETERS:
- path (str): Workspace path. Relative paths resolve against your session
  root. Writing into `./user-uploaded/` is rejected (read-only) — copy to
  `./scratch/` first.
- content (str): Full file contents.

EXAMPLES:
✅ write("script.py", "print('hello')\\n")
✅ write("data/config.json", '{"key": "value"}')
✅ write("artifacts/report.html", "<h1>Done</h1>")

Files written under `./artifacts/` are surfaced to the user through the
chat UI — HTML, Markdown, and images render inline; other types appear as
download cards.
"""

EDIT_TOOL = """
Replace a string inside an existing file in the workspace.

The replacement is exact: `old_string` must appear verbatim in the file. By
default it must appear exactly once — set `replace_all=True` to replace every
occurrence (e.g. renaming a variable).

PARAMETERS:
- path (str): Path to an existing workspace file. Relative paths resolve
  against your session root. Editing `./user-uploaded/` is rejected
  (read-only) — copy to `./scratch/` first.
- old_string (str): The exact text to replace. Include enough context to make
  it unique.
- new_string (str): Text to substitute. May be empty (to delete the match).
- replace_all (bool): If true, replaces every occurrence. Default false.

ERRORS:
- "File not found" — path doesn't exist
- "old_string not found" — verbatim match failed; re-read the file
- "old_string appears N times" — disambiguate by adding context, or pass
  `replace_all=True`

EXAMPLES:
✅ edit("config.py", "DEBUG = False", "DEBUG = True")
✅ edit("script.py", "old_name", "new_name", replace_all=True)
"""

QUERY_JSON_TOOL = """
Query a single JSON or JSONL workspace file: filter, project, sort, count, dedupe, group.

Built for mining files that a tool offloaded (e.g. a large Gmail fetch writes a
JSONL file, one JSON object per line — each line a record). Extracts just what
you need instead of reading the whole file back into context. Read-only.

PARAMETERS:
- path (str): Workspace path to ONE JSON/JSONL file (relative = session root).
- where (list): Filters as [{"field","op","value"}], combined by `match`.
    ops: contains (case-insensitive substring), equals, not_equals, is_true,
    is_false, exists, gt, lt, in (value is in a list-valued field like labels).
    For regex / free-text search, use `grep` instead.
- match (str): 'all' (AND, default) or 'any' (OR) across the filters.
- fields (list): Only return these fields (omit = all fields).
- sort_by (str) + order ('asc'|'desc', default 'desc').
- limit (int): Max records to return (default 50).
- count_only (bool): Return just the number of matches.
- unique_by (str): Dedupe by this field (e.g. "threadId").
- group_count_by (str): Return counts per distinct value (e.g. senders).

OUTPUT:
Matching records as JSONL (one per line), or {"count": N}, or grouped counts.
"(no matches)" when nothing matches. Truncated with a note if very large.

EXAMPLES:
- query_json("gmail/inbox.jsonl", where=[{"field":"from","op":"contains","value":"github"}], fields=["subject","from"])
- query_json("gmail/inbox.jsonl", where=[{"field":"isRead","op":"is_false"}], count_only=True)
- query_json("gmail/inbox.jsonl", sort_by="time", order="desc", limit=5, fields=["subject"])
- query_json("gmail/inbox.jsonl", group_count_by="from")
"""

GREP_TOOL = """
Search a single workspace file for a pattern with grep.

Built for mining offloaded files when you only need the matching lines, instead
of reading the whole file back into context. Read-only; searches ONE file.

PARAMETERS:
- pattern (str): A regular expression (or literal text) to match.
- path (str): Workspace path to ONE file. Relative paths resolve against your
  session root; absolute `/workspace/...` paths also work.
- ignore_case (bool): If true (-i), match case-insensitively. Default false.

OUTPUT:
Matching lines prefixed with their 1-indexed line number (`12:matched text`),
or "(no matches)" when nothing matches. Truncated with a note if very large.

EXAMPLES:
- grep("ERROR", "scratch/run.log")
- grep("invoice", "gmail/inbox_summary.jsonl", ignore_case=True)
"""
