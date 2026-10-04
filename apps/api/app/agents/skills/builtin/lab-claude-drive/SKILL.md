---
name: lab-claude-drive
description: Install, log in, and drive Claude Code headlessly inside the sandbox (OAuth paste-back, stream-json drive, resume/stop). Read before any bash that touches the claude CLI.
target: executor
---

# Claude Code in the Sandbox

Drive the CLI directly via bash. Do not invent flags; confirm with `claude --help` when unsure.

## Install (part of every launch line)

The run setup installs nothing; start every launch with this. The installer puts the binary in `~/.local/bin` (local disk, about 11s on a fresh sandbox, skipped when present):

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v claude >/dev/null 2>&1 || curl -fsSL https://claude.ai/install.sh | bash -s 2.1.286
```

UNVERIFIED: `DISABLE_UPDATES` env to stop the native installer's background auto-update inside the sandbox; check docs before relying on it.

## Login (OAuth paste-back)

```bash
unset ANTHROPIC_API_KEY
claude auth login
```

The browser cannot reach the sandbox callback, so it shows a login code instead; paste it at the `Paste code here` prompt. Terminal shows `Login successful`.
Alternative: `claude setup-token` mints a one-year OAuth token; export it as `CLAUDE_CODE_OAUTH_TOKEN`. UNVERIFIED end-to-end (docs-only, never minted here).

Credential lands at `~/.claude/.credentials.json` on Linux (0600). Symlink the WHOLE `~/.claude` dir for persistence (background-job state under `jobs/` and transcripts under `projects/` live beside it — a credentials-only symlink loses sessions on recreate):

```bash
mkdir -p /workspace/.credentials/claude
ln -sfn /workspace/.credentials/claude ~/.claude
```

Rules: `ANTHROPIC_API_KEY` must be unset or `-p` silently uses the key instead of subscription OAuth. Never use `--bare` for OAuth sessions; it never reads OAuth or Keychain and requires an API key.

## Drive

Run from the user's repo. `--settings` loads the run's hooks (from `bash run_todo_id`), so Claude reports back from any working directory:

```bash
unset ANTHROPIC_API_KEY
cd /workspace/<repo> && claude -p "<prompt>" --output-format stream-json --settings "$GAIA_LAB_CLAUDE_SETTINGS"
```

Useful flags: `--verbose --include-partial-messages` (token streaming), `--input-format text|stream-json`, `--continue` / `--resume [session-id]` / `--session-id <uuid>` / `--fork-session`, `--allowedTools`, `--permission-mode`, `--append-system-prompt`, `--mcp-config`, `--max-budget-usd`. With unattended runs, denials surface as `permission_denied` system messages in stream-json.
Background: `claude agents --json` lists (`--json` is REQUIRED headless; bare
`claude agents` refuses without a TTY), `claude attach <id>` / `claude logs <id>` / `claude stop|kill <id>` (keeps conversation) / `claude rm <id>`.

## Continue a session (after pause/resume or sandbox recreate)

Find the session id in the run's events or stream-json output (`session_id`) and write it on the todo's canvas. A later bash call gets no env injected, so source the run env first. Resume with `bash(..., background=True)` and finish your turn: a foreground resume is killed at the bash timeout, and the resumed agent's own Stop event is what wakes the todo next:

```bash
set -a; . ~/.gaia-lab/<run>/.gaia/lab-env; set +a
cd /workspace/<repo> && claude -p --resume <uuid> "<follow-up>" --output-format stream-json --settings "$GAIA_LAB_CLAUDE_SETTINGS"
```

`-p` is REQUIRED: bare `claude --resume` opens an interactive session that hangs headless, and `--continue` is interactive-only the same way. Prefer explicit `--resume <uuid>` over `-p --continue` whenever several runs exist. Session transcripts live beside credentials under `~/.claude/`, so the whole-dir symlink above covers pause/resume AND template recreate. The run folder lives on local disk, so after a sandbox recreate it is gone: relaunch the resume through `bash(..., background=True, run_todo_id=<todo>)` (fresh run env and subscription) instead of sourcing. Verify with `claude agents --json` before resuming; if the session is gone, start a fresh run with the todo's log tail pasted as context.

## Stop

Foreground `claude -p`: SIGTERM (exit 143; SessionEnd hooks run). Background: `claude stop <id>`. UNVERIFIED: SIGTERM behavior is docs-only, never signal-tested here.
