import type { ChatMessage } from "@/features/landing/components/demo/founders-demo/types";
import type { ToolStep } from "../types";
import FeatureDigestCard from "./FeatureDigestCard";
import PMProactiveCard from "./PMProactiveCard";
import ProductBriefCard from "./ProductBriefCard";
import StakeholderUpdateCard from "./StakeholderUpdateCard";

export const PM_PROACTIVE_MESSAGES: ChatMessage[] = [
  {
    id: "pm-pr1",
    role: "assistant",
    content: "While you were in user interviews, a few things landed:",
  },
  {
    id: "pm-pr2",
    role: "card",
    content: "",
    cardContent: <PMProactiveCard />,
    delay: 400,
  },
  {
    id: "pm-pr3",
    role: "assistant",
    content:
      "The mobile checkout sprint is 2 days behind — ENG-445 is blocked on a design decision. Want me to flag it in Slack before tomorrow's planning?",
    delay: 600,
  },
];

export const PRODUCT_BRIEF_TOOLS: ToolStep[] = [
  {
    category: "linear",
    name: "linear_list_issues",
    message: "Checking sprint progress",
  },
  {
    category: "github",
    name: "github_list_commits",
    message: "Loading recent deploys",
  },
  {
    category: "slack",
    name: "slack_list_messages",
    message: "Scanning team threads",
  },
  {
    category: "googlecalendar",
    name: "calendar_list_events",
    message: "Loading today's meetings",
  },
];

export const PRODUCT_BRIEF_MESSAGES: ChatMessage[] = [
  {
    id: "pm-pb1",
    role: "user",
    content: "Give me a quick product status before my 10am.",
  },
  { id: "pm-pb2", role: "thinking", content: "", delay: 600 },
  {
    id: "pm-pb3",
    role: "tools",
    content: "",
    tools: PRODUCT_BRIEF_TOOLS,
    delay: 1000,
  },
  {
    id: "pm-pb4",
    role: "card",
    content: "",
    cardContent: <ProductBriefCard />,
    delay: 500,
  },
  {
    id: "pm-pb5",
    role: "assistant",
    content:
      "ENG-445 is blocking the mobile checkout — it needs your call on the payment error UI. 8 minutes, you can unblock it now before sprint planning.",
    delay: 700,
  },
];

export const STAKEHOLDER_TOOLS: ToolStep[] = [
  {
    category: "linear",
    name: "linear_list_issues",
    message: "Pulling sprint metrics",
  },
  {
    category: "github",
    name: "github_list_commits",
    message: "Fetching release notes",
  },
  {
    category: "notion",
    name: "notion_read_page",
    message: "Reading roadmap context",
  },
  {
    category: "gmail",
    name: "gmail_create_draft",
    message: "Drafting update",
  },
];

export const STAKEHOLDER_MESSAGES: ChatMessage[] = [
  {
    id: "pm-sh1",
    role: "user",
    content: "Draft my weekly stakeholder update for the CEO review at 2pm.",
  },
  { id: "pm-sh2", role: "thinking", content: "", delay: 600 },
  {
    id: "pm-sh3",
    role: "tools",
    content: "",
    tools: STAKEHOLDER_TOOLS,
    delay: 1200,
  },
  {
    id: "pm-sh4",
    role: "card",
    content: "",
    cardContent: <StakeholderUpdateCard />,
    delay: 500,
  },
  {
    id: "pm-sh5",
    role: "assistant",
    content:
      "Done. Pulled from Linear and GitHub — covers sprint progress, what shipped, and the one decision that's blocking mobile checkout. Ready to paste or email.",
    delay: 700,
  },
];

export const FEATURE_TRIAGE_TOOLS: ToolStep[] = [
  {
    category: "slack",
    name: "slack_list_messages",
    message: "Scanning #feedback channel",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Scanning customer emails",
  },
  {
    category: "intercom",
    name: "intercom_list_tickets",
    message: "Checking support tickets",
  },
  {
    category: "linear",
    name: "linear_create_issue",
    message: "Creating triaged tickets",
  },
];

export const FEATURE_TRIAGE_MESSAGES: ChatMessage[] = [
  {
    id: "pm-ft1",
    role: "user",
    content: "What feature requests came in this week?",
  },
  { id: "pm-ft2", role: "thinking", content: "", delay: 600 },
  {
    id: "pm-ft3",
    role: "tools",
    content: "",
    tools: FEATURE_TRIAGE_TOOLS,
    delay: 1000,
  },
  {
    id: "pm-ft4",
    role: "card",
    content: "",
    cardContent: <FeatureDigestCard />,
    delay: 500,
  },
  {
    id: "pm-ft5",
    role: "assistant",
    content:
      "11 requests across 4 themes. API integrations are the loudest signal — 5 requests in 5 days. The SAML SSO request is from TechCorp (your $91K prospect). Should that jump the queue?",
    delay: 700,
  },
];
