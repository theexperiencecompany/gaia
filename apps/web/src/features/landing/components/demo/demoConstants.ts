import {
  Calendar03Icon,
  CheckListIcon,
  ConnectIcon,
  DashboardSquare02Icon,
  MessageMultiple02Icon,
  Target02Icon,
  ZapIcon,
} from "@icons";
import { demoEase } from "./demoAnimationConstants";
import type { DemoPage, UseCase } from "./types";

// ─── Animation helpers ────────────────────────────────────────────────────────
export const ease = demoEase;
export const tx = { duration: 0.18, ease };
export const slideUp = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

// ─── Animation timings (ms) ───────────────────────────────────────────────────
export const BASE_TIMINGS = {
  userMsg: 500,
  thinking: 900,
  loading1: 1900,
  loading2: 3200,
  toolCalls: 4600,
  botResponse: 5100,
  finalCard: 7000,
  done: 8600,
  loop: 14000,
};

// ─── Sidebar nav buttons ──────────────────────────────────────────────────────
export const NAV_BUTTONS: {
  Icon: React.ComponentType<{ width: number; height: number }>;
  label: string;
  page?: DemoPage;
}[] = [
  { Icon: DashboardSquare02Icon, label: "Dashboard", page: "dashboard" },
  { Icon: Calendar03Icon, label: "Calendar", page: "calendar" },
  { Icon: Target02Icon, label: "Goals", page: "goals" },
  { Icon: CheckListIcon, label: "Todos", page: "todos" },
  { Icon: ConnectIcon, label: "Integrations", page: "integrations" },
  { Icon: ZapIcon, label: "Workflows", page: "workflows" },
  { Icon: MessageMultiple02Icon, label: "Chats", page: "chats" },
];

// ─── Demo chat groups ─────────────────────────────────────────────────────────
export const CHAT_GROUPS: Record<
  string,
  { id: string; label: string; active?: boolean }[]
> = {
  Today: [
    { id: "t1", label: "HN + email digest", active: true },
    { id: "t2", label: "Plan my week" },
  ],
  Yesterday: [
    { id: "t3", label: "Summarize inbox" },
    { id: "t4", label: "Draft investor update" },
  ],
  "Last 30 days": [
    { id: "t5", label: "Book flight tickets" },
    { id: "t6", label: "Weekly retrospective" },
    { id: "t7", label: "Research competitors" },
  ],
};

// ─── Dummy notifications ──────────────────────────────────────────────────────
export const DUMMY_NOTIFICATIONS = [
  {
    id: "n1",
    title: "Morning briefing ready",
    body: "Your daily briefing has been prepared: 3 urgent emails, 2 meetings, 5 open tasks.",
    time: "2 minutes ago",
    tag: "system",
    unread: true,
  },
  {
    id: "n2",
    title: "Workflow completed",
    body: "Weekly Email Summary Digest has finished. 47 emails processed, 12 action items extracted.",
    time: "1 hour ago",
    tag: "workflow",
    unread: true,
  },
  {
    id: "n3",
    title: "Reminder: Investor call",
    body: "You have a call with Sequoia Capital in 30 minutes. Prep notes are ready.",
    time: "29 minutes ago",
    tag: "reminder",
    unread: false,
  },
  {
    id: "n4",
    title: "PR Review requested",
    body: "Alex requested your review on feat/auth-refactor. 23 files changed.",
    time: "3 hours ago",
    tag: "system",
    unread: false,
  },
];

// ─── Demo models ──────────────────────────────────────────────────────────────
export const DEMO_MODELS = [
  {
    id: "claude-sonnet-4-5-20250929",
    name: "Claude Sonnet 4.5",
    provider: "Anthropic",
    description: "Balanced performance and intelligence.",
    tier: "free",
    is_default: true,
    logo: "/images/logos/logo.webp",
  },
  {
    id: "claude-haiku-4-5-20251001",
    name: "Claude Haiku 4.5",
    provider: "Anthropic",
    description: "Fast and compact. Best for simple tasks.",
    tier: "free",
    is_default: false,
    logo: "/images/logos/logo.webp",
  },
  {
    id: "claude-opus-4-6",
    name: "Claude Opus 4.6",
    provider: "Anthropic",
    description: "Most capable. Best for complex reasoning.",
    tier: "pro",
    is_default: false,
    logo: "/images/logos/logo.webp",
  },
  {
    id: "gemini-3-flash",
    name: "Gemini 3 Flash",
    provider: "Google",
    description: "Fast and efficient for everyday tasks.",
    tier: "free",
    is_default: false,
    logo: "/images/icons/gemini.webp",
  },
  {
    id: "gemini-3-pro",
    name: "Gemini 3 Pro",
    provider: "Google",
    description: "Google's most advanced reasoning model.",
    tier: "pro",
    is_default: false,
    logo: "/images/icons/gemini.webp",
  },
  {
    id: "grok-4-1",
    name: "Grok 4.1",
    provider: "xAI",
    description: "xAI's latest model with real-time web access.",
    tier: "pro",
    is_default: false,
    logo: "/images/icons/grok.webp",
  },
];

export const MODEL_PROVIDERS = ["Anthropic", "Google", "xAI"];

// ─── Founder email for EmailComposeCard ───────────────────────────────────────
export const FOUNDER_EMAIL = {
  to: ["investors@sequoia.com"],
  subject: "GAIA — Q4 Update: 3x MRR, $2.1M ARR, Series A Prep",
  body: `Hi all,

Q4 Update — November 2025

→ MRR: $175K (+3x QoQ)
→ ARR: $2.1M run rate
→ DAU: 14,200 (+180% since last update)
→ Churn: 2.1% (down from 4.8%)

Heading into Series A. Happy to connect this week.

— Aryan`,
  thread_id: "demo-founder",
};

