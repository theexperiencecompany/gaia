# Preview environment GC

`gaia-previewctl` (its own repo, deployed on `gaia-home-server` as user `gaia`)
polls for PRs labeled `staging` and deploys each one. Per preview it creates:

| Artifact | Path / name |
|---|---|
| git worktree of `gaia` (~130 MB) | `~gaia/gaia-staging/.previewctl/runtime/gaia/worktrees/pr-{N}` |
| generated env | `.previewctl/runtime/gaia/generated-env/pr-{N}.env` |
| rendered compose dir | `staging-infra/deploy/pr-{N}/` |
| per-PR Postgres creds | `staging-infra/env/postgres/pr-{N}.env` |
| Traefik dynamic route | `staging-infra/traefik/dynamic/pr-{N}.yml` |
| docker compose project | `gaia-pr-{N}` (containers, volumes, `gaia-staging/{api,web}:pr-{N}-{sha}`) |

Previews are keyed by **PR number**. PR `0` is the always-on `develop` preview
and is never collected.

`previewctl down` tears down the docker side, but the on-disk artifacts — the
worktrees above all — routinely survive. By Aug 2026 that was 26 dead worktrees
/ 3.3 GB for PRs closed months earlier.

## `scripts/ci/preview-gc.sh`

Removes every artifact above for previews whose PR is closed/merged, or older
than `--days N` (default 7). **Dry run by default**; `--apply` acts.

```bash
bash scripts/ci/preview-gc.sh                  # dry run
bash scripts/ci/preview-gc.sh --closed-only    # ignore the age rule
bash scripts/ci/preview-gc.sh --apply --days 14
```

It refuses to run if it cannot list open PRs via `gh`, so a broken token can
never cause it to delete live previews.

## Installed on gaia-home-server

Copied to `/home/gaia/.local/bin/preview-gc.sh` and driven by a systemd **user**
timer under `gaia` (lingering is enabled):

- `~gaia/.config/systemd/user/preview-gc.timer` — `OnCalendar=daily`, `Persistent=true`
- `~gaia/.config/systemd/user/preview-gc.service` — `preview-gc.sh --apply --days 7`

Inspect with:

```bash
sudo -u gaia XDG_RUNTIME_DIR=/run/user/$(id -u gaia) \
  systemctl --user list-timers preview-gc.timer
```

Update the box after changing this script by copying it to
`/home/gaia/.local/bin/preview-gc.sh` (the box does not check this repo out).
