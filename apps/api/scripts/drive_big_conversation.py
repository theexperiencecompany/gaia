"""Drive a LARGE real conversation through the live chat-stream endpoint.

Not a simulation: every turn POSTs /api/v1/chat-stream like the web client
does, the real comms->executor graph runs against the real provider, and the
conversation history grows in the checkpoint + Mongo exactly like production.
Per-turn usage is read from the stream's own ``main_response_complete`` frame
(the same numbers the frontend receives), and the full history is re-read from
Mongo between turns — the authoritative source the web client uses on reload.

Run the same script twice (baseline code, then fixed code) with the same
turns and a fresh conversation id each time, then compare the per-turn
tables. Output is JSONL at ``--out`` (default ./cache_run.jsonl) for later
analysis, plus a human-readable table.

Usage: uv run python scripts/drive_big_conversation.py [--api URL] [--tag NAME]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import time
from typing import Any
import uuid

import httpx
from pymongo import MongoClient

# --- conversation script (deterministic; identical across runs) ---------------

# A realistic long document the user "pastes in chunks" — 26 chunks x ~2.2k chars.
_DOC_SECTIONS = [
    "Quarterly Product Review — Q3. "
    + (
        "This review consolidates feedback from the customer advisory board, "
        "support ticket themes, and the win/loss analysis produced by the field "
        "team. The headline: activation is up eleven points quarter over quarter, "
        "but retention among mid-market teams still trails the benchmark, and the "
        "largest single driver of churn remains the onboarding experience for "
        "multi-workspace organizations. The board's feedback this quarter "
        "clustered into five themes: (1) the setup flow assumes a single "
        "workspace, (2) permission presets do not cover the security review "
        "patterns our largest customers use, (3) the audit log is read-only and "
        "teams want to annotate events, (4) the API rate limit documentation is "
        "out of date, and (5) the mobile app lacks offline mode for review "
        "workflows. Each theme is expanded below with the evidence, the proposed "
        "response, and the open questions for the roadmap. We have also included "
        "the raw verbatim quotes from the board session in the appendix, since "
        "the exact language customers use tends to matter more than our summary "
        "of it. Where we cite a number, it comes from the analytics warehouse "
        "query set in the metrics appendix rather than from anecdote."
    )
    * 1
]

# Build 26 varied chunks from the seed paragraphs.
_BASE_PARAS = [
    (
        "Onboarding remains the sharpest edge of the product. New workspaces that "
        "complete the guided setup within the first session retain at 82% versus 54% "
        "for those that stall at the invitation step. The single highest-impact fix "
        "we identified is the invitation flow: when a workspace owner invites more "
        "than five people at once, the current UI silently queues the invitations "
        "and shows no progress, which produces duplicate invites and a support "
        "ticket pattern we can trace to a single screen. The proposed redesign "
        "splits the flow into batches, shows live delivery status per invite, and "
        "adds an undo for misdirected invitations. The open question is whether to "
        "gate the new flow behind the existing feature flag or ship it to the "
        "default cohort with a kill switch, given that the current flow is also the "
        "top source of activation drop-off for trial conversions."
    ),
    (
        "The permission model is the second theme. Security teams at our largest "
        "accounts review access quarterly, and the current presets force them to "
        "choose between read-only and editor with no middle ground. The board "
        "specifically asked for a review-only role that can see everything, export "
        "for compliance, and comment — but cannot change settings. We prototyped "
        "this as a new preset and the feedback from the design partners was "
        "positive, with the caveat that the preset needs to compose with the "
        "existing per-document overrides without surprising anyone. The roadmap "
        "question is whether to invest in the preset this quarter or fold it into "
        "the larger permissions redesign that the platform team has been scoping "
        "since last sprint."
    ),
    (
        "The audit log theme is smaller in volume but loud in sentiment. Teams want "
        "to annotate events with context — why a permission changed, which ticket "
        "requested it — and the current read-only log forces that context into "
        "side channels where it gets lost. The proposal is to allow comments on log "
        "entries with the same permission model as document comments, plus a "
        "filterset for the top ten event types. This is a low-risk, high-visibility "
        "change that several reference customers have already said they would "
        "adopt immediately, which makes it a strong candidate for the quick-wins "
        "lane in the next planning cycle."
    ),
    (
        "The API documentation complaint is the cheapest to fix and the most "
        "embarrassing to leave unfixed. The rate limit documentation still "
        "describes the previous generation limits, and the published example "
        "payloads for the webhook signature verification are missing the new "
        "timestamp header. The field team reports that this costs them a "
        "conversation on roughly every third technical evaluation. The fix is a "
        "documentation pass plus a test that diffs the published examples against "
        "the live API on every release, so the drift cannot recur. This should be "
        "treated as a release-blocker for the next patch train."
    ),
    (
        "Mobile offline mode rounds out the board themes. The review workflows we "
        "see on mobile are almost always read-and-approve, which is exactly the "
        "workload that breaks when a reviewer is on a plane or in a building with "
        "poor coverage. The engineering estimate for a local-first read cache with "
        "deferred approval sync is three sprints, and the design partners on the "
        "board were unanimous that this would change their purchasing decision for "
        "the next renewal cycle. The counterargument is that the mobile team is "
        "already at capacity with the notification overhaul, so the roadmap "
        "decision is really about sequencing rather than feasibility."
    ),
    (
        "The win/loss analysis adds a cautionary note to the otherwise positive "
        "quarter. We won deals where the evaluation was driven by an individual "
        "champion, and lost deals where the evaluation involved a procurement "
        "review of the security documentation pack. The common thread in the losses "
        "is that our security pack is written for a technical audience and the "
        "procurement reviewers we lost to wanted a plain-language summary with "
        "clear answers to the standard questionnaire. The field team has drafted a "
        "two-page executive summary that sits in front of the technical pack, and "
        "the early feedback from the three most recent evaluations is that it "
        "resolves the objection in the first meeting."
    ),
    (
        "The support ticket themes round out the evidence base. The top ticket "
        "category this quarter was integration setup, driven almost entirely by the "
        "calendar sync failing silently when the account has more than one "
        "timezone configured. The second category was billing — specifically the "
        "confusion around seat-based pricing when an admin adds a member who "
        "already has a personal subscription. The third category was data export, "
        "where the CSV export omits the custom fields that several teams rely on "
        "for their internal reporting. Each of these has a clear fix and an owner, "
        "and they are itemized in the action plan section of this review."
    ),
    (
        "The metrics appendix deserves its own paragraph because the numbers "
        "anchor the discussion. Activation improved from 58% to 69% on the back of "
        "the setup-flow changes shipped in the previous quarter. Median time to "
        "first value dropped from nine days to five. The retention cohort chart "
        "shows a clear elbow at the ninety-day mark for teams that adopted the "
        "review workflow, which supports the argument that the workflow is the "
        "retention lever rather than a nice-to-have. The churn reasons survey, "
        "which we run quarterly with a sample of cancelled accounts, ranks "
        "onboarding difficulty first, price second, and missing integrations "
        "third — consistent with the board themes above."
    ),
    (
        "The action plan section translates the themes into concrete workstreams "
        "with owners and timelines. Workstream one, the invitation flow redesign, "
        "is owned by the growth team and scheduled for the current sprint cycle "
        "with a target of the next monthly release. Workstream two, the "
        "review-only permission preset, is owned by the platform team and scoped "
        "for the quarter after next pending the permissions redesign decision. "
        "Workstream three, audit log annotations, is owned by the trust team and "
        "sized at two weeks of engineering time. Workstream four, the API "
        "documentation pass, is owned by developer relations and is already in "
        "progress with the release-blocker status noted above. Workstream five, "
        "mobile offline mode, is owned by the mobile team and scheduled after the "
        "notification overhaul completes."
    ),
    (
        "The open questions for the roadmap are deliberately few and specific. "
        "First, whether the invitation flow redesign should ship behind the "
        "existing feature flag or to the default cohort with a kill switch — the "
        "growth team recommends the flag, the support team recommends the default "
        "cohort because the current flow is the top activation blocker. Second, "
        "whether the review-only preset should wait for the permissions redesign "
        "or ship as a standalone preset — the platform team recommends waiting, "
        "the design partners recommend shipping. Third, whether mobile offline "
        "mode should displace the notification overhaul in the mobile roadmap — "
        "the mobile team recommends keeping the current sequencing. Each of these "
        "decisions has a named owner and a decision deadline of the next "
        "leadership sync, and the expectation is that this review documents the "
        "options rather than resolving them."
    ),
    (
        "The appendix verbatims are included in full because the language "
        "customers use matters more than our summary of it. The most frequently "
        "repeated phrase in the board session was the request for the ability to "
        "see what changed and why, which appeared in the permissions, audit log, "
        "and mobile discussions alike. The second most repeated phrase was about "
        "the setup flow feeling like it was designed for a different company — "
        "the multi-workspace onboarding gap. The third was a direct quote from the "
        "largest account in the room asking for the documentation to be written "
        "for a person who has not used the product yet, which is the principle "
        "behind the proposed documentation rewrite. These verbatims are quoted "
        "with permission and anonymized in the appendix for the record."
    ),
    (
        "The financial framing completes the review. The feature investment this "
        "quarter totals roughly three engineer-months across the five workstreams, "
        "against a measured retention lift of two points per quarter from the "
        "previous cycle's onboarding investment. The board asked for the review to "
        "state the expected payback period for each workstream, and the finance "
        "team has provided ranges in the appendix: the invitation flow workstream "
        "is expected to pay back within two quarters, the permission preset within "
        "four, the audit annotations within three, the documentation pass "
        "immediately, and the mobile offline mode within six quarters if the "
        "renewal impact materializes as the design partners predict. These "
        "estimates carry the usual caveats and are deliberately ranges rather "
        "than points."
    ),
]


def _doc_chunk(i: int) -> str:
    """A ~7k-char chunk of the review document, with a heading."""
    body = _BASE_PARAS[i % len(_BASE_PARAS)]
    # Add a long, varied filler paragraph so chunks are big and distinct.
    filler = (
        f"Additionally, the working group compiled the following observations "
        f"during session {i + 1}: the dashboards for cohort {i % 7 + 1} show a "
        f"repeatable pattern where the weekly active count peaks on day {i % 5 + 2} "
        f"after each release, then settles into a plateau that tracks the "
        f"adoption of the review workflow. The team logged {i * 3 + 17} distinct "
        f"support interactions across the period, of which {i * 2 + 5} were "
        f"classified as setup-related and the remainder split between billing, "
        f"export, and integration questions. The field notes from the account "
        f"review call on iteration {i % 4 + 1} reinforce the same conclusion: "
        f"customers who complete the guided checklist within the first two "
        f"sessions are measurably more likely to reach the retention elbow at "
        f"day ninety, and the correlation holds when controlling for account "
        f"size, region, and plan tier. The proposal from the working group is "
        f"to treat the checklist completion rate as a first-class metric on the "
        f"executive dashboard, to instrument the invitation flow with the new "
        f"event schema, and to re-run the cohort analysis at the next monthly "
        f"sync with the updated attribution model that the data team finalized "
        f"in the previous cycle. The open items are tracked in the action plan "
        f"section of this review, and the appendix includes the raw session "
        f"notes for the record."
    )
    return f"Section {i + 1} of the review I'm working on:\n{body}\n\n{filler}"


TASK_TURNS = [
    "Add a todo to review the Q3 product review draft and send comments to the growth team.",
    "What todos do I have right now? List them with their status.",
    "Remind me to follow up with the design partners about the permission preset next Tuesday at 10am.",
    "Set a reminder for the leadership sync on Friday at 3pm.",
    "Create a note with the five board themes from the review so I can find them later.",
    "What's my earliest reminder this week?",
    "Add a todo to rewrite the API documentation examples before the next release.",
    "Mark the API documentation todo as done once I confirm the PR merged — check the todos first.",
]


def build_turns(n_doc_chunks: int = 26) -> list[str]:
    """The full script: doc-chunk turns interleaved with task turns."""
    turns: list[str] = []
    for i in range(n_doc_chunks):
        turns.append(
            _doc_chunk(i)
            + "\n\nQuestion: what should I change in this section? Reply in at most 3 short bullets."
        )
        if i % 5 == 2:
            turns.append(TASK_TURNS[(i // 5) % len(TASK_TURNS)])
    return turns


# --- driver ----------------------------------------------------------------


def _history_from_mongo(client: MongoClient, conv_id: str) -> list[dict[str, str]]:
    db = client.get_database()
    doc = db["conversations"].find_one({"conversation_id": conv_id})
    if not doc:
        return []
    out: list[dict[str, str]] = []
    for m in doc.get("messages", []):
        # Persisted messages use MessageModel's type/response fields
        # ("user"/"bot"); the wire format the client sends is role/content.
        mtype = m.get("type")
        content = m.get("response", "")
        if mtype in ("user", "bot") and isinstance(content, str) and content.strip():
            out.append({"role": "user" if mtype == "user" else "assistant", "content": content})
    return out


def _sum_usage(usage: dict[str, Any]) -> dict[str, int]:
    total = {"input": 0, "cached": 0, "output": 0}
    for v in usage.values():
        if not isinstance(v, dict):
            continue
        total["input"] += int(v.get("input_tokens") or 0)
        total["output"] += int(v.get("output_tokens") or 0)
        details = v.get("input_token_details") or {}
        total["cached"] += int(details.get("cache_read") or 0)
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8620/api/v1")
    parser.add_argument("--mongo", default="mongodb://localhost:27017/GAIA")
    parser.add_argument("--tag", default="run")
    parser.add_argument("--chunks", type=int, default=26)
    parser.add_argument("--out", default=None)
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()

    conv_id = args.conversation_id or None
    out_path = args.out or f"cache_run_{args.tag}.jsonl"
    turns = build_turns(args.chunks)
    client = MongoClient(args.mongo)

    print(f"tag={args.tag} conv={conv_id or '(server-minted)'} turns={len(turns)}")
    rows: list[dict[str, Any]] = []
    tot_in = tot_cached = tot_out = 0
    for i, text in enumerate(turns):
        history = _history_from_mongo(client, conv_id) if conv_id else []
        body = {
            "message": text,
            "conversation_id": conv_id,  # None on turn 0 -> server creates + returns id
            "messages": [*history, {"role": "user", "content": text}],
            "turn_id": str(uuid.uuid4()),
            "fileIds": [],
            "fileData": [],
            "use_default_models": True,
        }
        turn_usage: dict[str, int] = {"input": 0, "cached": 0, "output": 0}
        errors: list[str] = []
        started = time.monotonic()
        try:
            with httpx.Client(timeout=httpx.Timeout(300, connect=10)) as http:
                with http.stream("POST", f"{args.api}/chat-stream", json=body) as resp:
                    if resp.status_code != 200:
                        errors.append(f"http {resp.status_code}: {resp.read()[:200]!r}")
                    else:
                        for line in resp.iter_lines():
                            if not line.startswith("data: "):
                                continue
                            try:
                                payload = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue
                            if payload.get("conversation_id") and conv_id is None:
                                conv_id = payload["conversation_id"]
                            if payload.get("main_response_complete") and payload.get("usage"):
                                turn_usage = _sum_usage(payload["usage"])
                            if payload.get("error"):
                                errors.append(str(payload["error"])[:300])
        except httpx.HTTPError as e:
            errors.append(f"transport: {e}")
        elapsed = time.monotonic() - started

        # The turn persists even if the client disconnected — wait for Mongo.
        for _ in range(60):
            if conv_id and len(_history_from_mongo(client, conv_id)) > len(history) + 1:
                break
            time.sleep(1)
        time.sleep(2)

        hit = turn_usage["cached"] / turn_usage["input"] * 100 if turn_usage["input"] else 0.0
        tot_in += turn_usage["input"]
        tot_cached += turn_usage["cached"]
        tot_out += turn_usage["output"]
        row = {
            "turn": i,
            "conv": conv_id,
            "time": datetime.now(UTC).isoformat(),
            "input": turn_usage["input"],
            "cached": turn_usage["cached"],
            "output": turn_usage["output"],
            "hit_pct": round(hit, 2),
            "history_msgs": len(_history_from_mongo(client, conv_id)) if conv_id else 0,
            "elapsed_s": round(elapsed, 1),
            "errors": errors,
        }
        rows.append(row)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(
            f"turn {i:>2}: in={turn_usage['input']:>7} cached={turn_usage['cached']:>7} "
            f"hit={hit:5.1f}% out={turn_usage['output']:>5} hist={row['history_msgs']:>3} "
            f"{elapsed:5.1f}s {'ERR: ' + errors[0][:80] if errors else ''}"
        )

    tot_hit = tot_cached / tot_in * 100 if tot_in else 0.0
    in_price, cached_price, out_price = 0.00009, 0.000018, 0.00018
    cost = (
        (tot_in - tot_cached) / 1000 * in_price
        + tot_cached / 1000 * cached_price
        + tot_out / 1000 * out_price
    )
    cost_no_cache = tot_in / 1000 * in_price + tot_out / 1000 * out_price
    print(
        f"\nTOTAL: in={tot_in:,} cached={tot_cached:,} hit={tot_hit:.1f}% out={tot_out:,}\n"
        f"  input cost: ${cost:.4f} (vs ${cost_no_cache:.4f} at 0% cache) — "
        f"{100 * (1 - cost / cost_no_cache):.1f}% saved\n"
        f"  rows -> {out_path}"
    )


if __name__ == "__main__":
    main()
