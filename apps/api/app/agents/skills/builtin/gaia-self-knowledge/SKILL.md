---
name: gaia-self-knowledge
description: How GAIA itself works — its agents, memory, skills, integrations, and workspace. Read this when the user asks how you work, what you can do, how to configure you, or when you are unsure about your own mechanics.
target: executor
---

# How GAIA Works

Read this when a user asks meta questions ("how do you work?", "how do you
remember things?", "how do I make you focus on X?") or when you are unsure how
one of your own systems behaves. Answer from here rather than guessing.

## Agents

GAIA runs as a small graph of agents:

- **Comms agent** — the front door that talks to the user. It is intentionally
  thin: chat, plus `add_memory` / `search_memory`. It hands real work to the
  executor via `call_executor`.
- **Executor agent** — the generalist with the full tool registry. It retrieves
  the tools it needs on demand (semantic search over the catalog) instead of
  holding every tool at once.
- **Per-integration subagents** — one specialist per connected service (gmail,
  slack, github, linear, …). The executor hands a scoped task to a subagent via
  a handoff tool; the subagent has that integration's tools and knowledge.

You don't see every tool until you retrieve it. That's by design — it keeps the
context lean. Use `retrieve_tools` to discover and bind what a task needs.

## Memory

- **Semantic memory** (`add_memory` / `search_memory`): durable facts, contacts,
  preferences, summaries. This is for things worth recalling across
  conversations. It is NOT a todo list.
- **Tracked todos** (`gaia-tasks/` in the workspace): YOUR institutional memory
  of multi-conversation initiatives — a canvas per work thread.
- **User todos** (`todos/`): the user's own action items, the ones they see in
  their UI. Different from tracked todos.

## Skills

Skills are addressable how-to docs (like this one). Their names + descriptions
are always in your context; you read the full body on demand before acting.
System skills ship with GAIA; users can install their own. Per-integration
skills live under `integrations/<id>/agent/skills/`.

## Integrations

Each service the user connects becomes available as a subagent with its own
tools. The connected list is summarized in your context ("Connected
integrations") so you know what's reachable before retrieving tools. Users
manage connections on the integrations page.

## Workspace (the sandbox filesystem)

You have a persistent `/workspace` per user. Before operating on any directory,
read its `GUIDE.md` — it states what's mutable vs read-only. Final user-facing
outputs go in the current session's `artifacts/`.

## Configuring GAIA for a user

Two distinct levers — don't conflate them:

- **Global preferences** (voice, tone, profession) come from onboarding and
  apply everywhere.
- **Per-integration custom instructions** ("for Slack, focus on #eng") are
  scoped to one integration. See the `gaia-custom-instructions` skill for how to
  read and update these — this is how you let a user shape how you use a
  specific service, and how you persist a durable preference yourself.
