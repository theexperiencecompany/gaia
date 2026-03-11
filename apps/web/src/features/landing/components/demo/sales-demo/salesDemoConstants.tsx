import type { ChatMessage } from "@/features/landing/components/demo/founders-demo/types";
import type { ToolStep } from "../types";
import FollowUpQueueCard from "./FollowUpQueueCard";
import MeetingPrepCard from "./MeetingPrepCard";
import PipelineBriefCard from "./PipelineBriefCard";
import SalesProactiveCard from "./SalesProactiveCard";

// ─── Section 1: Proactive AI ──────────────────────────────────────────────────

export const SALES_PROACTIVE_MESSAGES: ChatMessage[] = [
  {
    id: "sp1",
    role: "assistant",
    content:
      "While you were presenting, I caught a few things in your pipeline:",
  },
  {
    id: "sp2",
    role: "card",
    content: "",
    cardContent: <SalesProactiveCard />,
    delay: 400,
  },
  {
    id: "sp3",
    role: "assistant",
    content:
      "Acme's trial expires Friday and they haven't booked onboarding. Follow-up email is drafted. Want me to send it?",
    delay: 600,
  },
];

// ─── Section 2: Morning Pipeline Brief ───────────────────────────────────────

export const PIPELINE_BRIEF_TOOLS: ToolStep[] = [
  {
    category: "hubspot",
    name: "hubspot_list_deals",
    message: "Scanning pipeline",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Checking deal threads",
  },
  {
    category: "googlecalendar",
    name: "calendar_list_events",
    message: "Loading today's calls",
  },
  {
    category: "linkedin",
    name: "linkedin_search",
    message: "Checking contact activity",
  },
];

export const PIPELINE_BRIEF_MESSAGES: ChatMessage[] = [
  {
    id: "pb1",
    role: "user",
    content: "What's my pipeline situation this morning?",
  },
  { id: "pb2", role: "thinking", content: "", delay: 600 },
  {
    id: "pb3",
    role: "tools",
    content: "",
    tools: PIPELINE_BRIEF_TOOLS,
    delay: 1000,
  },
  {
    id: "pb4",
    role: "card",
    content: "",
    cardContent: <PipelineBriefCard />,
    delay: 500,
  },
  {
    id: "pb5",
    role: "assistant",
    content:
      "Acme is most urgent — trial expires Friday, no onboarding scheduled. I've drafted a check-in email. Want me to send it before your 11am?",
    delay: 700,
  },
];

// ─── Section 3: Meeting Prep ──────────────────────────────────────────────────

export const MEETING_PREP_TOOLS: ToolStep[] = [
  {
    category: "linkedin",
    name: "linkedin_search",
    message: "Researching prospect",
  },
  {
    category: "hubspot",
    name: "hubspot_get_deal",
    message: "Pulling deal context",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Reading email history",
  },
  {
    category: "perplexity",
    name: "perplexity_search",
    message: "Company recent news",
  },
];

export const MEETING_PREP_MESSAGES: ChatMessage[] = [
  {
    id: "mp1",
    role: "user",
    content: "I have a call with ByteScale at 11am. Prep me.",
  },
  { id: "mp2", role: "thinking", content: "", delay: 600 },
  {
    id: "mp3",
    role: "tools",
    content: "",
    tools: MEETING_PREP_TOOLS,
    delay: 1200,
  },
  {
    id: "mp4",
    role: "card",
    content: "",
    cardContent: <MeetingPrepCard />,
    delay: 500,
  },
  {
    id: "mp5",
    role: "assistant",
    content:
      "Sarah is the decision maker but the CTO is now involved. Their biggest concern will be data residency — I'd lead with your SOC 2 cert before they ask.",
    delay: 700,
  },
];

// ─── Section 4: Follow-Ups ────────────────────────────────────────────────────

export const FOLLOW_UP_TOOLS: ToolStep[] = [
  {
    category: "hubspot",
    name: "hubspot_list_deals",
    message: "Scanning stalled deals",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Checking last contact dates",
  },
  {
    category: "gmail",
    name: "gmail_create_draft",
    message: "Drafting follow-ups",
  },
];

export const FOLLOW_UP_MESSAGES: ChatMessage[] = [
  {
    id: "fu1",
    role: "user",
    content: "Which deals need follow-ups this week?",
  },
  { id: "fu2", role: "thinking", content: "", delay: 600 },
  {
    id: "fu3",
    role: "tools",
    content: "",
    tools: FOLLOW_UP_TOOLS,
    delay: 1000,
  },
  {
    id: "fu4",
    role: "card",
    content: "",
    cardContent: <FollowUpQueueCard />,
    delay: 500,
  },
  {
    id: "fu5",
    role: "assistant",
    content:
      "5 drafts are queued. Acme is most urgent — trial ends Friday. Want me to send the first three now?",
    delay: 700,
  },
];
