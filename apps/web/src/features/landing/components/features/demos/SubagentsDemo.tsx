"use client";

import { ChatBotIcon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";
import type { ToolStep } from "../../demo/types";

// ─── Tool Steps ────────────────────────────────────────────────────────────────

const SUBAGENT_TOOLS: ToolStep[] = [
  {
    category: "executor",
    name: "route_to_subagent",
    message: "github-agent",
  },
];

// ─── GitHub Agent Activation Card ─────────────────────────────────────────────

const REVIEWED_PRS = [
  {
    id: "rpr-1",
    number: 47,
    title: "feat: add rate limiting to API endpoints",
  },
  {
    id: "rpr-2",
    number: 52,
    title: "fix: resolve null ref in user settings page",
  },
  { id: "rpr-3", number: 61, title: "chore: migrate CI to GitHub Actions v4" },
];

function GitHubAgentCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-blue-400/10">
            <ChatBotIcon width={15} height={15} className="text-blue-400" />
          </div>
          <span className="text-sm font-semibold text-zinc-100">
            GitHub Agent
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-400" />
          </span>
          <span className="text-xs font-medium text-blue-400">Active</span>
        </div>
      </div>
      <div className="mb-2.5 flex items-center gap-1.5">
        <div className="flex h-4 w-4 shrink-0 items-center justify-center">
          {getToolCategoryIcon("github", {
            width: 13,
            height: 13,
            showBackground: false,
          })}
        </div>
        <span className="text-[11px] font-medium text-zinc-400">
          Reviewing 3 open pull requests
        </span>
      </div>
      <div className="space-y-2">
        {REVIEWED_PRS.map((pr) => (
          <div key={pr.id} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm font-medium text-zinc-200">
                {pr.title}
              </p>
              <span className="shrink-0 rounded-full bg-blue-400/10 px-2 py-0.5 text-[10px] font-medium text-blue-400">
                PR #{pr.number}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Messages ─────────────────────────────────────────────────────────────────

const SUBAGENTS_MESSAGES: ChatMessage[] = [
  {
    id: "sa1",
    role: "user",
    content: "Handle my open GitHub PRs — summarize and add review comments",
  },
  {
    id: "sa2",
    role: "thinking",
    content: "Routing to GitHub specialist agent...",
    delay: 600,
  },
  {
    id: "sa3",
    role: "tools",
    content: "",
    tools: SUBAGENT_TOOLS,
    delay: 900,
  },
  {
    id: "sa4",
    role: "card",
    content: "",
    cardContent: <GitHubAgentCard />,
    delay: 500,
  },
  {
    id: "sa5",
    role: "assistant",
    content:
      "Reviewed 3 open PRs. Added review comments to PR #47, PR #52, PR #61.",
    delay: 700,
  },
];

// ─── Component ─────────────────────────────────────────────────────────────────

export default function SubagentsDemo() {
  return (
    <div className="w-full">
      <ChatDemo messages={SUBAGENTS_MESSAGES} minHeight={260} />
    </div>
  );
}
