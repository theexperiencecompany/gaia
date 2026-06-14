"use client";

import ChatDemo from "../founders-demo/ChatDemo";
import type { ChatMessage } from "../founders-demo/types";
import type { ToolStep } from "../types";

const RECALL_TOOLS: ToolStep[] = [
  {
    category: "memory",
    name: "search_memories",
    message: "Recalling what you've told me",
  },
];

const RECALL_MESSAGES: ChatMessage[] = [
  {
    id: "mem-recall-1",
    role: "user",
    content: "Find a dinner spot for Friday with Maya",
  },
  {
    id: "mem-recall-2",
    role: "thinking",
    content: "",
    delay: 500,
  },
  {
    id: "mem-recall-3",
    role: "tools",
    content: "",
    tools: RECALL_TOOLS,
    delay: 700,
  },
  {
    id: "mem-recall-4",
    role: "assistant",
    content:
      "Maya's vegetarian, so I picked three places with serious plant-based menus. Osteria Verde has a table free at 7 — want me to book it?",
    delay: 900,
  },
];

export default function MemoryRecallCard() {
  return (
    <div className="h-full w-full">
      <ChatDemo messages={RECALL_MESSAGES} minHeight={260} compact />
    </div>
  );
}
