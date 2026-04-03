"use client";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import ChatDemo from "../../demo/founders-demo/ChatDemo";
import type { ChatMessage } from "../../demo/founders-demo/types";
import type { ToolStep } from "../../demo/types";

// ─── Tool Steps ────────────────────────────────────────────────────────────────

const CONTACTS_TOOLS: ToolStep[] = [
  {
    category: "gmail",
    name: "search_contacts",
    message: "Searching Gmail contacts",
  },
  {
    category: "hubspot",
    name: "search_contacts",
    message: "Searching HubSpot CRM",
  },
];

// ─── Contact Card ──────────────────────────────────────────────────────────────

function ContactCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="rounded-2xl bg-zinc-900 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-zinc-700 text-sm font-semibold text-zinc-100">
              AC
            </div>
            <div>
              <p className="text-sm font-semibold text-zinc-100">Alex Chen</p>
              <p className="text-xs text-zinc-400">
                VP of Engineering at Acme Corp
              </p>
            </div>
          </div>
          <div className="flex shrink-0 gap-1.5">
            <span className="flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-medium text-red-400">
              {getToolCategoryIcon("gmail", {
                width: 10,
                height: 10,
                showBackground: false,
              })}
              Gmail
            </span>
            <span className="flex items-center gap-1 rounded-full bg-orange-500/15 px-2 py-0.5 text-[10px] font-medium text-orange-400">
              {getToolCategoryIcon("hubspot", {
                width: 10,
                height: 10,
                showBackground: false,
              })}
              HubSpot
            </span>
          </div>
        </div>
        <div className="mt-3 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="w-12 text-[11px] text-zinc-500">Email</span>
            <span className="text-xs text-zinc-300">
              alex.chen@acmecorp.com
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-12 text-[11px] text-zinc-500">Phone</span>
            <span className="text-xs text-zinc-300">+1 (415) 555-0142</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Messages ──────────────────────────────────────────────────────────────────

const CONTACTS_MESSAGES: ChatMessage[] = [
  {
    id: "ct1",
    role: "user",
    content: "Find Alex Chen's contact info",
  },
  {
    id: "ct2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "ct3",
    role: "tools",
    content: "",
    tools: CONTACTS_TOOLS,
    delay: 900,
  },
  {
    id: "ct4",
    role: "card",
    content: "",
    cardContent: <ContactCard />,
    delay: 500,
  },
  {
    id: "ct5",
    role: "assistant",
    content:
      "Found Alex Chen across Gmail and HubSpot. He's VP of Engineering at Acme Corp — want me to draft an email or log a note in HubSpot?",
    delay: 700,
  },
];

// ─── Component ─────────────────────────────────────────────────────────────────

export default function ContactsDemo() {
  return (
    <div className="w-full">
      <ChatDemo messages={CONTACTS_MESSAGES} minHeight={260} />
    </div>
  );
}
