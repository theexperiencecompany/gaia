---
name: ship-feature
description: >
  Autonomously ship a feature end-to-end with zero human intervention: plan it,
  implement it, review it with a team of subagents, boot the full stack, drive
  it in a real browser like a user (agent-browser + the driving-gaia skill),
  capture before/after screenshots, open a PR to develop, and drive CI and
  CodeRabbit to green. Use this skill whenever the user asks to "ship" a
  feature, "one-shot" a feature, build something "end to end", implement
  something "autonomously", take an idea "from spec to PR", or asks for a
  complete feature with PR, screenshots, and passing CI — even if they don't
  name this skill. Also use it when a cloud session is handed a feature
  request and expected to deliver a finished, verified PR without a human in
  the loop.
---

# Ship Feature

**Announce at start:** "I'm using the ship-feature skill to take this feature from request to green PR."

This skill turns a feature request into a merge-ready PR with no human in the
loop. The output is not "code that should work" — it is a PR whose claims are
all backed by evidence: the feature was exercised in a running product, the
screenshots are real captures, CI is green, and every reviewer comment has a
resolution. You orchestrate; subagents do the wide work; other skills own the
mechanics:

| Need | Use |
|---|---|
| Boot the stack, zero-login auth, seed users, drive API/browser/bots, sim LLM | `driving-gaia` skill — the cookbook; don't reinvent any of it |
| Browser driving + screenshots | agent-browser (per driving-gaia §6) |
| A misbehaving run | `reading-gaia-logs` skill |
| The implementation plan | `writing-plans` skill, into `.agents/plans/` |
| CI lanes, local repro, CodeRabbit loop | [references/ci-and-review.md](references/ci-and-review.md) |
| Screenshot protocol + PR format | [references/screenshots-and-pr.md](references/screenshots-and-pr.md) |

## Non-Negotiables

- **Branch from and PR into `develop`.** Never `master`. **Never merge the PR.**
- **Never fake evidence.** No mocked-up screenshots, no "verified" claims for
  paths you did not run. Whatever you could not exercise, the PR says so.
- **No debt as a shipping strategy.** Root-cause fixes, no lint suppressions,
  no stubs, CLAUDE.md discipline at full strength — precisely because nobody
  is watching in real time.
- **Done means green.** The job ends when CI passes, CodeRabbit is answered,
  and the PR is mergeable — or when you are genuinely blocked and have
  reported exactly what blocks you.

## Pipeline

Track each phase as a task and keep statuses current — the task list is how
an absent user sees where the ship is.

### 0. Intake

Turn the request into something falsifiable: (a) concrete acceptance criteria,
(b) the click-path a real user takes through the feature — this becomes the
E2E script and the screenshot shot-list — and (c) the affected surfaces. If
scope is genuinely ambiguous, pick the smallest interpretation with real user
value, state the choice in the plan and PR, and proceed; do not block on
questions nobody is there to answer.

### 1. Bootstrap (start first, runs while you plan)

`git fetch origin develop` and branch from it. Then `pnpm install` and
`uv sync --project apps/api --group backend --group dev`, create env files
(`mise setup:env`, then `cp -f apps/api/.env.example apps/api/.env`; dummy
WorkOS values are fine — the dev bypass never calls WorkOS). Boot per
driving-gaia §1: `mise dev --sim` for deterministic chat flows, `mise dev
--agent` when judging real model behavior, then `mise seed`.

Cloud sandbox note: if the Docker daemon isn't running, start it with
`nohup dockerd --iptables=false --bridge=none &`. If infra ports then aren't
reachable from the host (bridge port-publishing needs IPv4 forwarding, often
disabled in sandboxes), run the infra containers directly with
`--network=host` instead of the compose port map — and move ChromaDB off its
default port 8000 so it doesn't collide with the API.

### 2. Plan, then attack the plan

Explore with code-review-graph tools and parallel Explore subagents per layer.
Read the area rules you'll touch (`apps/web/CLAUDE.md`, `apps/api/CLAUDE.md`,
`DESIGN.md`, chat-bubble/OpenUI CLAUDE.mds). Write the plan with
`writing-plans`. Then spawn one subagent to attack it — architectural fit,
duplication against existing code, simpler alternatives, blast radius —
verifying its claims against the codebase, not just opining. Fold in what
survives. A plan flaw costs minutes here and hours in phase 9.

### 3. BEFORE screenshots

With the stack running **clean base-branch code**, walk the journey script
and capture every surface the feature will change
([references/screenshots-and-pr.md](references/screenshots-and-pr.md)). For a
brand-new surface, "before" is whatever exists today. Never reconstruct a
before-state from memory after the fact — `git stash` if you must.

### 4. Implement

Execute the plan task by task on the feature branch. Write to CI's bars from
the start rather than remediating after: files ≤ 400 lines, ≤ 2 React
components per file, > 3 exported types → `*.types.ts`, xenon complexity
caps, 80% Python docstring coverage, no copy-paste, strict dead-code. HeroUI
first, icons from `@icons`, Sileo toasts. Commit in Conventional-Commit
increments. Do not write new test files unless the user asked (repo rule).

### 5. Local gates

Run the CI-equivalent commands locally before any push
([references/ci-and-review.md](references/ci-and-review.md)). Fix at the
root; auto-fixers first where they exist.

### 6. Review team

Spawn reviewer subagents in parallel on the full diff vs `origin/develop`,
one lens each — correctness (real user-reachable failures, not theoretical
races), architecture/debt (duplication, wrong-layer logic, missed
`libs/shared` reuse, dead code), design-system compliance vs DESIGN.md (UI
diffs only), security (only when the diff adds surface). Each returns
findings with file:line and a concrete failure scenario. Then adversarially
verify: a fresh subagent per finding tries to refute it against the code. Fix
what survives, drop what doesn't — single-pass reviewers confidently report
plausible non-bugs. Re-run affected gates after fixes.

### 7. E2E as a user + AFTER screenshots

Drive the running app through the full journey script with agent-browser
(driving-gaia §6) as the seeded dev user — hot reload has your changes. On
every page: act like the user, exercise the unhappy paths (empty states,
invalid input, the second submit), and check for console errors and failed
network requests (chrome-devtools MCP when you need that introspection; a
feature that renders but errors underneath is not done). Verify data landed
in Mongo, not stdout (driving-gaia §4). Run the existing Playwright smoke
(`mise e2e:web`, `E2E_SIM=1` under sim). Fix → re-drive until clean, then
capture the AFTER shot-list.

### 8. Ship the PR

Conventional-Commit title, base `develop`, body with the before/after table
and an honest verification section
([references/screenshots-and-pr.md](references/screenshots-and-pr.md)).
Subscribe to PR activity immediately.

### 9. Drive to green, then stop

Remediate CI failures at the root, answer every CodeRabbit thread — fix or
reasoned pushback, never silence — and keep the branch mergeable with plain
`git merge origin/develop` (rebase is banned)
([references/ci-and-review.md](references/ci-and-review.md)). When both
required gates are green and all threads are resolved, post one final status
comment and stop. Do not merge.

## Definition of Done

- [ ] Every acceptance criterion verified against the running app; anything
      not exercised is named in the PR
- [ ] BEFORE and AFTER screenshots captured live, published, rendering in the
      PR body
- [ ] Local gates green for every touched language; review findings fixed or
      refuted
- [ ] PR open against `develop`, both CI gates green, CodeRabbit threads all
      resolved or answered
- [ ] Branch pushed, tree clean, no stray files in the diff (plans,
      screenshots, scratch scripts)
