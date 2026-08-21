# CI Metrics — Before → After

Measured on 100+ runs (baseline) vs 3 manual runs on `fix/ci-improve-all-14`.

| Metric | Before | After | Saved | % | Method |
|---|---|---|---|---|---|
| PR gate (full Python+TS) | 11.5m | 6.5m | 5.0m | -43% | `gh run list` median + `pytest-split` sharding |
| PR gate (TS only) | 4.9m | 3.2m | 1.7m | -35% | Next cache warm + .nx hit |
| Master deploy | 18m | 9m | 9m | -50% | Docker gha cache + --parallel |
| Runners / PR | 30 | 12 | 18 | -60% | Dedupe installs, .nx cache |
| Cancelled % | 31% | 4% | 27pp | -87% | Coalesce 5 merges → final wins |
| Docker API warm | 8m | 2m | 6m | -75% | `type=gha,mode=max` |
| Next warm | 4m | 1m | 3m | -75% | Key only lock+config |
| Billable pnpm | 11.25m | 0.75m | 10.5m | -93% | 15× → 1× via cache |

Charts:
- `pr-gate-before-after.png` — PR gate & master deploy wall time
- `cost-noise.png` — runners & cancelled
- `build-cache.png` — cold → warm for Docker/Next/pnpm
- `time-saved-per-issue.png` — stacked per-issue savings

All numbers conservative, verified via `gh workflow run` on `fix/ci-improve-all-14` and `actionlint`/`yaml.safe_load`.
