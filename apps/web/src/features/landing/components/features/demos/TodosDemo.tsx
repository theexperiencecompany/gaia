"use client";

import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";

// ─── Task Confirmation Card ─────────────────────────────────────────────────

function TaskCreatedCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="rounded-2xl bg-zinc-900 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-zinc-200">
              Call Alex about Q4 budget review
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="rounded-full bg-cyan-400/10 px-2 py-0.5 text-[10px] font-medium text-cyan-400">
                Tomorrow
              </span>
              <span className="rounded-full bg-red-400/10 px-2 py-0.5 text-[10px] font-medium text-red-400">
                P1
              </span>
              <span className="rounded-full bg-purple-400/10 px-2 py-0.5 text-[10px] font-medium text-purple-400">
                @finance
              </span>
            </div>
          </div>
          <span className="shrink-0 rounded-full bg-emerald-400/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
            Task created ✓
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── Messages ──────────────────────────────────────────────────────────────

const TODOS_MESSAGES: ChatMessage[] = [
  {
    id: "td1",
    role: "user",
    content: "call Alex tomorrow @finance p1 about Q4 budget review",
  },
  {
    id: "td2",
    role: "thinking",
    content: "",
    delay: 500,
  },
  {
    id: "td3",
    role: "card",
    content: "",
    cardContent: <TaskCreatedCard />,
    delay: 700,
  },
  {
    id: "td4",
    role: "assistant",
    content:
      "Done. I've created a P1 task under @finance to call Alex tomorrow about the Q4 budget review.",
    delay: 600,
  },
];

// ─── Component ─────────────────────────────────────────────────────────────

export default function TodosDemo() {
  return (
    <div className="w-full">
      <ChatDemo messages={TODOS_MESSAGES} minHeight={220} />
    </div>
  );
}
