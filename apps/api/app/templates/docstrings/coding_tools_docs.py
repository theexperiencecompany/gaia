"""Docstrings for the persistent coding tools (bash / read / write / edit).

All four tools operate inside the user's persistent E2B sandbox. The
sandbox's `/workspace` is backed by Cloudflare R2 via JuiceFS, so files,
installed packages, and any state created by the agent survive across
conversations.
"""

BASH_TOOL = """
Run a shell command inside the user's persistent coding sandbox.

The command runs in `/workspace` by default. The sandbox has Python, Node.js,
common Linux tools, and `sudo`. Anything you install (pip, apt, npm) persists
across conversations because `/workspace` is on a durable filesystem.

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
- cwd (str): Working directory; defaults to `/workspace`. Must be inside
  `/workspace` unless inspecting system paths.
- timeout (int): Max seconds before the command is killed. Default 120, max 600.
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
inspect code you've written, configuration, or data. The file must be inside
`/workspace`.

PARAMETERS:
- path (str): Absolute or relative path inside `/workspace`.
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

Creates parent directories as needed. Refuses to write outside `/workspace`.
Use `edit` if you want to change part of an existing file — `write` always
replaces the whole file.

PARAMETERS:
- path (str): Absolute or relative path inside `/workspace`.
- content (str): Full file contents.

EXAMPLES:
✅ write("script.py", "print('hello')\\n")
✅ write("data/config.json", '{"key": "value"}')

Files written under `/workspace/.user-visible/` are surfaced to the user
through the chat UI.
"""

EDIT_TOOL = """
Replace a string inside an existing file in the workspace.

The replacement is exact: `old_string` must appear verbatim in the file. By
default it must appear exactly once — set `replace_all=True` to replace every
occurrence (e.g. renaming a variable).

PARAMETERS:
- path (str): Path to an existing file inside `/workspace`.
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
