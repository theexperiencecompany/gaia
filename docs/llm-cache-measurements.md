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
| Cache hit rate | 41.4% | **70.5%** (15-turn driver; 72.4% wire-verified) |
| Steady state (later turns) | ~45% | **80–85%** |
| Input cost | $0.1647 | $0.1598 |

The earlier "70–73%" figure was superseded: it came from a measurement run
whose aux-namespace fix was later found to be dead code on the wire (the
alias never reached the requests). After the real wire fix, the honest
figures are 72.4% (wire capture + provider-reported usage, 56 requests) and
70.5% (the 15-turn driver).

The e2e delta is real but the residual gap is NOT a layout defect and NOT
eviction by the graph's own traffic — that earlier hypothesis was measured
and disproved. Controlled probes on the real lane (identical re-sends,
growing chains, changing volatile tails, bound tools, interleaved
follow-up/summarize calls at real sizes, 23k alias-namespace extractions)
all cache at 97–100%, and **replaying the graph's exact captured request
bytes hits 100%**. What actually varies is the provider's cache itself:
the same byte-identical request flaps between ~81% (static prefix only)
and ~99% (full chain) across calls minutes apart — six consecutive turns
of the same driver measured 81/98/79/78/99/98% on the comms call with
identical interleaves, and the identical follow-up request strictly
alternated 0/67/0/69%. The same driver that measured 70.5% at one hour
measured 84.8% (89% comms-only) two hours later with zero code changes.
The layout's demonstrated 94.9% ceiling is reachable whenever the
provider's cache cooperates; the residual is provider-side cache
reliability, not request structure.

Two follow-up fixes in this PR close the biggest measured gaps:

- **Sticky model fallback** — when the primary fails and the fallback serves
  the call, the request's `model` field flipped per call (primary → fallback →
  primary → …) and the per-model cache could never chain. Once a run falls
  back, later calls use the fallback directly.
- **Aux calls get their own cache namespace** — the memory-pipeline and
  follow-up calls now run the same underlying model under a different id
  (`AUX_MODEL_NAME`), so their ~30k tokens/turn of new blocks can no longer
  evict the conversation from its namespace.

Real-graph runs with all fixes measure **70.5%** on a 15-turn driver
(up from 41.4% baseline) — and **84.8% (89% comms-only) on the identical
driver two hours later with zero code changes**. The per-turn pattern is
the provider's flapping cache: the byte-identical comms chain alternates
between ~81% (static prefix only) and ~99% (full chain) across turns;
the extraction chain (alias namespace) holds 92–99% steadily. When the
provider's cache holds the conversation chain, the real graph reaches the
layout's 94.9% ceiling; when it drops the chain, the hits collapse to the
static prefix. The named next step (batching the memory-pipeline/executor
calls) would cut the interleaved request count but is no longer believed
to be the binding constraint — the same interleaves replay at 100%.

**Tested and reverted: OpenRouter `session_id` sticky routing.** The
conversation id was pinned on every request (comms, executor, subagents,
aux) via a post-`bind_tools` bind — wire-verified at 100% coverage. The
A/B on the same 15-turn driver measured **no benefit (64.2% pinned vs
70.5% unpinned)** — OpenRouter's default routing already keeps a client's
requests on the same upstream (turn-to-turn cache continuity was identical
with and without the pin), and the pin has a real cost: it fragments the
shared byte-identical ~19k system prefix across per-conversation upstreams,
so a new conversation starts cold (turn 0: 0% cached pinned vs 79% cached
unpinned — the unpinned run hit a warm upstream's copy of the shared
prefix). Reverted on that evidence; the mechanism is documented here so it
is not re-attempted without new data.

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
