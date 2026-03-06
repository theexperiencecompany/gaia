import type { ChatMessage } from "@/features/landing/components/demo/founders-demo/types";
import type { ToolStep } from "../types";
import AgencyProactiveCard from "./AgencyProactiveCard";
import BDPipelineCard from "./BDPipelineCard";
import ClientReportCard from "./ClientReportCard";
import PortfolioBriefCard from "./PortfolioBriefCard";

export const AGENCY_PROACTIVE_MESSAGES: ChatMessage[] = [
  {
    id: "ag-pr1",
    role: "assistant",
    content:
      "While you were presenting, I handled a few things across your portfolio:",
  },
  {
    id: "ag-pr2",
    role: "card",
    content: "",
    cardContent: <AgencyProactiveCard />,
    delay: 400,
  },
  {
    id: "ag-pr3",
    role: "assistant",
    content:
      "ByteScale's deliverable is 3 days behind — the content brief wasn't received. I've drafted a follow-up to their PM. Want me to send it?",
    delay: 600,
  },
];

export const PORTFOLIO_BRIEF_TOOLS: ToolStep[] = [
  {
    category: "clickup",
    name: "clickup_list_tasks",
    message: "Scanning ClickUp projects",
  },
  {
    category: "asana",
    name: "asana_list_tasks",
    message: "Checking Asana boards",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Scanning client emails",
  },
  {
    category: "googlecalendar",
    name: "calendar_list_events",
    message: "Loading client meetings",
  },
];

export const PORTFOLIO_BRIEF_MESSAGES: ChatMessage[] = [
  {
    id: "ag-pb1",
    role: "user",
    content: "Give me a rundown on all active clients this morning.",
  },
  { id: "ag-pb2", role: "thinking", content: "", delay: 600 },
  {
    id: "ag-pb3",
    role: "tools",
    content: "",
    tools: PORTFOLIO_BRIEF_TOOLS,
    delay: 1000,
  },
  {
    id: "ag-pb4",
    role: "card",
    content: "",
    cardContent: <PortfolioBriefCard />,
    delay: 500,
  },
  {
    id: "ag-pb5",
    role: "assistant",
    content:
      "ByteScale is most urgent — 3 days behind on the content brief that was supposed to come from their side. Momentum is approaching scope creep territory: 14h over budget. Worth a conversation before it gets worse.",
    delay: 700,
  },
];

export const CLIENT_REPORT_TOOLS: ToolStep[] = [
  {
    category: "clickup",
    name: "clickup_list_tasks",
    message: "Pulling project progress",
  },
  {
    category: "googlesheets",
    name: "sheets_read",
    message: "Fetching metrics data",
  },
  {
    category: "gmail",
    name: "gmail_create_draft",
    message: "Drafting client report",
  },
];

export const CLIENT_REPORT_MESSAGES: ChatMessage[] = [
  {
    id: "ag-cr1",
    role: "user",
    content: "Draft the weekly status report for TechCorp.",
  },
  { id: "ag-cr2", role: "thinking", content: "", delay: 600 },
  {
    id: "ag-cr3",
    role: "tools",
    content: "",
    tools: CLIENT_REPORT_TOOLS,
    delay: 1200,
  },
  {
    id: "ag-cr4",
    role: "card",
    content: "",
    cardContent: <ClientReportCard />,
    delay: 500,
  },
  {
    id: "ag-cr5",
    role: "assistant",
    content:
      "Done. Pulled from ClickUp and your metrics sheet. Looks on track for a March 22 launch. Want me to send it or does it need your review first?",
    delay: 700,
  },
];

export const BD_PIPELINE_TOOLS: ToolStep[] = [
  {
    category: "hubspot",
    name: "hubspot_list_deals",
    message: "Scanning BD pipeline",
  },
  {
    category: "gmail",
    name: "gmail_list_emails",
    message: "Checking inbound leads",
  },
  {
    category: "linkedin",
    name: "linkedin_search",
    message: "Researching prospects",
  },
  {
    category: "perplexity",
    name: "perplexity_search",
    message: "Company research",
  },
];

export const BD_PIPELINE_MESSAGES: ChatMessage[] = [
  {
    id: "ag-bd1",
    role: "user",
    content: "Where does the new business pipeline stand?",
  },
  { id: "ag-bd2", role: "thinking", content: "", delay: 600 },
  {
    id: "ag-bd3",
    role: "tools",
    content: "",
    tools: BD_PIPELINE_TOOLS,
    delay: 1000,
  },
  {
    id: "ag-bd4",
    role: "card",
    content: "",
    cardContent: <BDPipelineCard />,
    delay: 500,
  },
  {
    id: "ag-bd5",
    role: "assistant",
    content:
      "HealthTech Co is the hottest lead — inbound this morning, ideal profile. I've sent an intro response and drafted a capabilities deck from your template. The CloudOps RFP is due Friday — want me to start on that now?",
    delay: 700,
  },
];
