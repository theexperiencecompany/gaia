---
name: ship-feature
description: >
  Autonomously ship a feature end-to-end with zero human intervention: plan it,
  implement it, review it with a team of subagents, boot the full stack, drive
  it in a real browser like a user (agent-browser + the driving-gaia skill),
  capture before/after screenshots, open a PR to master, and drive CI and
  CodeRabbit to green. Use this skill whenever the user asks to "ship" a
  feature, "one-shot" a feature, build something "end to end", implement
  something "autonomously", take an idea "from spec to PR", or asks for a
  complete feature with PR, screenshots, and passing CI — even if they don't
  name this skill. Also use it when a cloud session is handed a feature
  request and expected to deliver a finished, verified PR without a human in
  the loop. Do not use it when the user just wants code written or an
  ordinary PR without the full verified-shipping pipeline (live E2E,
  screenshots, drive-to-green).
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
| UI design brief, building UI, design iteration | `shape` → `impeccable` → `critique`/`polish` (see Frontend Craft) |
| CI lanes, local repro, CodeRabbit loop | [references/ci-and-review.md](references/ci-and-review.md) |
| Screenshot protocol + PR format | [references/screenshots-and-pr.md](references/screenshots-and-pr.md) |

**Subagent economy.** A team of agents is not a license to burn tokens.
Match the model to the job: wide mechanical fan-outs (exploration, claim
verification, lane repro) run on a small model; judgment-heavy singletons
(plan attack, review lenses, design critique) use the session's model.
Spawn the agents the task needs, no more — parallelism is for wall-clock,
not volume.

## Non-Negotiables

- **Branch from and PR into `master`.** **Never merge the PR.**
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

`git fetch origin master` and branch from it. Then `pnpm install` and
`pnpm exec nx run api:sync`, create env files
(`cp -f apps/api/.env.example apps/api/.env` first — `mise setup:env` errors
without it, and only auto-copies the others; dummy WorkOS values are fine —
the dev bypass never calls WorkOS). Boot per
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

Valid only while the branch's tracked tree still matches `master` —
untracked bootstrap artifacts (`.env` files, installed deps) don't count.
Capture before your first source edit (`git stash` around the capture if
you already edited). Walk the journey script and shoot every surface the
feature will change, per the protocol in
[references/screenshots-and-pr.md](references/screenshots-and-pr.md).

### 4. Implement

Execute the plan task by task on the feature branch. Write to CI's structural
bars from the start rather than remediating after — the Code Quality lanes
enforce limits on file size, components per file, type placement, complexity,
docstring coverage, duplication, and dead code (current thresholds live in
the lane scripts/configs, see the CI reference). UI-touching work follows
Frontend Craft (below). Commit in Conventional-Commit increments; no new
test files unless the user asked (repo Testing rule).

### 5. Local gates

Run the CI-equivalent commands locally before any push
([references/ci-and-review.md](references/ci-and-review.md)). Fix at the
root; auto-fixers first where they exist.

### 6. Review team

Spawn reviewer subagents in parallel on the full diff vs `origin/master`,
one lens each — correctness (real user-reachable failures, not theoretical
races), architecture/debt (duplication, wrong-layer logic, missed
`libs/shared` reuse, dead code), design-system compliance vs DESIGN.md (UI
diffs only), security (when the diff adds surface — endpoints, queries, file
handling, external calls — or touches security-sensitive code: authz,
validation, secrets, dependencies, infra). Each returns
findings with file:line and a concrete failure scenario. Then adversarially
verify: a fresh skeptic subagent takes the batched findings and tries to
refute each against the code. Fix what survives, drop what doesn't —
single-pass reviewers confidently report plausible non-bugs. Re-run affected
gates after fixes.

### 7. E2E as a user + AFTER screenshots

Run the existing Playwright smoke first (`mise e2e:web`, `E2E_SIM=1` under
sim) — its global setup **resets and re-seeds the dev user**, wiping
anything driven before it; smoke first, journey second. Then drive the app
through the full journey script with agent-browser (driving-gaia §6) as the
seeded dev user. Hot reload covers code edits only — after dependency, env,
or settings changes, re-sync and restart the stack. On every page: act like
the user, exercise the unhappy paths (empty states, invalid input, the
second submit), and check for console errors and failed network requests
(chrome-devtools MCP when you need that introspection; a feature that
renders but errors underneath is not done). Verify data landed in Mongo, not
stdout (driving-gaia §4). If the journey needs state the dev seed cannot
create (OAuth integrations, external data), fabricate it under `--sim`
directives or verify that layer directly via the dev routes (driving-gaia
§5) — and name the un-exercised surface under Not verified. Fix → re-drive
until clean, then capture the AFTER shot-list.

### 8. Ship the PR

Push the branch first (`git push -u origin <branch>`), then open the PR:
Conventional-Commit title, base `master`, body with the before/after table
and an honest verification section
([references/screenshots-and-pr.md](references/screenshots-and-pr.md)).
Subscribe to PR activity immediately.

### 9. Drive to green, then stop

Remediate CI failures at the root, answer every CodeRabbit thread — fix or
reasoned pushback, never silence — and keep the branch mergeable
([references/ci-and-review.md](references/ci-and-review.md)). When both
required gates are green and all threads are resolved, post one final status
comment and stop. Do not merge.

## Frontend Craft (UI features)

Unattended AI-generated UI defaults to slop — generic layouts, timid
typography, no hierarchy, elements added because sections like them usually
exist. Design is a gate in this pipeline, not a coat of paint:

- **Before UI code:** run `shape` for the design brief — direction,
  hierarchy, what to leave out — grounded in `DESIGN.md` tokens. Every
  element must have a reason to exist; if it's there "for completeness",
  cut it.
- **While building:** use the `impeccable` skill. Typography scale, spacing
  rhythm, and visual hierarchy are decisions made from principles — the bar
  is Linear/Notion/Apple-level consideration — never framework defaults.
- **After it renders:** iterate. Screenshot → critique with the design
  skills (`critique`, `polish`, `make-interfaces-feel-better`) → refine →
  re-drive. Expect several rounds; one-pass UI is how slop ships. The
  phase-6 design lens and the AFTER screenshots are the exit gate, not the
  first render.

## Definition of Done

- [ ] Every acceptance criterion verified against the running app; anything
      not exercised is named in the PR
- [ ] BEFORE and AFTER screenshots captured live and rendering in the PR for
      every changed UI surface; features with no UI surface substitute
      equivalent live evidence (bot transcript, curl + Mongo output) and say so
- [ ] Local gates green for every touched language; review findings fixed or
      refuted
- [ ] PR open against `master`, both CI gates green, CodeRabbit threads all
      resolved or answered
- [ ] Branch pushed, tree clean, no stray files in the diff (plans,
      screenshots, scratch scripts)
