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
| Cache hit rate | 41.4% | **63.4%** |
| Steady state (later turns) | ~45% | **80–85%** |
| Input cost | $0.1647 | $0.1598 |

The e2e delta is real but capped by a measured mechanism, not a layout
defect: the provider's prompt cache retains only a small window of recent
*request entries*, and every graph call that hits its own chain (the executor's
3–9 calls per turn at 20–26k tokens, the memory-extraction/follow-up calls)
occupies a slot. Between two comms calls the graph runs 5–15 such requests,
so the comms conversation's entry is evicted before the next turn reads it —
the comms hits collapse to the static prefix. This was established by
byte-level capture of the real requests (the shared prefix is byte-identical;
identical re-sends hit 100%) and by interleave probes: requests that never
match anything (unique junk) do NOT evict the chain even at 112k tokens/turn,
while the graph's own matching traffic does. Pinning the first-party DeepSeek
lane (the paid path) measured *worse* on this key (19% vs 58% on the probe).

The follow-up fix in this PR — a **sticky model fallback** — addresses the
second measured killer: when the primary model fails and the fallback serves
the call, the request's `model` field flips per call (primary → fallback →
primary → …) and the per-model cache can never chain. Once a run has fallen
back, later calls use the fallback directly; the real-graph run then measures
**63.4%** with later turns at 80–85%.

This PR also bounds the aux calls' cache footprint so the fix is in place
when the request count drops: the memory-extraction transcript is capped at
10k chars (was 24k) and the volatile memory-recall slot at 8k chars
(head+tail), cutting ~30k tokens/turn of new cache blocks. The remaining
lever to unlock the layout's demonstrated 95% ceiling in the real graph is
reducing the number of requests between comms calls — batching the
memory-pipeline calls (extraction/reconcile/consolidate run 2× per turn, once
per agent thread) and/or the executor's per-turn loop — a memory/agent
pipeline change, not a cache-layout one.

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

## How it was measured

A live harness drove graph-shaped conversations (real `manage_system_prompts_node`,
real provider, per-run isolated bytes) for the layout A/B, and the real
`/api/v1/chat-stream` endpoint was driven for the end-to-end runs. Requests
were captured byte-level through a logging proxy to verify determinism and
the exact divergence points.
