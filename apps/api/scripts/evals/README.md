# GAIA Eval Harness

Autonomous, provider-rotating, journal-resumable evals for the GAIA agent.
Every run produces an append-only journal, a self-contained HTML report, and
an Opik experiment.

## Quick start

```bash
# 1. Opik (isolated stack — UI at http://localhost:5173)
mise eval:opik:up

# 2. Run a suite
cd apps/api
uv run --group backend python -m scripts.evals run --suite smoke     # 3 toy cases
uv run --group backend python -m scripts.evals run --suite memory --limit 10
uv run --group backend python -m scripts.evals run --suite capability
uv run --group backend python -m scripts.evals run --suite quality
uv run --group backend python -m scripts.evals run --suite gaia_bench
uv run --group backend python -m scripts.evals run --suite longmemeval
uv run --group backend python -m scripts.evals run --suite regression --sim   # free, stub-driven gate

# 3. Resume an interrupted run (skips completed cases)
uv run --group backend python -m scripts.evals run --suite memory --resume memory-20260807-231807-34b2a9

# 4. Reports / cost
uv run --group backend python -m scripts.evals report <run-id>   # writes report.html + summary.md
uv run --group backend python -m scripts.evals cost --project    # per-suite spend + forecast

# 5. Verdicts from journals already on disk — no model, no API, no cost
uv run --group backend python -m scripts.evals compare <run-id>              # exits 1 on a regression
uv run --group backend python -m scripts.evals compare <run-id> --rebaseline # record it as the bar
uv run --group backend python -m scripts.evals rescore <run-id>              # re-grade after a gate fix
uv run --group backend python -m scripts.evals flaky                         # cases that flip
```

`compare` refuses to baseline a run that is `excluded` or did not finish — an
outage's numbers must never become the bar every later run is judged against.

mise tasks: `eval:opik:up|down|reset`, `eval:smoke`, `eval:gate`, `eval:all`
(nightly set), `eval:week` (weekly set), `eval:cost`, `eval:report`.

## Suites

| Suite | What it measures | Transport | Cost |
|---|---|---|---|
| `smoke` | harness plumbing (rotation, journal, report) | fake | $0 |
| `regression` | deterministic tool-flow gate | real executor graph + scripted stub | $0 |
| `memory` | 45-scenario memory benchmark (10 weakness categories) | in-process real pipeline | flash-class |
| `longmemeval` | 500-question LongMemEval oracle (LLM judge) | in-process real pipeline | flash-class |
| `capability` | 41 cases, 9 families incl. hard tier (composition, temporal, conflict, ambiguity, precision, injection) + simulated gmail | real executor graph, real LLM | flash-class |
| `quality` | 18 transcripts — structural (bubbles, tool cards, suggestions, OpenUI) + rubric judge | live API `chat-stream` | flash-class |
| `comms` | 32 cases — comms agent routing & honesty: delegate vs small-talk, ask-don't-guess, context carry, no fabrication | live API `chat-stream` | flash-class |
| `safety` | 34 cases — chat injection, exfiltration via tool args, jailbreaks, moderation, refusal consistency + over-refusal | live API `chat-stream` | flash-class |
| `hil` | 20 cases — real approval gate (pause / approve / deny / auto) end-to-end + comprehension of underspecified/contradictory/multi-step | live API `chat-stream` + `/approvals` | flash-class |
| `gaia_bench` | official GAIA benchmark (validation 165, gated — needs `HF_TOKEN`) | live API executor | flash-class |

## Providers & rotation

`config.toml` is the provider catalog ("the checkbox"). Default order:
**nous → opencode-go → openrouter → gemini**. The harness health-checks each
provider at boot, skips dead ones, re-runs a case on the next provider when a
provider errors, and rotates when a provider's `budget_usd` cap is hit (nous
defaults to $5). Every case records the provider + model that actually served
it. `--providers a,b` / `--exclude x` override per run.

Judge model (rubric metrics, LongMemEval): DeepSeek via the configured judge
lane (`config.toml [judge]`, default opencode-go `deepseek-v4-pro`) — a
different family than the agent's model, per judge-bias research.

## Tokens & cost

Every run ends with a per-provider token + USD table. `--max-usd` is the hard
run cap. The custom lanes (nous / opencode-go) reject langchain's default
`json_schema` structured output and explicit `tool_choice` — the memory suite
forces `method="json_mode"` (both gateways accept `response_format:
json_object`). Live-API suites (quality, gaia) estimate tokens from
transcripts (the endpoint exposes no usage); in-process suites meter real
usage through the app's callback seam.

## Config & env

- `apps/api/.env` — provider keys (`NOUS_*`, `DEV_LLM_*` = opencode-go lane).
- `scripts/evals/.env.opik` (gitignored) — Opik URL/key.
- `EVALS_DEV_API_BASE` (default `http://localhost:9460`) — live-API suites
  need the API running with `DEV_AUTH_BYPASS_EMAIL` + `DEV_UNLIMITED_RATE_LIMITS=1`
  (the eval user would otherwise hit the free plan's 200 chat messages/day).
- `EVALS_CASE_TIMEOUT_S` (default 300) — per-case deadline for SSE transports.

## Adding a case

YAML in `data/<suite>/` following the schema in the suite's docstring:
ground truth = expected conversation constraints (`communicate`), expected
tool calls (`tool_calls`), DB end-state (`end_state`), and `judge.criteria`
rubrics. Gates (`score.gates`) decide pass/fail — any trajectory reaching the
right end state and saying the right things passes (τ-bench semantics).

## Baselines

`baselines/*.json` hold the measured numbers; the regression gate compares
against them. Re-baselining is a deliberate commit, never auto-adopted.

## Known gaps

- GAIA real validation run: blocked on `HF_TOKEN` (gated dataset terms).
- OpenRouter/Gemini rotation lanes: need `OPENROUTER_API_KEY` /
  `GOOGLE_API_KEY` in `.env`.
- Calendar/messaging simulated backends: not yet built (gmail seam is).
