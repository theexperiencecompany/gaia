#!/usr/bin/env bash
# Refuse to boot a linked worktree's dev process without its own .env.worktree loaded.
#
# Without it, the process silently falls back to the main checkout's API port 8000,
# web port 3000 and shared GAIA database, so it talks to, or writes into, another stack.
# Started outside mise (a bare `pnpm dev`, `nx dev web`, `uv run`), the file exists but
# nothing loads it, which fails the same way. The main checkout keeps the defaults.

set -euo pipefail

git_dir="$(git rev-parse --absolute-git-dir)"
common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
[ "$git_dir" = "$common_dir" ] && exit 0

env_file="$(git rev-parse --show-toplevel)/.env.worktree"
if [ ! -f "$env_file" ]; then
  cat >&2 <<EOF
ERROR: this linked worktree has no .env.worktree, so it would use the main checkout's
       ports (8000/3000) and its GAIA database. Create it, then start again through mise:

    mise run wt:env

EOF
  exit 1
fi

own_slot="$(sed -n 's/^GAIA_WT_SLOT=//p' "$env_file")"
if [ -z "$own_slot" ]; then
  echo "ERROR: $env_file predates per-worktree isolation. Regenerate it: mise run wt:env" >&2
  exit 1
fi
if [ "${GAIA_WT_SLOT:-}" != "$own_slot" ]; then
  cat >&2 <<EOF
ERROR: $env_file (slot $own_slot) is not loaded into this process (GAIA_WT_SLOT=${GAIA_WT_SLOT:-unset}).
       Start it through mise, which loads the file (mise dev, mise dev --sim, mise run <task>),
       not with a bare pnpm, nx or uv command, and not from another checkout's shell.
EOF
  exit 1
fi
