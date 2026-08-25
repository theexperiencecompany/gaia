---
name: writing-pull-requests
description: >
  Write a GAIA pull request description someone can read cold — how to fill the
  template in .github/pull_request_template.md, and the habits (session
  narration, commit lists, "CI is green", missing screenshots, missing deploy
  steps, a fix with no real root cause) that make our PRs unreadable. Use when
  opening a PR, rewriting a PR body, or judging whether a description is good
  enough.
---

# Writing Pull Requests

## Who you are writing for

An engineer who has never seen this branch, was not in the session that produced
it, and is reading it cold — in review, or a year later while bisecting a
regression into it. They already have the diff and the commit log. What they
don't have is why this exists, what it does for a user, how to see it working,
and what breaks if it's wrong. That's the whole job of the body.

Two tests for every line:

- **Will this still be true after merge?** "CI is green", "all tests pass", "94
  pre-existing lint errors on master", "merge this after the other PR" — false or
  pointless within a week.
- **Does it only exist because of the session that wrote it?** "Then I tried X
  instead", "18 commits of small fixes", session links, "please confirm this
  commit is yours". Never attribute the work to a tool either — no "generated
  with" footer, no co-author trailer, in the body or the commits. Open questions
  get resolved before review or posted as a comment, not parked in the body.

## How it should read

Explain it the way you would to a teammate at your desk: plain sentences, in
order, with the reasoning connecting them. Two ways that goes wrong — the wall of
prose nobody finishes, and clipped fragments that list everything and explain
nothing. "Saved logins, lifecycle rule, recap nav" says nothing; "logins are
saved per user and encrypted at rest, so a repeat task on the same site skips the
sign-in" says what happened and why it matters.

Length follows content. A one-line fix gets a paragraph; a feature across five
surfaces gets a page. Neither gets padding, and neither gets a lab notebook —
round-by-round investigation notes belong in an issue. Skip internal shorthand or
gloss it once; acronyms and service names are invisible walls to anyone outside
the thread that invented them. And say things the plain way: "this was broken for
every user on mobile", not "a regression manifested in the mobile render path".

## Process

1. Read the actual diff, not your memory of writing it and not the commit
   subjects.
2. Fill `.github/pull_request_template.md`. GitHub pre-fills it in the browser;
   from the CLI, `gh pr create --base master --body-file <your-filled-copy>`.
3. Delete every section that doesn't apply — don't answer it with "none".
   "Post-merge steps: none", "Rollback: revert this PR", "Not verified: nothing
   here executes" are headings that cost the reader time and give nothing back.
   A rollback line earns its place only when a revert alone doesn't undo the
   change; a verify section only when there's something to run.
4. Title: Conventional Commit, `type: description` or `type(scope): description`
   — the scope is optional, so add one only when it says something. CI validates the type
   against `.github/workflows/pr-naming-conventions.yml`. Write it as the
   changelog line it becomes.
5. Base is always `master`. Never merge the PR yourself.

## The sections

**Summary** — 2–4 sentences on the outcome, in the words someone using the
product would use. Mechanism comes later.

**Why** — the concrete trigger: an incident, a measured number, a broken
invariant, a user complaint. A few sentences, not a wall — if it runs past a
short paragraph you're arguing the case instead of stating it. "Cleanup",
"improves maintainability" and "better UX" are labels for a reason you haven't
written down yet.

**What changed** — grouped by surface (API / Web / Bots / Infra) so a reviewer
can find their part. One or two lines per item: what it is now, and the one thing
worth knowing about it. If a bullet needs a paragraph, the detail belongs in the
diff or in Why.

**The bug** (fix PRs) — symptom, reproduction, root cause, fix, then the
regression test and the gap that let it ship. The usual failure is a root cause
narrated from a stack trace: "this typically happens when the user cancels
mid-stream" is a hypothesis, and shipping it as fact means the next person debugs
from a fiction. If you didn't reproduce it, write "inferred from the trace, not
reproduced". Point at the code (`file.py:42`) or the commit that introduced it.
Per CLAUDE.md's bug loop a fix ships with a test seen red first; if it doesn't,
say so — silence reads as coverage that isn't there.

**Screenshots** — required for anything user-visible, or the reviewer has to
build the branch to see a modal. Real captures from the running app, same
viewport on both sides, plus the empty and error states. Host them on the
`pr-assets` branch (`pr-image-embedding` skill), never in the diff.

**How to verify** — instructions the reviewer can run ("start the API, send X,
expect Y"), not a list of what you ran. Then say what you couldn't exercise.
Naming the gap costs one line and is the fastest way to be trusted; claiming
coverage you don't have is the fastest way to lose it.

**Post-merge steps** — everything the diff can't do to itself: env vars and
secrets, DNS or proxy config, migrations, index builds, one-off scripts, feature
flags, dashboards, third-party settings. Ordered, executable, and clear about
which effects are expected rather than failures. Then a rollback line: "revert
this PR", plus whatever a revert won't undo — a deleted branch, a migrated
collection, a rotated secret.

**Metrics** — optional. Numbers need a baseline and a method, and you say whether
the harness is committed. If they came from a throwaway script, write that
plainly instead of implying anyone can reproduce them.

**Risk** — the specific failure mode and its blast radius: who breaks, how
visibly, how fast you'd notice. "Low risk" is a rubber stamp.

Don't add a section listing what you didn't do. A reader needs to know what the
change is, not the shape of every change it isn't. The rare exception is a
missing piece someone would otherwise assume is there — a surface the feature
visibly skips — and that's one line inside Summary, not a heading.

## Two things worth adding when they fit

A **before/after table** for anything that changes behaviour, limits, or
permissions — it turns a large branch into something scannable in seconds.

And **the seam that makes the change safe**: "enforcement lives in the one
middleware every execution path passes through, so no entry point can route
around it". It answers "how do I know this is complete?" before the reviewer asks.

## Before you submit

- A stranger can say, from the body alone, what this does, why, how to see it,
  and what to do after merge.
- Everything unproven is labelled unproven.
- No session artifacts, no commit lists, no ephemeral CI status.
- UI change → screenshots. Infra or config change → post-merge steps. Fix → root
  cause and regression test, or an honest note that there isn't one.
