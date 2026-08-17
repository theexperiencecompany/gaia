---
name: writing-pull-requests
description: >
  Write a GAIA pull request description that a first-time reader can actually
  use — the template in .github/pull_request_template.md, what belongs in each
  section, and the failure modes (session narration, commit lists, "CI is
  green", missing screenshots, missing deploy steps, a fix with no root cause)
  that make our PRs unreadable. Use whenever opening a PR, rewriting a PR body,
  reviewing whether a description is good enough, or asked to "write the PR",
  "open a PR", "update the PR description", or "clean up this PR body".
---

# Writing Pull Requests

## The reader you are writing for

One person: an engineer who has never seen this branch, was not in the session
that produced it, and is reading the PR cold — during review, or a year later
while bisecting a regression into it. They have the diff and the commit log
already. What they do not have is **why this exists, what it does for a user,
how to see it working, and what breaks if it is wrong.** That is the entire job
of the body.

Two tests to apply to every line before you keep it:

- **Will this still be true and useful after merge?** "CI is green", "all 11,379
  tests pass", "94 pre-existing lint errors on master", "merge after #858",
  "rebased onto develop" — all false or meaningless within a week. Cut them.
- **Does this exist only because of the session that produced it?** "The user
  then pointed out…", "first I tried X, then switched to Y", "18 commits of
  small fixes", a `claude.ai/code/session_…` link, "please confirm this commit
  is yours". None of it survives contact with a stranger. Cut it. And never
  attribute the work to a tool — no "generated with Claude Code" footer, no
  "written by Claude", no co-author trailer, in the body or the commits. Open questions get resolved before review or posted as a PR comment —
  never parked in the description.

## How it should read

Write it the way you would explain the change to a teammate standing at your
desk: plain sentences, in order, with the reasoning connecting them. That is the
target on both sides of a common failure — the wall of dense prose nobody
finishes, and the stack of clipped fragments that technically lists everything
and explains nothing.

- **Prefer real sentences over telegraphic bullets.** "Saved logins, R2 lifecycle,
  recap nav" tells a reader nothing. "Logins are saved per user and encrypted at
  rest, so a repeat task on the same site skips the sign-in" tells them what
  happened and why they should care. Bullets are for grouping parallel items, not
  for compressing a thought until it stops being one.
- **Length follows content, not habit.** A one-line fix gets a short paragraph. A
  feature touching five surfaces gets a page. Neither gets padding, and neither
  gets a lab notebook — if you find yourself writing round-by-round investigation
  notes or a fourth result matrix, that belongs in a linked issue.
- **Cut the jargon, or explain it once.** Internal names (`ModelLane`,
  `DeltaChannel`, "the T3 batch"), acronyms, and infrastructure shorthand are
  invisible walls to anyone outside the thread that invented them. Use the
  product's own words where they exist, and gloss the term the first time you
  genuinely need it.
- **Say things the plain way.** "This was failing for every user on mobile" beats
  "a regression in the mobile render path manifested". No marketing tone, no
  self-congratulation, no hedging a fact you actually verified.

## Process

1. **Read the actual diff** (`git diff master...HEAD --stat`, then the substance)
   — not your memory of writing it, and not the commit subjects.
2. **Fill the repo template**, `.github/pull_request_template.md`. GitHub loads it
   automatically in the web UI; from the CLI, start from the file:
   `gh pr create --base master --title "…" --body-file <filled-copy>`.
3. **Delete every section you cannot fill honestly.** An empty heading, or one
   padded to look filled, is worse than no heading.
4. **Title**: Conventional Commit, `type(scope): description`, validated in CI by
   `.github/workflows/pr-naming-conventions.yml` — read the allowed types there.
   Write it as the changelog line it will become.
5. **Base is always `master`.** Never merge the PR yourself.

## Section by section

**Summary** — 2–4 sentences on the outcome, in the vocabulary of someone using
the product. Mechanism comes later. Expand every internal name on first use:
`ModelLane`, `HIL`, `DeltaChannel`, `root_request_id` mean nothing cold.

**Why** — the concrete trigger, and it must be falsifiable. A good one names an
incident, a measured number, or a broken invariant:

> Proof from 2026-08-14: the master run's `trigger-web` job was skipped … yet
> the frontend shipped anyway — the CI path contributed nothing. (#1013)

> **The core idea:** message counts are the wrong unit when one message can cost
> 1000x another. (#855)

"Cleanup", "improves maintainability", "better UX" are not reasons. They are
labels for a reason you have not written down yet.

**What changed** — grouped by surface (API / Web / Bots / Infra), bullets, so a
reviewer can jump to what they own. Summarize; do not inventory. If a section
restates the diff line by line, delete it.

**The bug** (fix PRs) — four questions, answered in order, no exceptions:
symptom → reproduce → root cause → fix, then the regression test and the gap that
let it ship. This is the section our fix PRs most often fake. The common failure
is a root cause narrated from a stack trace: "this typically occurs when the user
cancels mid-stream" is a hypothesis, and shipping it as a cause means the next
person debugs from a fiction. If you did not reproduce it, write **"inferred from
the trace, not reproduced"** and let the reader calibrate. The bar to aim at:

> Every chat request in production was failing with `GraphUnavailableError` …
> behind an opaque `KeyError`. Introduced in `fc937af60`. … **Why no test caught
> it**: [the two exact fixture blind spots]. … reverting the fix → `None`
> (BROKEN). (#1004)

By the repo's bug loop (CLAUDE.md), a fix ships with a test seen **red** before
the fix. If it does not, the PR says so out loud — #999 does this well ("No
regression test for the stale-cache bug yet … calling it out rather than burying
it"). Silence reads as coverage that does not exist.

**Screenshots** — mandatory for anything user-visible. Real captures from the
running app, identical viewport on both sides, plus empty/error states. Most of
our UI PRs ship with none, and a reviewer then has to build the branch to see a
modal. Host on the `pr-assets` branch per the `pr-image-embedding` skill — images
in the diff are noise, and a per-PR assets branch is noise too.

**How to verify** — written as instructions for the reviewer ("run `nx dev api`,
send X, expect Y"), not as a trophy case of what you ran. Then **Not verified**,
naming the surface you could not exercise. This is the highest-trust move
available to you and it costs one line:

> Reproduced? No. Proven by CI log timestamps + code path … a hermeticity fix
> backed by stability evidence, not a deterministic regression test. (#966)

**Post-merge steps** — everything the diff cannot do to itself: env vars and
secrets, DNS/vhost/proxy config, migrations, index builds, one-off scripts,
feature flags, dashboards, third-party console settings. Ordered and executable,
in the shape #961 used:

> 1. Verify the master push goes green end-to-end 2. Repoint every open
> develop-based PR … 3. Delete `origin/develop` … 5. Expected: release-please may
> open release PRs.

Note which steps are expected side effects rather than failures. Then a
**Rollback** line: "revert this PR", plus whatever a revert does not undo (a
deleted branch, a migrated collection, a rotated secret).

**Metrics** — optional, and only with a baseline and a method. Say whether the
harness is committed. If the numbers came from a throwaway script, disclose it in
those words rather than implying reproducibility:

> The end-to-end figures quoted in this description are reported, not
> reproducible from anything in this diff. (#997)

**Risk** — the specific failure mode and its blast radius: who breaks, how
visibly, how fast you would notice. "Low risk" is a rubber stamp.

**Out of scope** — deliberate omissions, one line each. State the boundary; do
not re-argue approaches you rejected. #1016's "**Out of scope (deliberate)**:
mobile surfaces … group chats" is the right length.

## Patterns worth reaching for

- **A before/after table** for anything that changes behaviour, limits, or
  permissions. It turns a 40-commit branch into something scannable, and it is
  the single highest-value artifact in our best PRs (#850, #1009, #1020).
- **One bolded core-idea sentence** carrying the whole rationale (#855).
- **A gotcha callout** that saves the next engineer an afternoon — a real
  constraint of the system, stated where they will hit it (#876).
- **Naming the seam that makes the change safe**: "metering and enforcement live
  in `LLMAccountingMiddleware` — the one seam every execution path passes
  through, so no entry point can route around it" (#855). It answers "how do I
  know this is complete?" before the reviewer asks.

## Before you submit

- A stranger can state, from the body alone: what this does, why, how to see it,
  and what to do after merge.
- Every claim is evidence, not vibes; everything unproven is labelled unproven.
- No session artifacts, no commit lists, no ephemeral CI status, no open
  questions parked in the body.
- UI change → screenshots present. Infra/config change → post-merge steps
  present. Fix → root cause and regression test present, or their absence stated.
