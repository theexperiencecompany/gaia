---
name: debt-review
description: >
  Deep, multi-lens debt review of a GAIA PR or gh stack: twelve read-only reviewers, one
  per lens (duplication, design, rot, types, lifecycle, data realism, LLM visibility,
  security, scale and cost, ops and config, analytics, tests), each searching the whole
  repo rather than only the diff, merged into one verified, ranked list of findings with
  file:line and the clean fix. Run it when a PR is code-ready, when a stack reaches about
  3 PRs, and before any handoff. Use for "debt review", "deep review", "review this
  stack", "is this ready to hand over", or when CLAUDE.md asks for it.
---

# Debt review

A diff review catches the bug in the lines it shows you. It does not catch a second
copy of a pipeline that already exists, a constant mirrored by hand in four runtimes, a
query with no index, or a test that only proves its fixture. One review of the briefing
stack found about 150 of those. They came from the same few habits, and twelve lenses
cover them.

Every lens is its own reviewer, because one reviewer reading for everything reads for
nothing. The reviewers did not write the code and change nothing. The orchestrator (you)
verifies each finding before it reaches the list.

## When to run

- **Code-ready.** The PR does what it says, tests pass locally, and you are about to call
  it done.
- **The stack reaches about 3 PRs.** Debt compounds up a stack: PR 3 builds on PR 1's
  shape. Review before PR 4 builds on it too.
- **Before any handoff**: to the founder, to the merge queue, to another agent, or at
  the end of a session.

Run it again after a fix round that changed the design, not after every push.

## 1. Fix the scope

```bash
gh stack view --json                                  # a stack: bottom to top, with each PR's base
git diff --stat <base>...<head>                       # one PR: base is its stack parent, else master
git diff --name-only <bottom-base>...<top-head>       # a whole stack, as one change
```

Write down: the target (PR numbers or branch), the base ref, the changed files, and the
design note in `.agents/plans/` if there is one. Every reviewer gets the same four facts.

## 2. Spawn the reviewers, in parallel

Spawn one subagent per lens, all in one message, with read-only tools (the `Explore`
type, or any type with no edit tools), on the strongest model available. Never use the
agent that wrote the code. Do not let reviewers run tests, builds or type-checks: they
read. On a PR of under about 200 changed lines you may skip a lens the change cannot
reach (no prompt text means no LLM-visibility lens). Name each skipped lens and the reason
in the report.

### Brief template (fill one per lens)

```text
You are the <LENS> reviewer in a debt review of <TARGET> (base <BASE>). You did not write
this code. Read only: change nothing, run no tests, builds or type-checks.

Scope: these changed files: <FILES>. Design note: <PLAN PATH or "none">.
Read first: CLAUDE.md, .claude/rules/general.md, and the CLAUDE.md of each app the diff
touches (apps/api, apps/web, apps/bots, ...). They are the bar.

Your lens: <LENS CHARTER, copied from the debt-review skill>.

Search the WHOLE repo, not only the diff: rg, the code-review-graph MCP tools, and
codegraph_explore when .codegraph/ exists. A finding about something that "should
exist" must name the existing thing, at its file:line.

Report only findings you confirmed by reading the code at the cited line. For each:
- id: <LENS-PREFIX>-<n>
- severity: P0 | P1 | P2 (definitions below)
- where: file:line (every site, if it is a duplication or drift)
- evidence: the line(s) quoted, plus what it duplicates or contradicts, at file:line
- why it is debt: one sentence on what breaks, or what gets harder, and when
- clean fix: the root fix (the canonical owner, the one type, the index), never a patch
- test: for a bug, the test that fails before the fix, and its tier (unit, integration, e2e)

Severity: P0 = a user hits it, or data, money, security or privacy is at risk. P1 = debt
that compounds: a second implementation, a second source of truth, a missing index on a
hot path, a test that cannot fail. P2 = local debt: a magic value, a weak assertion, a
misleading name. No style nits and no theoretical races (CLAUDE.md, "Reporting Issues").
If you find nothing real, say so. Do not pad. Return at most 25 findings, worst first.
```

### Lens charters

**1. Duplication and one canonical way (DUP).** For each new function, type, constant,
hook, service, query, prompt fragment and test fixture, search the repo for the thing that
already does it and name it. Look for: two copies of one pipeline that already drift (a
daily and a weekly runner, where only one has the timeout); a constant or rule hand-synced
across Python, web, the Worker and the CLI; a second date or day-window helper; a parallel
model that re-declares fields an existing model owns; a new helper next to an existing
one with a different name. The fix extends or reuses the existing one, or merges the two.

**2. Design and boundaries (DES).** Who owns each concept and each rule, and is there
exactly one owner? Look for: god modules (a 500-line file with five jobs); a feature
reaching into another feature's internals instead of its `index.ts` or public service;
a client re-deriving a decision the server already made (the web re-computing which items
the API left out); special-casing (`if kind == "weekly"` scattered through shared code
instead of a spec object); pass-through wrappers (general.md, "No Pass-Through Wrappers").

