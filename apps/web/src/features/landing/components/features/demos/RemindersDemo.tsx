"use client";

import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import type { ChatMessage } from "@/features/landing/components/demo/founders-demo/types";

function ReminderConfirmationCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-fit min-w-[300px]">
      <p className="text-sm font-semibold text-zinc-100 mb-3">
        Review sales pipeline
      </p>
      <div className="space-y-2">
        <div className="rounded-2xl bg-zinc-900 p-3">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">Schedule</span>
              <span className="text-xs font-medium text-zinc-200">
                Every Monday at 9:00 AM
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">Timezone</span>
              <span className="text-xs font-medium text-zinc-200">
                America/New_York
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">Next</span>
              <span className="text-xs font-medium text-zinc-200">
                Monday, March 30 at 9:00 AM
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 px-1 pt-1">
          <span className="text-xs font-medium text-emerald-400">
            Reminder set ✓
          </span>
        </div>
      </div>
    </div>
  );
}

const REMINDERS_MESSAGES: ChatMessage[] = [
  {
    id: "rem1",
    role: "user",
    content: "Remind me every Monday at 9am to review my sales pipeline",
  },
  {
    id: "rem2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "rem3",
    role: "card",
    content: "",
    cardContent: <ReminderConfirmationCard />,
    delay: 800,
  },
  {
    id: "rem4",
    role: "assistant",
    content:
      "Done. I'll remind you every Monday at 9:00 AM Eastern to review your sales pipeline.",
    delay: 600,
  },
];

export default function RemindersDemo() {
  return <ChatDemo messages={REMINDERS_MESSAGES} minHeight={220} />;
}
