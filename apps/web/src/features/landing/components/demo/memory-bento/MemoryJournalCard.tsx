"use client";

import { Calendar01Icon, NotificationIcon } from "@icons";
import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";

const ease = [0.25, 0.1, 0.25, 1] as const;

const JOURNAL_ENTRIES = [
  { time: "10:14", text: "Shipped the onboarding redesign with Sam" },
  { time: "1:30", text: "Booked flights for the Lisbon offsite" },
  { time: "4:45", text: "Told Priya the proposal would go out Friday" },
];

export default function MemoryJournalCard() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div ref={ref} className="flex h-full flex-col gap-2">
      <div className="flex flex-1 flex-col rounded-2xl bg-zinc-900 p-3 sm:p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar01Icon className="size-4 text-zinc-400" />
            <span className="text-sm font-medium text-zinc-200">
              Thursday, June 11
            </span>
          </div>
          <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-400">
            Today
          </span>
        </div>

        <div className="relative flex flex-col gap-3 pl-4">
          <div className="absolute top-1.5 bottom-1.5 left-[3px] w-px bg-zinc-800" />
          {JOURNAL_ENTRIES.map((entry, index) => (
            <m.div
              key={entry.text}
              className="relative"
              initial={{ opacity: 0, x: -12 }}
              animate={isInView ? { opacity: 1, x: 0 } : { opacity: 0, x: -12 }}
              transition={{ duration: 0.3, ease, delay: 0.2 + index * 0.15 }}
            >
              <div className="absolute top-1.5 -left-4 size-[7px] rounded-full bg-zinc-600" />
              <p className="text-xs leading-relaxed text-zinc-300">
                {entry.text}
              </p>
              <span className="text-[10px] tabular-nums text-zinc-600">
                {entry.time}
              </span>
            </m.div>
          ))}
        </div>
      </div>

      <m.div
        className="rounded-2xl bg-zinc-900 p-2 sm:p-3"
        initial={{ opacity: 0, y: 12 }}
        animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
        transition={{ duration: 0.35, ease, delay: 0.8 }}
      >
        <div className="mb-1.5 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <NotificationIcon className="size-3.5 text-blue-400" />
            <span className="text-[11px] font-medium text-blue-400">
              Follow-up
            </span>
          </div>
          <span className="text-[11px] text-zinc-500">Friday, 9:02 AM</span>
        </div>
        <p className="text-xs leading-relaxed text-zinc-300">
          The proposal for Priya is due today. Want me to draft it from
          Tuesday's notes?
        </p>
      </m.div>
    </div>
  );
}
