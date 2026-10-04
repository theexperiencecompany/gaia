---
name: lab-opencode-drive
description: Install, authenticate, and drive the OpenCode CLI headlessly inside the sandbox (Zen/API-key auth, run --format json, resume/stop). Read before any bash that touches the opencode CLI.
target: executor
---

# OpenCode in the Sandbox

Drive the CLI directly via bash. Do not invent flags; confirm with `opencode --help` when unsure.

## Install (pinned, user-writable prefix)

```bash
export PATH="/workspace/.local/bin:$PATH"
command -v opencode >/dev/null 2>&1 || curl -fsSL https://opencode.ai/install | bash
```

UNVERIFIED: pinning method and v1/v2 package naming (`opencode-ai` vs `@opencode/cli`; probed local version is v2.0.2 via `@opencode/cli@2.0.2`). Resolve with `--help` / docs before pinning in automation. `opencode upgrade [target]` exists for updates.

## Auth (Zen key paste-back)

```bash
opencode auth login [target] [--method <label>]
```

Zen flow: `/connect` in the TUI (or the login command) signs in at `opencode.ai/auth`, then paste the API key back into the terminal. This paste-back is headless-friendly by design.
Credential lands at `~/.local/share/opencode/auth.json` (i.e. `$XDG_DATA_HOME/opencode/auth.json`; if `XDG_DATA_HOME` is set the whole tree moves — symlink the resolved dir). Symlink the WHOLE data dir for persistence (sessions live in `opencode.db` beside it — an `auth.json`-only symlink loses sessions on recreate):

```bash
mkdir -p /workspace/.credentials/opencode
ln -sfn /workspace/.credentials/opencode ~/.local/share/opencode
```

UNVERIFIED: exact per-provider entry schema inside `auth.json` (never dumped; secret-adjacent) and whether Zen auth has a browser-callback step or is pure key-paste. Probe with `auth login --method` and a real account before scripting it. `opencode auth list|logout|switch` and `opencode mcp auth [name]` (MCP-server OAuth, separate surface) also exist.

## Drive

Run from the user's repo. `OPENCODE_CONFIG_DIR` (injected by `bash run_todo_id`) loads the run's notify plugin, so OpenCode reports back from any working directory:

```bash
cd /workspace/<repo> && opencode run --format json -m <provider/model> "<message>"
```

`--format json` emits line-delimited JSON events; verified types include `{"type":"text","part":{"text":"..."}}` and `{"type":"step_finish",...}` (anything else needs a live capture).
Useful flags: `-m/--model provider/model`, `--agent`, `-c/--continue`, `-s/--session <id>`, `--fork`, `--share`, `-f/--file`, `--title`, `--dir`, `--auto` (auto-approve non-denied permissions). Resume via `run -c` / `run -s <id>` / `--fork`; `opencode session list|delete|export|import` manages saved sessions.
Optional long-running mode: `opencode serve` (headless HTTP API; `OPENCODE_SERVER_PASSWORD` for basic auth) plus `opencode run --attach <url>` per message to avoid MCP cold-boot per run.

## Continue a session (after pause/resume or sandbox recreate)

Find the session id in the run's output (`opencode session list` also shows saved ones; all `ses_`-prefixed, and `-s` REJECTS ids without the prefix) and write it on the todo's canvas. A later bash call gets no env injected, so source the run env first or the plugin stays silent. Resume with `bash(..., background=True)` and finish your turn: a foreground resume is killed at the bash timeout, and the resumed agent's own idle event is what wakes the todo next:

```bash
set -a; . /workspace/.gaia/lab/<run>/.gaia/lab-env; set +a
cd /workspace/<repo> && opencode run --format json -s <ses_id> "<follow-up>"
```

`--format json` is required; bare `run -c` opens the interactive TUI. Prefer explicit `-s <ses_id>` over `-c` whenever several runs exist. Session data (`opencode.db`) lives beside `auth.json`, so the whole-dir symlink above covers pause/resume AND recreate. After a recreate, run `opencode session list` first; if the session is gone, start a fresh run seeded from the todo's log tail.

## Stop

`opencode run` is one-shot: process exit is the stop. A `serve` backend stops via SIGTERM to the server process. UNVERIFIED: never signal-tested here; confirm exit codes and partial-output guarantees in a live probe.
