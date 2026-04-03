"use client";

import { DocumentAttachmentIcon, Download02Icon } from "@icons";
import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";
import type { ToolStep } from "../../demo/types";

// ─── Tool Steps ────────────────────────────────────────────────────────────────

const DOCUMENT_TOOLS: ToolStep[] = [
  {
    category: "notion",
    name: "notion_read_page",
    message: "Reading Q1 roadmap page",
  },
  {
    category: "googlesheets",
    name: "sheets_read",
    message: "Pulling milestone data",
  },
];

// ─── Document Card ─────────────────────────────────────────────────────────────

function DocumentCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="rounded-2xl bg-zinc-900 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-zinc-800">
              <DocumentAttachmentIcon className="h-5 w-5 text-zinc-300" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-zinc-200">
                Q1 Product Roadmap Summary
              </p>
              <div className="mt-1 flex items-center gap-2">
                <span className="rounded-full bg-cyan-400/10 px-2 py-0.5 text-[10px] font-medium text-cyan-400">
                  PDF
                </span>
                <span className="text-xs text-zinc-500">142 KB</span>
                <span className="text-xs text-zinc-500">·</span>
                <span className="text-xs text-zinc-500">4 pages</span>
              </div>
            </div>
          </div>
          <button
            type="button"
            className="flex shrink-0 items-center gap-1.5 rounded-xl bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-all duration-200 hover:bg-zinc-700 active:scale-95"
          >
            <Download02Icon className="h-3.5 w-3.5" />
            Download
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Messages ──────────────────────────────────────────────────────────────────

const DOCUMENT_MESSAGES: ChatMessage[] = [
  {
    id: "dg1",
    role: "user",
    content: "Generate a PDF summary of our Q1 product roadmap",
  },
  {
    id: "dg2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "dg3",
    role: "tools",
    content: "",
    tools: DOCUMENT_TOOLS,
    delay: 1000,
  },
  {
    id: "dg4",
    role: "card",
    content: "",
    cardContent: <DocumentCard />,
    delay: 500,
  },
  {
    id: "dg5",
    role: "assistant",
    content:
      "Done. I compiled the Q1 roadmap into a 4-page PDF covering all milestones, priorities, and owners. Ready to download or share.",
    delay: 700,
  },
];

// ─── Component ─────────────────────────────────────────────────────────────────

export default function DocumentGenerationDemo() {
  return (
    <div className="w-full">
      <ChatDemo messages={DOCUMENT_MESSAGES} minHeight={260} />
    </div>
  );
}
