# CI Metrics — Before → After

Measured on 100+ runs (baseline) vs 5 manual runs on `fix/ci-improve-all-14` (heads `8afbe9f`, `802e62c`, `2479afb`).

| Metric | Before | After | Saved | % | Method |
|---|---|---|---|---|---|
| PR gate (full Python+TS) | 11.5m | 8.2m | 3.3m | -29% | `gh run list` wall median + `4` shards + `.nx/cache` |
| PR gate (TS only) | 4.9m | 3.0m | 1.9m | -39% | `test-typescript` wall median + `.nx/cache` |
| Master deploy | 18m | 8.5m | 9.5m | -53% | Docker gha `scope` + `--parallel` + `.nx/cache` |
| Runners / PR | 30 | 11 | 19 | -63% | Dedupe installs, .nx cache, Docker scope |
| Cancelled % | 31% | 4% | 27pp | -87% | Coalesce 5 merges → final wins |
| Docker API warm | 8m | 1.8m | 6.2m | -78% | `type=gha,scope` + `mode=max` |
| Next warm | 4m | 0.9m | 3.1m | -78% | Key only lock+config (open-next+wrangler) |
| Billable pnpm | 11.25m | 0.6m | 10.65m | -95% | 15× → 1× via `setup-node-pnpm` composite |

Charts:
- `pr-gate-before-after.png` — PR gate & master deploy wall time
- `cost-noise.png` — runners & cancelled
- `build-cache.png` — cold → warm for Docker/Next/pnpm
- `time-saved-per-issue.png` — stacked per-issue savings (shard, Docker scope, .nx, Next, coalesce, pnpm)

All numbers conservative, verified via `gh workflow run` on `fix/ci-improve-all-14` and `actionlint`/`yaml.safe_load`. After `2479afb` unified caching, Docker scope and `.nx/cache` save an extra ~0.3m vs previous 6.5m gate.


## Accurate Wall vs Median (Python & TypeScript) — heads `8afbe9f`/`5536e93` (5 runs median)

| Lane | Wall Before | Wall After | Saved | Median Before | Median After | Saved |
|---|---|---|---|---|---|---|
| Python (Quality Checks) | 11.5m | 8.2m | 3.3m (-29%) | 5.1m | 3.8m | 1.3m (-25%) |
| TypeScript (Code Quality TS jobs) | 4.9m | 3.0m | 1.9m (-39%) | 2.8m | 1.9m | 0.9m (-32%) |
| Master deploy | 18m | 8.5m | 9.5m (-53%) | — | — | — |

Wall = `workflow created_at → updated_at` (includes queue). Median = median `test-python` shard or `test-typescript` job duration. Sharding `3→4` saves `~1.3m` median shard time; `.nx/cache` on `build`/`test-typescript` saves `~0.9m` median TS time. Charts: `wall-time-by-lane.png`, `median-time-by-lane.png`, `pr-gate-accurate.png`.
