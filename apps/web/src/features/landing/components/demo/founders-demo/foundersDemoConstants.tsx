import { DemoFinalCard } from "../DemoFinalCards";
import type { ToolStep } from "../types";
import InvestorMetricsCard from "./InvestorMetricsCard";
import MorningBriefingCard from "./MorningBriefingCard";
import PipelineCard from "./PipelineCard";
import ProactiveCard from "./ProactiveCard";
import type { ChatMessage } from "./types";

// ─── Tool Definitions ────────────────────────────────────────────────

export const BRIEFING_TOOLS: ToolStep[] = [
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Scanning inbox — 4 urgent",
  },
  {
    category: "googlecalendar",
    name: "calendar_list_events",
    message: "Loading today's calendar",
  },
  {
    category: "slack",
    name: "slack_list_messages",
    message: "Checking Slack threads",
  },
  {
    category: "github",
    name: "github_list_notifications",
    message: "Checking GitHub alerts",
  },
];

export const INVESTOR_TOOLS: ToolStep[] = [
  {
    category: "googlesheets",
    name: "sheets_read",
    message: "Pulling latest metrics",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Scanning investor threads",
  },
  {
    category: "gmail",
    name: "gmail_create_draft",
    message: "Composing update draft",
  },
];

export const PIPELINE_TOOLS: ToolStep[] = [
  {
    category: "hubspot",
    name: "hubspot_list_deals",
    message: "Scanning active deals",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Checking follow-up threads",
  },
  {
    category: "linkedin",
    name: "linkedin_search",
    message: "Checking contact updates",
  },
];

// ─── Message Arrays ──────────────────────────────────────────────────

export const BRIEFING_MESSAGES: ChatMessage[] = [
  {
    id: "b1",
    role: "user",
    content: "What do I need to know before my 9am?",
  },
  {
    id: "b2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "b3",
    role: "tools",
    content: "",
    tools: BRIEFING_TOOLS,
    delay: 1000,
  },
  {
    id: "b4",
    role: "card",
    content: "",
    cardContent: <MorningBriefingCard />,
    delay: 500,
  },
  {
    id: "b5",
    role: "assistant",
    content:
      "Board sync at 2pm is your highest priority — your Q4 deck isn't ready. I can draft the key slides from your metrics if you want.",
    delay: 700,
  },
];

export const INVESTOR_MESSAGES: ChatMessage[] = [
  {
    id: "inv1",
    role: "user",
    content: "Draft my February investor update with our latest numbers.",
  },
  {
    id: "inv2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "inv3",
    role: "tools",
    content: "",
    tools: INVESTOR_TOOLS,
    delay: 1200,
  },
  {
    id: "inv4",
    role: "card",
    content: "",
    cardContent: <InvestorMetricsCard />,
    delay: 500,
  },
  {
    id: "inv5",
    role: "assistant",
    content:
      "Done. I pulled MRR, customers, and churn from your Google Sheets and referenced 3 recent investor threads. The draft covers growth, key wins, and your Series A timeline — ready for review.",
    delay: 700,
  },
  {
    id: "inv6",
    role: "card",
    content: "",
    cardContent: <DemoFinalCard type="email" />,
    delay: 400,
  },
];

export const PROACTIVE_MESSAGES: ChatMessage[] = [
  {
    id: "pr1",
    role: "assistant",
    content:
      "While you were in meetings, I noticed a few things and handled them:",
  },
  {
    id: "pr2",
    role: "card",
    content: "",
    cardContent: <ProactiveCard />,
    delay: 400,
  },
  {
    id: "pr3",
    role: "assistant",
    content:
      "The Acme follow-up is queued — want me to send it? Their trial expires Friday.",
    delay: 600,
  },
];

export const PIPELINE_MESSAGES: ChatMessage[] = [
  {
    id: "p1",
    role: "user",
    content: "Which deals need my attention this week?",
  },
  {
    id: "p2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "p3",
    role: "tools",
    content: "",
    tools: PIPELINE_TOOLS,
    delay: 1000,
  },
  {
    id: "p4",
    role: "card",
    content: "",
    cardContent: <PipelineCard />,
    delay: 500,
  },
  {
    id: "p5",
    role: "assistant",
    content:
      "Acme Corp is the most urgent — their trial expires Friday and they haven't scheduled onboarding. I've drafted a check-in email. Want me to send it?",
    delay: 700,
  },
];
