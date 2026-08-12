# Prompt-cache measurements — tail layout vs leading layout

Live A/B measured on the production lane (OpenRouter → `deepseek/deepseek-v4-flash-0731`,
DeepSeek's automatic prefix cache). Two complementary measurements:

1. **Harness** (`apps/api/scripts/measure_llm_cache.py`): real message shapes
   through the real `manage_system_prompts_node` against the real provider,
   back-to-back per-turn calls (what the layout alone is worth).
2. **End-to-end** (`apps/api/scripts/drive_big_conversation.py`): the real
   `/api/v1/chat-stream` endpoint — full comms → executor graph, real history
   growth, 45-turn conversations, ~2.7M input tokens per run (what production
   gets).

## The layouts

- **Before** — volatile prompt slots (`todo_context`, `executor_status`,
  `memory_recall`) sit between the stable `[static, dynamic_stable]` block and
  the conversation history. They churn every turn/step, so the provider's
  byte-prefix cache can never extend past them — the conversation re-sends
  **uncached** every turn.
- **After** — `manage_system_prompts_node` moves the volatile slots **after**
  the conversation (OpenAI-wire providers only; Gemini keeps the leading-block
  layout because its API drops non-leading system messages). The byte-stable
  prefix becomes `[static, dynamic_stable, ...conversation]` and the cached
  prefix grows with the conversation.

## 1. Harness measurement — the layout ceiling

30-turn conversations, identical bytes per scenario (per-run isolated seeds),
only the slot order differs. Same lane, same model, same tool binding.

![Hit rate per turn](https://raw.githubusercontent.com/theexperiencecompany/gaia/pr-assets/997-llm-cache/harness/hit_rate_per_turn.png)

![Uncached per turn](https://raw.githubusercontent.com/theexperiencecompany/gaia/pr-assets/997-llm-cache/harness/uncached_per_turn.png)

![Cumulative cost](https://raw.githubusercontent.com/theexperiencecompany/gaia/pr-assets/997-llm-cache/harness/cumulative_cost.png)

| Metric (30 turns, ~1.19M input tokens each) | Before | After |
|---|---|---|
| Cache hit rate | 35.2% | **94.9%** |
| Hit rate, steady state (turns 20–29) | ~30% | **98.8–99.3%** |
| Input cost | $0.0786 | $0.0273 (**65% cheaper**) |

The before-layout hit rate *declines* as the conversation grows (the static
prefix is a shrinking fraction); the after-layout rate *rises* toward ~99%
(the uncached tail stays ~1–2k tokens while the prompt grows).

## 2. End-to-end measurement — the real graph

45-turn conversations driven through the real chat endpoint (comms → executor,
memory extraction, follow-up actions, tool results) on the same machine and
upstream, before vs after the layout change.

![Hit rate per turn](https://raw.githubusercontent.com/theexperiencecompany/gaia/pr-assets/997-llm-cache/e2e/hit_rate_per_turn.png)

![Uncached per turn](https://raw.githubusercontent.com/theexperiencecompany/gaia/pr-assets/997-llm-cache/e2e/uncached_per_turn.png)

| Metric (45 turns, ~2.7M input tokens each) | Before | After |
|---|---|---|
| Cache hit rate | 41.4% | 50.1% |
| Input cost | $0.1647 | $0.1598 |

The e2e delta is real but modest, and the reason is measured, not guessed:
the graph runs ~4–6 auxiliary LLM calls per turn (memory extraction is 18–21k
tokens alone, follow-up actions ~3k, reconcile/consolidate ~2k — ≈25–30k
tokens/turn). Those calls write new prefix blocks between turns and evict the
conversation chain from the provider's bounded LRU cache before the next turn
reads it. The conversation *does* join the cached prefix (per-turn hits grow
to 25–30k and occasionally 80–99% when the chain survives), but the aux-call
churn caps the average. Trimming the memory-extraction input or batching aux
calls is the follow-up that unlocks the full 95% in the real graph.

## Semantics (verified, not assumed)

- DeepSeek applies system messages that appear after the conversation when a
  leading system message exists; the earliest system message wins conflicts,
  so the static prompt keeps authority (probed live).
- Facts and directives in the tail system slot reach the model (`teal` from a
  tail fact; todo directives followed).
- The cache reports in 128-token blocks (every reported value is
  block-aligned); it is global per key and LRU-evicted, so each scenario run
  uses unique conversation bytes and only measures its own writes.

## What changed

`apps/api/app/agents/core/nodes/manage_system_prompts.py` — provider-aware
layout:

- `openrouter` / `custom` (OpenAI-wire): volatile slots move after the
  conversation → tail layout.
- `gemini`: unchanged leading-block layout (its API silently drops
  non-leading system messages).
- Missing provider: defaults to the leading layout (today's behavior).

## How to re-run

```bash
# Harness A/B (isolated conversation bytes, real lane)
uv run python apps/api/scripts/measure_llm_cache.py --scenario all --turns 30

# End-to-end: boot the API, then one run per layout
uv run python apps/api/scripts/drive_big_conversation.py --tag baseline  # pre-fix code
uv run python apps/api/scripts/drive_big_conversation.py --tag fixed     # post-fix code
uv run --with matplotlib python apps/api/scripts/plot_cache_comparison.py \
    --baseline cache_run_baseline.jsonl --fixed cache_run_fixed.jsonl
```
