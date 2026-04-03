"use client";

import ChatDemo from "@/features/landing/components/demo/founders-demo/ChatDemo";
import type { ChatMessage } from "@/features/landing/components/demo/founders-demo/types";

const MILESTONES = [
  { id: "m1", label: "Week 1-2: 5K baseline run" },
  { id: "m2", label: "Week 3-6: Build to 10K" },
  { id: "m3", label: "Week 7-12: Half marathon training" },
  { id: "m4", label: "Week 13-18: Full marathon prep" },
  { id: "m5", label: "Week 19-20: Taper and race day" },
];

function RoadmapCard() {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-fit min-w-[280px]">
      <p className="text-sm font-semibold text-zinc-100 mb-3">
        Marathon Roadmap — June
      </p>
      <div className="space-y-2">
        {MILESTONES.map((milestone, index) => (
          <div key={milestone.id} className="flex items-start gap-3">
            <div className="flex flex-col items-center">
              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-400/10">
                <span className="text-[10px] font-semibold text-emerald-400">
                  {index + 1}
                </span>
              </div>
              {index < MILESTONES.length - 1 && (
                <div className="mt-1 h-4 w-px bg-zinc-700" />
              )}
            </div>
            <div className="rounded-xl bg-zinc-900 p-3 flex-1">
              <p className="text-xs font-medium text-zinc-200">
                {milestone.label}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const GOALS_MESSAGES: ChatMessage[] = [
  {
    id: "g1",
    role: "user",
    content: "I want to run a marathon by June",
  },
  {
    id: "g2",
    role: "thinking",
    content: "",
    delay: 600,
  },
  {
    id: "g3",
    role: "card",
    content: "",
    cardContent: <RoadmapCard />,
    delay: 900,
  },
  {
    id: "g4",
    role: "assistant",
    content:
      "Here's your 20-week marathon plan. I'll check in each week and adjust your training load based on how you're feeling.",
    delay: 600,
  },
];

export default function GoalsDemo() {
  return <ChatDemo messages={GOALS_MESSAGES} minHeight={320} />;
}
