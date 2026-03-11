import type { ChatMessage } from "@/features/landing/components/demo/founders-demo/types";
import type { ToolStep } from "../types";
import EMProactiveCard from "./EMProactiveCard";
import OneOnOnePrepCard from "./OneOnOnePrepCard";
import SprintReportCard from "./SprintReportCard";
import TeamHealthCard from "./TeamHealthCard";

export const EM_PROACTIVE_MESSAGES: ChatMessage[] = [
  {
    id: "em-pr1",
    role: "assistant",
    content: "While you were in leadership sync, a few things surfaced:",
  },
  {
    id: "em-pr2",
    role: "card",
    content: "",
    cardContent: <EMProactiveCard />,
    delay: 400,
  },
  {
    id: "em-pr3",
    role: "assistant",
    content:
      "PR #214 has been waiting for review for 4 days — it's blocking the auth release. Alex is the author. Want me to flag it in Slack or draft a nudge?",
    delay: 600,
  },
];

export const TEAM_HEALTH_TOOLS: ToolStep[] = [
  {
    category: "github",
    name: "github_list_pull_requests",
    message: "Checking PR cycle times",
  },
  {
    category: "linear",
    name: "linear_list_issues",
    message: "Pulling sprint velocity",
  },
  {
    category: "slack",
    name: "slack_list_messages",
    message: "Scanning team threads",
  },
];

export const TEAM_HEALTH_MESSAGES: ChatMessage[] = [
  { id: "em-th1", role: "user", content: "How's the team doing this sprint?" },
  { id: "em-th2", role: "thinking", content: "", delay: 600 },
  {
    id: "em-th3",
    role: "tools",
    content: "",
    tools: TEAM_HEALTH_TOOLS,
    delay: 1000,
  },
  {
    id: "em-th4",
    role: "card",
    content: "",
    cardContent: <TeamHealthCard />,
    delay: 500,
  },
  {
    id: "em-th5",
    role: "assistant",
    content:
      "PR cycle time jumped from 12h to 18h — mostly driven by PR #214 sitting unreviewed for 4 days. Dev is out until Thursday and ENG-412 needs reassignment. Want me to handle both?",
    delay: 700,
  },
];

export const ONE_ON_ONE_TOOLS: ToolStep[] = [
  {
    category: "github",
    name: "github_list_pull_requests",
    message: "Checking Alex's PRs",
  },
  {
    category: "linear",
    name: "linear_list_issues",
    message: "Loading completed tickets",
  },
  {
    category: "slack",
    name: "slack_list_messages",
    message: "Scanning relevant threads",
  },
  {
    category: "googlecalendar",
    name: "calendar_list_events",
    message: "Checking 1:1 history",
  },
];

export const ONE_ON_ONE_MESSAGES: ChatMessage[] = [
  {
    id: "em-oo1",
    role: "user",
    content: "Prep me for my 1:1 with Alex at 2pm.",
  },
  { id: "em-oo2", role: "thinking", content: "", delay: 600 },
  {
    id: "em-oo3",
    role: "tools",
    content: "",
    tools: ONE_ON_ONE_TOOLS,
    delay: 1200,
  },
  {
    id: "em-oo4",
    role: "card",
    content: "",
    cardContent: <OneOnOnePrepCard />,
    delay: 500,
  },
  {
    id: "em-oo5",
    role: "assistant",
    content:
      "Alex has had a strong sprint but PR #214 is stalling things. The API schema decision is yours to make — she mentioned it in Slack on March 1. Worth resolving before the 1:1.",
    delay: 700,
  },
];

export const SPRINT_REPORT_TOOLS: ToolStep[] = [
  {
    category: "linear",
    name: "linear_list_issues",
    message: "Pulling sprint data",
  },
  {
    category: "github",
    name: "github_list_pull_requests",
    message: "Calculating cycle times",
  },
  {
    category: "notion",
    name: "notion_create_page",
    message: "Building retro doc",
  },
  {
    category: "slack",
    name: "slack_create_message",
    message: "Posting to team",
  },
];

export const SPRINT_REPORT_MESSAGES: ChatMessage[] = [
  {
    id: "em-sr1",
    role: "user",
    content: "Build the Sprint 24 retro report before the meeting.",
  },
  { id: "em-sr2", role: "thinking", content: "", delay: 600 },
  {
    id: "em-sr3",
    role: "tools",
    content: "",
    tools: SPRINT_REPORT_TOOLS,
    delay: 1200,
  },
  {
    id: "em-sr4",
    role: "card",
    content: "",
    cardContent: <SprintReportCard />,
    delay: 500,
  },
  {
    id: "em-sr5",
    role: "assistant",
    content:
      "Done. Posted to Notion and #engineering. PR cycle time is the main theme — worth making it a retro topic. Should I add a discussion prompt to the doc?",
    delay: 700,
  },
];
