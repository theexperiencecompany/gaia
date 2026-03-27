"use client";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";
import type { ToolStep } from "../../demo/types";

// ─── Tool Steps ────────────────────────────────────────────────────────────────

const GITHUB_PR_TOOLS: ToolStep[] = [
  {
    category: "github",
    name: "list_pull_requests",
    message: "Fetching open pull requests",
  },
];

// ─── PR Summary Card ───────────────────────────────────────────────────────────

const PR_ITEMS = [
  {
    id: "pr-1",
    number: 42,
    title: "feat: add streaming support to chat API",
    status: "Changes requested",
    statusColor: "text-amber-400",
    statusBg: "bg-amber-400/10",
    branch: "feat/streaming-chat",
    comments: 3,
  },
  {
    id: "pr-2",
    number: 38,
    title: "fix: resolve race condition in auth token refresh",
    status: "Review pending",
    statusColor: "text-blue-400",
    statusBg: "bg-blue-400/10",
    branch: "fix/token-refresh",
    comments: 1,
  },
  {
    id: "pr-3",
    number: 35,
    title: "chore: upgrade dependencies to latest stable",
    status: "Draft",
    statusColor: "text-zinc-400",
    statusBg: "bg-zinc-700/50",
    branch: "chore/dep-upgrade",
    comments: 0,
  },
];

function GitHubPRSummaryCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-2">
        <div className="flex h-4 w-4 shrink-0 items-center justify-center">
          {getToolCategoryIcon("github", {
            width: 14,
            height: 14,
            showBackground: false,
          })}
        </div>
        <span className="text-[11px] font-medium text-zinc-400">
          3 open pull requests
        </span>
      </div>
      <div className="space-y-2">
        {PR_ITEMS.map((pr) => (
          <div key={pr.id} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-200">
                  {pr.title}
                </p>
                <p className="mt-0.5 text-xs text-zinc-500">
                  #{pr.number} · {pr.branch}
                </p>
              </div>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${pr.statusBg} ${pr.statusColor}`}
              >
                {pr.status}
              </span>
            </div>
            {pr.comments > 0 && (
              <p className="mt-1.5 text-xs text-zinc-500">
                {pr.comments} comment{pr.comments > 1 ? "s" : ""}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Messages ─────────────────────────────────────────────────────────────────

const SMART_CHAT_MESSAGES: ChatMessage[] = [
  {
    id: "sc1",
    role: "user",
    content: "Summarize my top 3 open GitHub PRs",
  },
  {
    id: "sc2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "sc3",
    role: "tools",
    content: "",
    tools: GITHUB_PR_TOOLS,
    delay: 900,
  },
  {
    id: "sc4",
    role: "card",
    content: "",
    cardContent: <GitHubPRSummaryCard />,
    delay: 500,
  },
  {
    id: "sc5",
    role: "assistant",
    content:
      "PR #42 needs your attention most — a reviewer requested changes 2 days ago. PR #38 is ready for you to review. PR #35 is still a draft.",
    delay: 700,
  },
];

// ─── Component ─────────────────────────────────────────────────────────────────

export default function SmartChatDemo() {
  return (
    <div className="w-full">
      <ChatDemo messages={SMART_CHAT_MESSAGES} minHeight={260} />
    </div>
  );
}
