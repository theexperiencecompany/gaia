"use client";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";
import type { ToolStep } from "../../demo/types";

// ─── Tool Definitions ────────────────────────────────────────────────

const EMAIL_TOOLS: ToolStep[] = [
  {
    category: "gmail",
    name: "list_messages",
    message: "Fetching unread emails",
  },
  {
    category: "gmail",
    name: "get_message",
    message: "Reading urgent email from Sequoia",
  },
];

// ─── Draft Reply Card ────────────────────────────────────────────────

function DraftReplyCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-fit min-w-[400px]">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("gmail", {
          width: 16,
          height: 16,
          showBackground: false,
        })}
        <span className="text-[11px] font-medium text-zinc-400">
          Draft reply ready to send
        </span>
      </div>
      <div className="rounded-2xl bg-zinc-900 p-3 space-y-2">
        <div className="flex items-baseline gap-2">
          <span className="text-xs text-zinc-500 w-14 shrink-0">To</span>
          <span className="text-sm text-zinc-200">
            sarah.chen@sequoiacap.com
          </span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-xs text-zinc-500 w-14 shrink-0">Subject</span>
          <span className="text-sm text-zinc-200">
            Re: Series A — scheduling next week
          </span>
        </div>
        <div className="border-t border-zinc-800 pt-2">
          <p className="text-xs text-zinc-400 leading-relaxed">
            Hi Sarah, thanks for reaching out. I'd love to connect next week.
            Tuesday or Wednesday afternoon works best for me — happy to do 30
            minutes to discuss the round. I'll send a calendar invite once you
            confirm.
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── Email Summary Card ──────────────────────────────────────────────

const EMAIL_SUMMARIES = [
  {
    id: "es-1",
    sender: "Sequoia Capital",
    subject: "Series A follow-up",
    preview: "Wants to schedule a call next week to discuss the round",
    urgency: "urgent",
  },
  {
    id: "es-2",
    sender: "David Kim (CTO)",
    subject: "Prod outage — needs decision",
    preview: "Deployment blocker requires your approval before EOD",
    urgency: "urgent",
  },
  {
    id: "es-3",
    sender: "Acme Corp",
    subject: "Enterprise contract renewal",
    preview: "Renewal docs attached, legal review requested by Friday",
    urgency: "normal",
  },
];

function EmailSummaryCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-fit min-w-[400px]">
      <div className="mb-3 flex items-center gap-2">
        {getToolCategoryIcon("gmail", {
          width: 16,
          height: 16,
          showBackground: false,
        })}
        <span className="text-[11px] font-medium text-zinc-400">
          Top 3 unread emails
        </span>
      </div>
      <div className="space-y-2">
        {EMAIL_SUMMARIES.map((email) => (
          <div key={email.id} className="rounded-2xl bg-zinc-900 p-3">
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-sm font-medium text-zinc-200">
                {email.sender}
              </span>
              {email.urgency === "urgent" && (
                <span className="text-[10px] font-medium rounded-full bg-red-400/10 text-red-400 px-2 py-0.5">
                  Urgent
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-400">{email.subject}</p>
            <p className="text-xs text-zinc-500 mt-0.5">{email.preview}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Message Array ───────────────────────────────────────────────────

const EMAIL_MESSAGES: ChatMessage[] = [
  {
    id: "em1",
    role: "user",
    content:
      "Summarize my top 3 unread emails and draft a reply to the most urgent one",
  },
  {
    id: "em2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "em3",
    role: "tools",
    content: "",
    tools: EMAIL_TOOLS,
    delay: 900,
  },
  {
    id: "em5",
    role: "card",
    content: "",
    cardContent: <EmailSummaryCard />,
    delay: 500,
  },
  {
    id: "em6",
    role: "assistant",
    content:
      "The most urgent is from Sequoia — they want to schedule a Series A call next week. I've drafted a reply for you.",
    delay: 700,
  },
  {
    id: "em7",
    role: "card",
    content: "",
    cardContent: <DraftReplyCard />,
    delay: 400,
  },
];

// ─── Component ───────────────────────────────────────────────────────

export default function EmailDemo() {
  return <ChatDemo messages={EMAIL_MESSAGES} minHeight={280} />;
}
