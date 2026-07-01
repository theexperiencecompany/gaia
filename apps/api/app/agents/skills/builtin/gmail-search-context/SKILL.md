---
name: gmail-search-context
description: Read, search, and summarize Gmail — precise queries, large-inbox fan-out reads, synthesized findings, and the opinionated inbox triage report
target: gmail_agent
---

# Gmail: Read, Search & Summarize Inbox

## When to Activate
User wants to find specific emails, gather context on a topic, OR get a summary /
triage / brief of their inbox ("summarize my emails", "what's in my inbox", "what
needs my attention", "catch me up", a morning digest).

The mechanics below (query, fetch, large-inbox fan-out) are shared by both jobs. The
two output contracts at the end differ: free-form findings for a search, the fixed
four-section report for a summary.

## Step 1: Construct a Smart Query

Gmail supports powerful search operators:

**People:** `from:user@x.com` / `to:user@x.com` / `cc:user@x.com`
**Status:** `is:unread` / `is:read` / `is:starred` / `is:important` / `is:snoozed`
**Categories:** `category:primary|social|promotions|updates` / `label:custom-label`
**Time:** `after:2025/01/01` / `before:2025/02/01` / `newer_than:7d` / `older_than:30d`
- All emails for one day: `after:YYYY/MM/DD before:YYYY/MM/DD+1` (Jan 15: `after:2025/01/15 before:2025/01/16`)

**Content:** `subject:meeting` / `"exact phrase"` / `has:attachment` / `filename:pdf` / `larger:5M` / `smaller:1M`
**Logic:** AND (default), OR, `-exclude`

## Step 2: Fetch the messages

`GMAIL_FETCH_MESSAGES` is the one read tool for everything: a specific email, a topic,
or a whole-inbox scan. Call it **directly, do NOT wrap it in `spawn_subagent`**. It
paginates the Gmail API server-side in one call (results are never silently capped),
renders the email-list card for small results, and offloads big ones to a file itself.

```
GMAIL_FETCH_MESSAGES(
  query="from:sarah@company.com subject:Q1 after:2025/01/01",  # any Gmail search query
  timeframe="today",   # optional: yesterday | 7d | this_week | 1m | ... ; ANDed with query
  fields=["id","threadId","from","to","subject","snippet","time","isRead","labels","body"],
)
```

Include `body` in `fields` when you need to triage or read content, not just subjects.

For thread-grouped views (participants, timeline, decisions per thread) use
`GMAIL_LIST_THREADS(query=..., max_results=30, verbose=true)` via `spawn_subagent`.
Contact lookup is lightweight, call directly: `GMAIL_SEARCH_PEOPLE(query="Sarah", pageSize=10)`.

It returns one of two shapes:
- **Inline** (`{"messages": [...]}`): a small inbox. Use the messages directly.
- **Offloaded** (`{"offloaded_to": ..., "total_messages": N, "file_size_human": ...,
  "read_plan": {...}}`): a large inbox written to a JSONL file, one message per line,
  too big to read inline. Do NOT read the whole file into your own context.

### Large-inbox fan-out (offloaded results)
`read_plan.chunks` gives exact line ranges; `read_plan.recommended_subagents` is how
many readers to spawn.
- If `recommended_subagents` is 1, just `read` the file yourself.
- Otherwise issue all `spawn_subagent` calls in ONE turn (parallel), one per chunk.
  Give each: the path (`offloaded_to`), its chunk's `read.offset` and `read.limit`, and
  what to extract. Tell it to `read(<path>, offset=<offset>, limit=<limit>)` and return
  only its distilled result, never raw bodies.

```
Read /workspace/sessions/<id>/gmail/inbox_summary_*.jsonl with read(offset=26, limit=25).
Each line is one email (JSON). <extraction instructions>. Return a compact result, not raw emails.
```

Then merge subagent results; dedupe by `threadId`/`id` if a chunk boundary split a thread.
For ad-hoc filtering, prefer the `query_json` tool, e.g.
`query_json(path=<path>, where=[{"field":"from","op":"contains","value":"github"}], fields=["subject"])`.

## Step 3: Progressive Search (when a query comes back empty)
1. Start specific: `"quarterly report from:finance@company.com after:2025/01/01 has:attachment"`
2. Broaden: drop the date, then the sender, then the attachment, down to `"quarterly report"`.
Each retry must change the query meaningfully — never re-fire a near-identical one.

## Persistence & Disambiguation
- Don't stop after the first 5-10 results; broaden and raise `max_results` when needed.
- Multiple strong candidates: present the best 2-3 (sender + date + subject), ask ONE focused question.
- No results: briefly list what you tried, ask ONE clarifying question (sender? timeframe? attachment type?).

## Output contract A — Search findings
Collect the subagent digests and present organized results, e.g.:
```
Found 8 emails about "Q1 budget proposal":

Thread: "Q1 Budget Review" (5 messages) — Sarah → Finance Team, Jan 15-22
  Initial proposal → revision → final approval. Attachment: Q1_Budget_Final.xlsx.
  Status: Approved.

Thread: "Budget Follow-up" (3 messages) — Alex → Sarah, You, Jan 25
  Questions about marketing allocation. Status: Awaiting your response.
```

## Output contract B — Inbox summary / triage (OPINIONATED, FIXED)
For summary/triage/brief requests, the output is NOT free-form. Sort every message into
exactly ONE section and emit the sections in this order. **Skip a section entirely when
it is empty** (never print a heading with "None" under it). One short, scannable line
per item: who it is from, the point, any date.

- **Section 1 — What matters today (main summary):** important inbox mail, actionable
  updates/promotions, anything needing a reply, anything with a deadline/date, finance /
  payment / verification / security, calendar-related mail, mail from important people
  or domains, follow-ups due today.
- **Section 2 — Action queue (most important):** a numbered to-do list of what the user
  must DO ("Reply to ...", "Confirm ...", "Review the attachment from ...", "Pay /
  submit / upload / sign / register ...", "Follow up with X if no reply by ..."). Each
  item points to a specific email. If there is nothing to do, say so in one line.
- **Section 3 — Low-priority digest:** promotions, social, newsletters, automated
  notifications, no-action circulars. Counts grouped by source/type, never one by one.
- **Section 4 — Worth a closer look:** OTP / login / security alerts, bank or payment
  alerts, a new recruiter or interview mail, a deadline that shifted, a large invoice /
  refund / cancellation, likely spam or phishing still worth a glance. Flag plainly.

Example shape (copy the structure, not the content):
```
**📌 What matters today**
- Prof. Mehta: wants your thesis draft by Fri Jun 27. Needs a reply.
- Stripe: payment of $480 failed, the card on file expired.
- Calendar: "Design sync" moved to 3pm today.

**✅ Action queue**
1. Reply to Prof. Mehta with the thesis draft (due Fri Jun 27).
2. Update the card on Stripe so the $480 charge goes through.
3. Review the offer PDF from Acme before the call.
4. Follow up with the recruiter at Initech if no reply by tomorrow.

**🗂️ Low-priority digest**
- 6 promotions (Swiggy, Zomato, Amazon)
- 2 newsletters
- 3 GitHub notifications
- 4 college circulars, no action

**⚠️ Worth a closer look**
- Login alert: new sign-in from a Windows device in Mumbai.
- HDFC: ₹22,400 debit notification.
```

Write it like a sharp assistant briefing a busy person: plain words, varied sentence
length, no filler, no "I hope this helps". Wording can vary run to run, but the four
sections, their order, and what belongs in each are fixed. This report is the
deliverable: return it to the executor verbatim (headings, order, emoji, line breaks
intact) and tell the executor to relay it to comms unchanged, not re-summarized.

## Anti-Patterns
- Wrapping `GMAIL_FETCH_MESSAGES` in a subagent (call it directly; it self-paginates and offloads).
- Calling `GMAIL_LIST_THREADS` in the parent context (use `spawn_subagent`).
- Reading a whole offloaded JSONL into your own context instead of fanning out the `read_plan` chunks.
- Using `label:snoozed` (use `is:snoozed`).
- Long natural-language queries (use operators); giving up after one search.
- Raw message dumps without synthesis; improvising a summary format instead of the fixed four sections.