**3. Rot patterns (ROT).** Look for: a boolean flag or string mode steering behaviour
through many call sites; magic values; silent fallbacks (`or ""`, `.get(k, default)`
hiding a missing key, a client that returns `""` where its twin throws); catch and
continue; `except` that logs and returns `None`; shims, compatibility aliases or "legacy"
paths with no removal step; commented-out code; TODOs that return fake success.

**4. Types and vocabulary (TYP).** Closed sets are enums or `Literal`s, never bare
`str`. One name and one type per concept across the API, web, bots, CLI and docs (one
word that means five things, like "dormancy" across five modules, is a finding). No
hand-written TypeScript mirroring a Pydantic model (types come from
`@gaia/shared/api/generated`); no `Any`, no `dict[str, Any]` crossing a boundary; no new
entries in `scripts/ci/baselines/api-shape-twins.txt`.

**5. State and lifecycle (LIFE).** Build the lifecycle table for each stateful thing the
change adds: create, change, delete, fail, retry, pause, resume. Then check the edges the
table exposes: timezone and DST changes; a plan upgrade or downgrade mid-cycle; account
deletion and chat deletion (does the new data go too?); a worker killed mid-step (is the
retry idempotent, or does it double-send or drop?); a disabled integration.

**6. Data realism (DATA).** Walk each input through: empty, exactly one, huge (10k items,
a 2 MB email), stale (weeks old), malformed (a missing field, a legacy row with the old
shape), and source down (the integration times out). Does each produce a correct, honest
result, or a crash, a blank screen, or confident output built on nothing?

**7. LLM-facing visibility (LLM).** For each prompt or tool the change touches: which
facts must the model guess because nobody gave them to it (the current time, the user's
timezone, what was already sent, why an item was left out)? Does untrusted text (email
bodies, web pages, calendar descriptions, user names) reach a prompt without being
delimited and marked as data? Does code parse model prose where a structured output
belongs?

**8. Security and privacy (SEC).** Authorization on every new route and every query
(scoped by `user_id`; one user's ids cannot read another's); entitlements on new routes
(apps/api/CLAUDE.md, "Entitlements"); secrets out of logs; PII out of logs and analytics;
SSRF on any user-supplied URL; signed and expiring share links; prompt injection reaching
a tool with side effects.

**9. Performance and cost at about 10k users (PERF).** For every new query, name the index
that serves it (user_id first, then the filter, then the sort), or the finding is a missing
index. Look for: unbounded reads (no limit, full documents where ids would do); N+1 (a
query per user, per item); fan-out (one cron tick touching every user at once); LLM calls,
browser renders or storage growth per user per day, priced; work that is not idempotent
under retry.

**10. Ops and config (OPS).** Deploy order: can the new code read old data, and can the
old code survive new data during the rollout? Migrations and backfills, and who runs them.
Config parity: every new setting exists in the API config, `.env.example`, the self-host
compose and the CLI's config schema, with the same default. Docs that the change made
false. Failures that nobody sees: a job that can fail with no log, metric or alert; an
index build failure that is only logged.

**11. Analytics (ANA).** Every user-facing feature ships an event in the catalog
(`libs/shared/py/analytics/catalog/`), emitted server-side after success, once, with
no PII in properties, and with an `Expect` in its journey in
`apps/api/scripts/analytics_ops/e2e.py` (CLAUDE.md, "Product Analytics"). Flag a client
event for something the server sees, and a missing failure event.

**12. Tests (TEST).** Each test must be able to fail: name the line of product code
whose deletion turns it red, or it is a finding. Look for: mocking the subject; a fake
LLM that regex-parses prompt prose; assertions on prompt wording; fixtures that disagree
with production ("airmail" in the fixture, "postal" in the code); one subject tested in
two or three files with copied mock blocks; hand-rolled fixtures where
`tests/factories.py` or `tests/helpers.py` already has one; a bug fix with no test that
was seen red.

## 3. Verify, merge, rank

1. **Verify every finding yourself.** Open the cited file:line. A finding whose evidence
   is not there, or whose "existing helper" does not exist, is dropped. Reviewers
   sometimes return a confident finding that is wrong. This step is where you catch it.
2. **Merge duplicates across lenses.** The same root cause often appears as DUP, TYP and
   OPS (a constant hand-synced in four places). Keep one finding, list every site, and
   tag every lens that found it.
3. **Rank.** P0 first, then P1, then P2. Within a severity, rank by how many places
   each finding touches.
4. **Write the list** to `.agents/plans/<target>-debt-review.md` (gitignored). Each
   finding has its id, severity, sites, the clean fix and the test. Report the counts per
   severity and the P0s to the caller.

## 4. What happens to the findings

- **Fix at the root, in this PR or stack.** No finding is deferred silently: either it
  is fixed, or it is raised to the founder as a decision, by name (CLAUDE.md, "Never defer
  cleanup to a separate PR").
- **Every bug gets a test that fails before the fix**, seen red, at the tier that
  catches it (CLAUDE.md, "The bug loop").
- **A ratchet baseline never grows to make a finding pass.** `baseline-growth` fails the
  PR, and only the founder's explicit approval permits the approval line
  (`scripts/ci/CLAUDE.md`, "baselines/").
- After the fixes, run the lenses the fixes touched again, not the whole review.
