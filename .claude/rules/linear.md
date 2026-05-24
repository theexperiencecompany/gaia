# Linear Workspace Rules

Apply these rules whenever creating or updating anything in Linear — initiatives, projects, issues, comments, or descriptions.

## Writing Style

**No em dashes.** Use a comma, period, or colon instead.

**No fluff.** Cut filler phrases: "we need to", "it would be great if", "we should look into", "this is important because". Say the thing directly.

**Short sentences.** If a sentence needs a second clause, consider making it two sentences.

**No vague nouns as titles.** Every issue title must make sense on its own without reading the description.

## Issue Titles

Start with a verb. Be specific about what changes.

Good: `Add caching to Gmail schema fetch`
Bad: `Gmail performance`

Good: `Fix crash when opening chat with empty history`
Bad: `Chat bug`

Good: `Show inline diff when GAIA edits a file`
Bad: `File editing improvements`

## Issue Descriptions

Every issue needs three things:

1. **Context** — one sentence on why this matters or what triggered it
2. **What to do** — clear, specific steps or the outcome expected
3. **Done when** — how to know the issue is complete (acceptance criteria)

No empty descriptions. No "TBD". If you can't write a description, the issue is not ready to be created.

## Priority

Never leave priority as None on any issue in an active cycle.

- **Urgent** — blocks a user-facing release or causes a live outage
- **High** — on the critical path to the current milestone
- **Medium** — valuable this cycle but not blocking
- **Low** — nice to have, can slip to next cycle

When in doubt, Low is better than None.

## Issue Scope

Each issue should be completable in 1 to 3 days by one person. If it would take longer, break it into smaller issues. Large issues stall in cycles and inflate scope without delivering value.

## Project Linking

Every issue must belong to a project. Orphan issues are invisible in the roadmap and get ignored. If no project fits, that is a signal to either create one or reconsider the issue.

## Status Discipline

- **In Progress** — you are actively working on it right now, today
- **In Review** — waiting on another person (PR review, feedback, approval)
- **Done** — fully shipped or resolved, not just "code merged"

Do not leave issues In Progress if you have moved on. Update status the moment it changes.

## Cycles

Only add issues to a cycle if they will realistically be completed in that cycle. A cycle with 40 issues and 2% completion is worse than a cycle with 12 issues and 90% completion. Be honest about capacity.

## Comments

Use comments to record decisions and blockers, not to chat. If the issue scope changed, note it. If something is blocked and why, note it. Anything that would be lost when the Slack thread disappears should be a comment on the issue.

## Labels

Every issue must have at least one label before it is considered ready. Unlabeled issues disappear when filtering by label and get ignored during triage.

Available labels: Bug, Feature, Improvement, PMF-Critical, User-Reported, Quick Win, Developer Experience, Open Source/Self Hosting.

If none fit, that is a signal the label set needs expanding, not a reason to leave the issue unlabeled.

## The "Why This Cycle" Test

Before adding an issue to a cycle, you must be able to finish this sentence in one line: "This is in the current cycle because ___." If you cannot, it does not go in. Push it to backlog and revisit next planning session.

## No Duplicates

Search Linear before creating any new issue. With 500+ issues there are definitely duplicates. If you find one, close the newer issue as duplicate and add a comment linking to the original.

## Assignee Required in Active Cycles

Every issue in a running cycle must have an assignee. Unassigned means no owner, and no owner means it will not get done. If you are unsure who should own it, that is a planning problem to resolve before the cycle starts.

## Blocked Issues

If an issue is blocked, do two things immediately:
1. Add a comment explaining what it is blocked on and who can unblock it
2. Move it out of the current cycle if it cannot be resolved within 24 hours

Do not leave blocked issues sitting In Progress. They inflate the cycle and hide the real completion rate.

## Initiatives and Projects

When writing descriptions for initiatives or projects, state the outcome you are trying to achieve, not the tasks you plan to do. Tasks go in issues. Descriptions should answer: what does winning look like for this initiative?
