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
provider-side flakiness — both of those earlier hypotheses were measured and
disproved. The shadow test settled it: replaying the graph's exact captured
request bytes seconds after the live call hits 99.5% while the live call
itself reported 80% — the cache is a byte-prefix cache working exactly as
specified, and the live hit rate is the shared-prefix fraction. The per-turn
byte divergence has two measured sources:

1. **The memory-recall slot churns inside the cached prefix.** The volatile
   slot is rebuilt every turn; its tail (recent-activity journal + tracked
   todos) changed bytes every turn — the journal's sliding last-6 window
   shifted every emitted entry each time a new one landed. The comms'
   shared-with-previous-turn prefix was capped at ~18k (static + docs) while
   the request grew to 23k+. **Fixed**: the journal is now anchored
   (append-only) — shared-with-previous-turn went 50% → 74%, and the comms'
   cached prefix now grows with the conversation instead of staying flat.
2. **Concurrent same-provider requests wipe each other's chains mid-read.**
   The memory extraction is a fire-and-forget background task that overlaps
   the next turn's requests. A/B on the same lane: the comms chain collapsed
   to 0/72.6% under a concurrent alias-lane extraction and held 99.5%+ under
   a concurrent Gemini extraction. **Fixed**: the memory pipeline runs on
   direct Gemini — a different provider has no shared cache store.

The layout's demonstrated 94.9% ceiling (the harness uses byte-stable slots)
is reachable once the volatile tail stops churning inside the prefix; the
remaining lever is moving the recall slot's newest entries + todo statuses
after the time message so the prefix extends through the stable core.

Two follow-up fixes in this PR close the biggest measured gaps:

- **Sticky model fallback** — when the primary fails and the fallback serves
  the call, the request's `model` field flipped per call (primary → fallback →
  primary → …) and the per-model cache could never chain. Once a run falls
  back, later calls use the fallback directly.
- **Aux calls get their own cache namespace** — the follow-up and other
  one-shot calls now run under a different id (`AUX_MODEL_NAME`), so their
  ~30k tokens/turn of new blocks can no longer evict the conversation from its
  namespace. Note this is a genuinely different model, not an alias of the
  same weights: OpenRouter serves `deepseek/deepseek-v4-flash` as "V4 Flash
  0423" (Apr 2026) and `…-0731` as "V4 Flash 0731" (Jul 2026), at different
  rate cards. There is no second id resolving to 0731, so a separate namespace
  and the newer revision cannot both be had on this provider — the aux lane
  trades model version for isolation, deliberately.
  The memory pipeline is NOT covered by this: a separate id on the same
  provider was measured and did not hold (see the concurrency finding above),
  which is why it runs on direct Gemini instead.

Real-graph runs measure **76.3%** on the 15-turn driver (up from the 70.5%
baseline), with the comms at 83–91% per turn and the cached prefix growing
through the conversation (20.2k → 24.8k). The mechanism, finally isolated
and fixed: OpenRouter routes each request to the provider holding the warm
cache when the request carries a ``session_id`` (sticky routing, forced
from the FIRST request) — measured 0/100/99/99/99/99/99 on an isolated
growing conversation with the session_id alone. Explicit provider routing
was measured WORSE (sort:price 35.6%, first-party pin conflicts) and was
removed. The residual gap to 99% is the per-turn content that SHOULD
change: the new turn's messages, the volatile tail (~370 tokens), and the
follow-up one-shot (~2k at its ~65% ceiling because its per-turn context
churns) — plus occasional provider-side flakes (2 turns in 15).

**History — the first `session_id` attempt, and why the shipped one differs.**
An earlier revision pinned the conversation id on *every* request including
the aux one-shots, via a post-`bind_tools` bind, wire-verified at 100%
coverage. That A/B measured **no benefit (64.2% pinned vs 70.5% unpinned)**
and was reverted: sharing one session across the conversation AND its aux
calls fragments the byte-identical ~19k system prefix across per-conversation
upstreams, so a new conversation starts cold (turn 0: 0% cached pinned vs 79%
unpinned, the unpinned run hitting a warm upstream's copy of the shared
prefix).

**What ships is not that.** The aux one-shots now carry their own suffixed
session (`{session_id}-aux`, see `_aux_structured_runnable`) precisely so they
cannot re-pin the conversation's provider, and the sticky-flip retry recovers
the cold-flip case rather than relying on the pin alone. Measured best on the
real full graph in that shape — 82.2% total, 83–88% steady-state (recorded
against `DEFAULT_MODEL_NAME` in `app/constants/llm.py`). The reverted variant
is kept here so the *shared-session* version is not re-attempted without new
data; it is not a statement about the shipped one.

This PR also bounds the aux calls' cache footprint so the fix is in place
when the request count drops: the volatile memory-recall slot is capped at 8k chars
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
