---
name: lab-claude-drive
description: Install, log in, and drive Claude Code headlessly inside the sandbox (OAuth paste-back, stream-json drive, resume/stop). Read before any bash that touches the claude CLI.
target: executor
---

# Claude Code in the Sandbox

Drive the CLI directly via bash. Do not invent flags; confirm with `claude --help` when unsure.

## Install (pinned, user-writable prefix)

```bash
export PATH="/workspace/.local/bin:$PATH"
command -v claude >/dev/null 2>&1 || curl -fsSL https://claude.ai/install.sh | bash -s 2.1.286
```

npm alternative (needs Node >= 22): `npm install -g --prefix /workspace/.local @anthropic-ai/claude-code@2.1.286`.
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

```bash
unset ANTHROPIC_API_KEY
claude -p "<prompt>" --output-format stream-json
```

Useful flags: `--verbose --include-partial-messages` (token streaming), `--input-format text|stream-json`, `--continue` / `--resume [session-id]` / `--session-id <uuid>` / `--fork-session`, `--allowedTools`, `--permission-mode`, `--append-system-prompt`, `--mcp-config`, `--max-budget-usd`. With unattended runs, denials surface as `permission_denied` system messages in stream-json.
Background: `claude agents --json` lists (`--json` is REQUIRED headless; bare
`claude agents` refuses without a TTY), `claude attach <id>` / `claude logs <id>` / `claude stop|kill <id>` (keeps conversation) / `claude rm <id>`.

## Continue a session (after pause/resume or sandbox recreate)

Always start runs with an explicit id and record it on the todo:

```bash
claude -p "<prompt>" --output-format stream-json --session-id <uuid>
```

Re-enter later with `claude -p --resume <uuid> "<follow-up>"` (`-p` is REQUIRED;
bare `claude --resume` opens an interactive session that hangs headless, and
`--continue` is interactive-only the same way). For the most recent session,
`claude -p --continue "…"`. Session transcripts live beside credentials under `~/.claude/`, so the whole-dir symlink above already covers them for pause/resume AND template recreate. After a recreate, verify with `claude agents` before resuming; if the session is gone, re-anchor by starting a fresh run pasting the todo's log tail as context. Never assume `--continue` reaches the right session when several runs exist — prefer explicit `--resume <uuid>`.

## Stop

Foreground `claude -p`: SIGTERM (exit 143; SessionEnd hooks run). Background: `claude stop <id>`. UNVERIFIED: SIGTERM behavior is docs-only, never signal-tested here.