// ─── Use cases ────────────────────────────────────────────────────────────────
export const USE_CASES: UseCase[] = [
  {
    id: "founder",
    label: "Founder",
    emoji: "🚀",
    userMessage:
      "Draft my Q4 investor update from our metrics and recent emails",
    tools: [
      { category: "executor", name: "executor", message: "Starting executor" },
      {
        category: "retrieve_tools",
        name: "retrieve_tools",
        message: "Retrieving tools",
      },
      {
        category: "gmail",
        name: "gmail_list_emails",
        message: "Reading investor emails",
      },
      {
        category: "googlesheets",
        name: "sheets_read",
        message: "Pulling Q4 metrics",
      },
      {
        category: "gmail",
        name: "gmail_create_draft",
        message: "Composing update",
      },
    ],
    loadingTexts: [
      "GAIA is thinking...",
      "Reading investor emails",
      "Pulling Q4 metrics",
    ],
    botResponse:
      "I've drafted your Q4 investor update using 12 recent investor emails and your Google Sheets metrics. It covers 3x MRR growth, key milestones, and a Series A narrative — review and send when you're ready:",
    finalCard: "email",
  },
  {
    id: "developer",
    label: "Developer",
    emoji: "💻",
    userMessage: "Summarise my open PRs and post standup notes to Slack",
    tools: [
      { category: "executor", name: "executor", message: "Starting executor" },
      {
        category: "retrieve_tools",
        name: "retrieve_tools",
        message: "Retrieving tools",
      },
      {
        category: "github",
        name: "github_list_prs",
        message: "Fetching open PRs",
      },
      {
        category: "linear",
        name: "linear_list_issues",
        message: "Checking Linear tickets",
      },
      {
        category: "slack",
        name: "slack_post_message",
        message: "Posting to Slack",
      },
    ],
    loadingTexts: [
      "GAIA is thinking...",
      "Fetching GitHub PRs",
      "Checking Linear tickets",
    ],
    botResponse:
      "Here's your standup summary across 4 open PRs and 12 in-progress Linear tickets. I flagged 2 blockers needing attention and posted the full update to #engineering-standup on Slack:",
    finalCard: "workflow",
  },
  {
    id: "marketer",
    label: "Marketer",
    emoji: "📣",
    userMessage: "Schedule this week's social content based on top performers",
    tools: [
      { category: "executor", name: "executor", message: "Starting executor" },
      {
        category: "retrieve_tools",
        name: "retrieve_tools",
        message: "Retrieving tools",
      },
      {
        category: "twitter",
        name: "twitter_get_analytics",
        message: "Analysing engagement",
      },
      {
        category: "linkedin",
        name: "linkedin_draft_post",
        message: "Drafting LinkedIn post",
      },
      {
        category: "googlesheets",
        name: "sheets_append",
        message: "Logging to content calendar",
      },
    ],
    loadingTexts: [
      "GAIA is thinking...",
      "Analysing engagement metrics",
      "Drafting social content",
    ],
    botResponse:
      "Based on your top performers, data-led threads get 3× more engagement. I've drafted 2 posts — one for X on Monday morning and one for LinkedIn mid-week — and logged both to your content calendar:",
    finalCard: "tools",
  },
  {
    id: "student",
    label: "Student",
    emoji: "📚",
    userMessage: "Build my finals study plan for this week",
    tools: [
      { category: "executor", name: "executor", message: "Starting executor" },
      {
        category: "retrieve_tools",
        name: "retrieve_tools",
        message: "Retrieving tools",
      },
      {
        category: "googlecalendar",
        name: "calendar_list_events",
        message: "Checking deadlines",
      },
      {
        category: "notion",
        name: "notion_get_pages",
        message: "Reviewing lecture notes",
      },
      {
        category: "todoist",
        name: "todoist_create_tasks",
        message: "Creating study tasks",
      },
    ],
    loadingTexts: [
      "GAIA is thinking...",
      "Checking your calendar",
      "Reviewing your notes",
    ],
    botResponse:
      "Here's your finals study plan built around 3 upcoming deadlines and your Notion lecture notes. I've created 5 prioritised tasks starting Monday — high-priority chapters first, mock exam Thursday, revision Friday:",
    finalCard: "tasks",
  },
  {
    id: "executive",
    label: "Executive",
    emoji: "🎯",
    userMessage: "What's on my plate today? Give me my morning briefing",
    tools: [
      { category: "executor", name: "executor", message: "Starting executor" },
      {
        category: "retrieve_tools",
        name: "retrieve_tools",
        message: "Retrieving tools",
      },
      {
        category: "gmail",
        name: "gmail_list_emails",
        message: "Scanning inbox",
      },
      {
        category: "googlecalendar",
        name: "calendar_list_events",
        message: "Loading meetings",
      },
      {
        category: "slack",
        name: "slack_list_messages",
        message: "Checking Slack",
      },
    ],
    loadingTexts: [
      "GAIA is thinking...",
      "Scanning your inbox",
      "Loading today's meetings",
    ],
    botResponse:
      "Good morning! You have 4 meetings back-to-back from 9:30 AM, 3 urgent emails including a term sheet from Alex Chen, and 2 Slack threads in #engineering waiting on your input. Here's the full breakdown:",
    finalCard: "briefing",
  },
];
