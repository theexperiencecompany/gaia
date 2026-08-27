"use client";

import {
  AlarmClockIcon,
  CheckmarkCircle02Icon,
  WorkflowCircle06Icon,
} from "@icons";
import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { ChatDemo, type ChatMessageItem } from "../iphone/ChatDemo";
import { SplitShowcase } from "./SplitShowcase";

/**
 * Workflows & Automations section: mirrors RunsYourDaySection via
 * SplitShowcase `reverse` (copy right, square demo tile left — same tile
 * sizing). Two slides, each a two-act story: the user sets up a real
 * workflow (SCHEDULED: "Study Plan Builder — weekly on Sunday"; TRIGGERED:
 * emails after 7pm get replies drafted), then a time-jump divider and GAIA
 * texting the RESULT when the workflow actually runs. The segmented pill
 * swaps slides; ChatDemo's native `play` reveal replays per slide (typing
 * dots, divider beat, payoff pause on the final message).
 */

const SCHEDULED_SCRIPT: ChatMessageItem[] = [
  {
    from: "me",
    text: "Every Sunday, plan my study week around my calendar and add the tasks to Todoist.",
    time: "9:47 PM",
  },
  {
    from: "them",
    text: "Set up. Runs every Sunday at 6pm: check calendar, build the plan, add tasks.",
  },
  { from: "them", text: "Activated ✅" },
  { divider: "Sunday · 6:00 PM" },
  {
    from: "them",
    text: "☀️ Study plan ready. 4 sessions fit around your classes, tasks are in Todoist.",
  },
  {
    from: "them",
    text: "First up: stats review, tomorrow 9am.",
  },
];

const TRIGGERED_SCRIPT: ChatMessageItem[] = [
  {
    from: "me",
    text: "When an email lands after 7pm, draft a reply and leave it in my drafts for the morning.",
    time: "8:12 PM",
  },
  {
    from: "them",
    text: "Set up. Emails after 7pm get a draft reply, filed in your drafts.",
  },
  {
    from: "them",
    text: "Running. I'll ping you when something lands.",
  },
  { divider: "Today · 10:05 PM" },
  {
    from: "them",
    text: "📧 2 replies drafted tonight. A client follow-up and an invoice question, both in your drafts.",
  },
  {
    from: "them",
    text: "Want me to send the invoice one? Just say yes.",
  },
];

const ROWS = [
  {
    icon: <AlarmClockIcon width={18} height={18} />,
    label: "Set a schedule or a trigger",
  },
  {
    icon: <WorkflowCircle06Icon width={18} height={18} />,
    label: "Runs the chain across your tools",
  },
  {
    icon: <CheckmarkCircle02Icon width={18} height={18} />,
    label: "Pings you when it's done, so you never chase it",
  },
];

type Slide = "scheduled" | "triggered";

export default function WorkflowsSection() {
  const [slide, setSlide] = useState<Slide>("scheduled");
  const tileRef = useRef<HTMLDivElement>(null);
  const inView = useInView(tileRef, { once: true, amount: 0.45 });

  return (
    <SplitShowcase
      reverse
      title="Put your life on autopilot."
      subtitle="Tell GAIA what to automate in plain language. Set a schedule or a trigger and it runs the steps across your tools. No code."
      rows={ROWS}
    >
      <div ref={tileRef} className="absolute inset-0 flex flex-col bg-white">
        {/* Segmented slide control — native-looking pill on the white screen */}
        <div className="flex h-10 shrink-0 items-center justify-center">
          <div className="flex items-center gap-0.5 rounded-full bg-black/5 p-0.5">
            {(
              [
                { id: "scheduled", label: "Scheduled" },
                { id: "triggered", label: "Triggered" },
              ] as const
            ).map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSlide(s.id)}
                aria-pressed={slide === s.id}
                className={cn(
                  "cursor-pointer rounded-full px-3 py-1 text-xs font-medium transition-colors",
                  slide === s.id
                    ? "bg-white text-zinc-900 shadow-sm"
                    : "text-zinc-500 hover:text-zinc-700",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* key={slide} remounts ChatDemo so its `play` reveal replays */}
        <AnimatePresence mode="wait" initial={false}>
          <m.div
            key={slide}
            className="flex min-h-0 flex-1 flex-col"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
          >
            <ChatDemo
              platform="imessage"
              title="GAIA"
              messages={
                slide === "scheduled" ? SCHEDULED_SCRIPT : TRIGGERED_SCRIPT
              }
              showHeader={false}
              play={inView}
              className="min-h-0 flex-1"
            />
          </m.div>
        </AnimatePresence>
      </div>
    </SplitShowcase>
  );
}
