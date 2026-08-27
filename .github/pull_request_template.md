<!--
Write for someone who has never seen this branch, never saw the conversation that
produced it, and is reading this PR for the first time — today, or a year from now.

Delete every section that does not apply — do not answer it with "none". A heading
that says "Post-merge steps: none" or "Not verified: nothing here executes" costs the
reader time and gives nothing back.

Write it like you would explain the change to a teammate: plain sentences, in order,
with the reasoning connecting them. Not a wall of dense prose, and not clipped fragments
("saved logins, lifecycle rule, recap nav") that list everything and explain nothing.
Skip the internal jargon, or explain the term the first time you need it.

Do NOT include: commit-by-commit lists, tool-attribution footers or session links, "CI is green",
"all tests pass", "lint is clean", pre-existing-lint caveats, stacked-PR merge order,
approaches you tried and abandoned, or narration of the session ("then I was asked to…").
The diff, the commit log, and the Checks tab already carry that, and it goes stale
the moment this merges.
-->

## Summary

<!-- 2–4 sentences. What this changes and what it means for a user or an operator.
Lead with the outcome, not the mechanism. Expand any internal name the first time it appears. -->

## Why

<!-- The concrete trigger: the user problem, the incident, the measured number, the broken
invariant. Not "cleanup" or "improves things". One sharp sentence beats a paragraph. -->

## What changed

<!-- Grouped by surface, bullets not prose. Enough for a reviewer to know which parts they
own. Do not restate the diff file by file — it is one click away. -->

### API

### Web

### Bots / Mobile

### Infra

---

## The bug

<!-- Delete this whole block on feature/refactor PRs. Every line here is mandatory on a fix. -->

**Symptom** —
<!-- What the user or operator actually saw. Quote the real error, not a paraphrase. -->

**Reproduce** —
<!-- Numbered steps that trigger it on master. If you never reproduced it, say so here. -->

**Root cause** —
<!-- The mechanism, with a `file.py:42` pointer or the commit that introduced it.
If it is inferred from a trace rather than reproduced, label it "inferred, not reproduced". -->

**The fix** —
<!-- Why this is the root fix and not a workaround. -->

**Regression test** —
<!-- The test that now covers it, and confirmation it was seen failing before the fix.
If there is none, say that plainly instead of leaving the line out. -->

**Why the suite missed it** —
<!-- The specific gap: no test on this path, assertion too weak, the broken part was mocked. -->

---

## Screenshots

<!-- Required for any user-visible change. Real captures from the running app, same viewport
on both sides, plus the states that matter (empty, filled, error). Host them on the
`pr-assets` branch — never in the diff. See the `pr-image-embedding` skill. -->

| Surface | Before | After |
| --- | --- | --- |
|  |  |  |

## How to verify

<!-- Imperative steps a reviewer can run themselves: "run X, do Y, expect Z" — not
"I ran it and it passed". Cover the failure path too, not just the happy one. -->

**Not verified:**
<!-- What you could not exercise, stated plainly. Drop the line if you exercised it all. -->

## Post-merge steps

<!-- Everything that must happen outside this diff before it works in production: env vars and
secrets, DNS/vhost/proxy config, migrations, index builds, one-off scripts, feature flags,
dashboards, third-party settings. Ordered, executable, and specific about who runs it.
Nothing to do outside the diff? Delete the section — do not write "none". -->

- [ ]

**Rollback:**
<!-- Only when a revert alone does not undo it: a deleted branch, a migrated collection,
a rotated secret. Otherwise delete this line. -->

## Metrics

<!-- OPTIONAL — delete unless you measured something. A number without a baseline and a method
is not evidence. Say whether the harness is committed and reproducible; if the figures are
reported rather than reproducible from this diff, say exactly that. -->

| Metric | Before | After | How measured |
| --- | --- | --- | --- |

## Risk

<!-- The specific failure mode and its blast radius — who breaks, how visibly. Not "low risk". -->

## Related

<!-- Closes #123 · Depends on #456 -->
