---
name: opencode-run-task
description: Install, authenticate, and drive the OpenCode CLI headlessly inside the sandbox (Zen/API-key auth, run --format json, resume/stop). Read before any bash that touches the opencode CLI.
target: executor
---

# OpenCode in the Sandbox

Drive the CLI directly via bash. Do not invent flags; confirm with `opencode --help` when unsure.

## Install (part of every launch line)

The run setup installs nothing; start every launch with this. The installer puts the binary in `~/.opencode/bin` (local disk, about 4s on a fresh sandbox, skipped when present); the sandbox profile already has it on PATH:

```bash
command -v opencode >/dev/null 2>&1 || curl -fsSL https://opencode.ai/install | bash
```

The installer is unpinned (it installed 1.18.34 in the sandbox on 2026-10-04). The notify plugin handles both the 1.x and 2.x plugin APIs.

## Auth (Zen key paste-back)

```bash
opencode auth login [target] [--method <label>]
```

Zen flow: `/connect` in the TUI (or the login command) signs in at `opencode.ai/auth`, then paste the API key back into the terminal. This paste-back is headless-friendly by design.
Credentials land in `~/.local/share/opencode/auth.json`, which the run setup links to `~/agents/state/opencode` on local disk (never set `XDG_DATA_HOME`, it moves the tree off the link). Sessions live in `opencode.db` beside it; gaia-save packs both into `/workspace/agents/home.tgz` before every event, the database as a consistent SQLite backup, so a replaced sandbox gets them back. An API-key login is `{"<provider>": {"type": "api", "key": "..."}}` in `auth.json` (verified: `opencode auth list` shows it).

UNVERIFIED: whether Zen auth has a browser-callback step or is pure key-paste. Probe with `auth login --method` and a real account before scripting it. `opencode auth list|logout|switch` and `opencode mcp auth [name]` (MCP-server OAuth, separate surface) also exist.

## Drive

Run from the project's folder under `~/agents/work` (local disk: fast; saved with every event). `OPENCODE_CONFIG_DIR` (injected by `bash run_todo_id`) loads the sandbox's notify plugin, which saves the agents' home and then reports to GAIA, so OpenCode reports back from any working directory:

```bash
mkdir -p ~/agents/work/<project> && cd ~/agents/work/<project> && opencode run --format json -m <provider/model> "<message>"
```

`--format json` emits line-delimited JSON events; verified types include `{"type":"text","part":{"text":"..."}}` and `{"type":"step_finish",...}` (anything else needs a live capture).
Useful flags: `-m/--model provider/model`, `--agent`, `-c/--continue`, `-s/--session <id>`, `--fork`, `--share`, `-f/--file`, `--title`, `--dir`, `--auto` (auto-approve non-denied permissions). Resume via `run -c` / `run -s <id>` / `--fork`; `opencode session list|delete|export|import` manages saved sessions.
Optional long-running mode: `opencode serve` (headless HTTP API; `OPENCODE_SERVER_PASSWORD` for basic auth) plus `opencode run --attach <url>` per message to avoid MCP cold-boot per run.

## Continue a session (after pause/resume or sandbox recreate)

Find the session id in the run's output (`opencode session list` also shows saved ones; all `ses_`-prefixed, and `-s` REJECTS ids without the prefix) and write it on the todo's canvas. A later bash call gets no env injected, so source the run env first or the plugin stays silent. Resume with `bash(..., background=True)` and finish your turn: a foreground resume is killed at the bash timeout, and the resumed agent's own idle event is what wakes the todo next:

```bash
set -a; . ~/agents/runs/<run>/lab-env; set +a
cd ~/agents/work/<project> && opencode run --format json -s <ses_id> "<follow-up>"
```

`--format json` is required; bare `run -c` opens the interactive TUI. Prefer explicit `-s <ses_id>` over `-c` whenever several runs exist. Session data (`opencode.db`) lives in `~/agents/state/opencode`: a pause keeps it, and a replaced sandbox restores it from the last save (the `sandbox_replaced` event says which). After a replacement the old run's process is gone: relaunch the resume through `bash(..., background=True, run_todo_id=<todo>)` (fresh run env and subscription) instead of sourcing. Run `opencode session list` first; if the session is gone, start a fresh run seeded from the todo's log tail.

## Stop

`opencode run` is one-shot: process exit is the stop. A `serve` backend stops via SIGTERM to the server process. UNVERIFIED: never signal-tested here; confirm exit codes and partial-output guarantees in a live probe.
