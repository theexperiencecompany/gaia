import type { ChatMessage } from "../founders-demo/types";
import type { ToolStep } from "../types";
import DevProactiveCard from "./DevProactiveCard";
import IncidentCard from "./IncidentCard";
import PRReviewCard from "./PRReviewCard";
import StandupCard from "./StandupCard";

// ─── Tool Definitions ────────────────────────────────────────────────

export const STANDUP_TOOLS: ToolStep[] = [
  {
    category: "github",
    name: "github_list_pull_requests",
    message: "Checking merged PRs",
  },
  {
    category: "linear",
    name: "linear_list_issues",
    message: "Loading completed tickets",
  },
  {
    category: "slack",
    name: "slack_list_messages",
    message: "Scanning team threads",
  },
  {
    category: "googlecalendar",
    name: "calendar_list_events",
    message: "Checking today's meetings",
  },
];

export const PR_TOOLS: ToolStep[] = [
  {
    category: "github",
    name: "github_list_pull_requests",
    message: "Scanning open PRs",
  },
  {
    category: "github",
    name: "github_get_pull_request",
    message: "Summarizing changes",
  },
  {
    category: "slack",
    name: "slack_list_messages",
    message: "Checking PR discussions",
  },
];

export const INCIDENT_TOOLS: ToolStep[] = [
  {
    category: "sentry",
    name: "sentry_list_issues",
    message: "Scanning error reports",
  },
  {
    category: "github",
    name: "github_list_commits",
    message: "Checking recent deploys",
  },
  {
    category: "slack",
    name: "slack_create_message",
    message: "Alerting #oncall",
  },
];

// ─── Message Arrays ──────────────────────────────────────────────────

export const PROACTIVE_MESSAGES: ChatMessage[] = [
  {
    id: "dev-pr1",
    role: "assistant",
    content: "While you were coding, I took care of a few things:",
  },
  {
    id: "dev-pr2",
    role: "card",
    content: "",
    cardContent: <DevProactiveCard />,
    delay: 400,
  },
  {
    id: "dev-pr3",
    role: "assistant",
    content:
      "The Sentry error on /api/auth is marked P1 — want me to draft a Slack message to the #oncall channel?",
    delay: 600,
  },
];

export const STANDUP_MESSAGES: ChatMessage[] = [
  {
    id: "dev-st1",
    role: "user",
    content: "Write my standup for today.",
  },
  {
    id: "dev-st2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "dev-st3",
    role: "tools",
    content: "",
    tools: STANDUP_TOOLS,
    delay: 1000,
  },
  {
    id: "dev-st4",
    role: "card",
    content: "",
    cardContent: <StandupCard />,
    delay: 500,
  },
  {
    id: "dev-st5",
    role: "assistant",
    content: "Done. Ready to post to #engineering-standup. Want me to send it?",
    delay: 700,
  },
];

export const PR_MESSAGES: ChatMessage[] = [
  {
    id: "dev-pr1r",
    role: "user",
    content: "Which PRs need my attention today?",
  },
  {
    id: "dev-pr2r",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "dev-pr3r",
    role: "tools",
    content: "",
    tools: PR_TOOLS,
    delay: 1000,
  },
  {
    id: "dev-pr4r",
    role: "card",
    content: "",
    cardContent: <PRReviewCard />,
    delay: 500,
  },
  {
    id: "dev-pr5r",
    role: "assistant",
    content:
      "Start with #214 — it's 3 days old and blocks the auth release. I've summarized the 23 changed files. Want the highlights?",
    delay: 700,
  },
];

export const INCIDENT_MESSAGES: ChatMessage[] = [
  {
    id: "dev-inc1",
    role: "assistant",
    content:
      "P1 alert: /api/payments/webhook is erroring at 847/min — started 3 minutes ago.",
  },
  {
    id: "dev-inc2",
    role: "card",
    content: "",
    cardContent: <IncidentCard />,
    delay: 400,
  },
  {
    id: "dev-inc3",
    role: "assistant",
    content:
      "Rollback PR is drafted. The error traces to the Stripe webhook change in the last deploy. Want me to merge it?",
    delay: 600,
  },
];
