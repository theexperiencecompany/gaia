"use client";

import { Clock01Icon, QuillWriteIcon } from "@icons";
import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";

const ease = [0.25, 0.1, 0.25, 1] as const;

const JOURNAL_ENTRIES = [
  "Shipped the onboarding redesign with Sam",
  "Booked flights for the Lisbon offsite",
  "Told Priya the proposal would go out Friday",
];

export default function MemoryJournalCard() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div ref={ref} className="flex h-full flex-col gap-2">
      <div className="flex flex-1 flex-col rounded-2xl bg-zinc-900 p-4">
        <div className="mb-1 flex items-center gap-1.5">
          <QuillWriteIcon className="size-3.5 text-zinc-400" />
          <span className="text-xs text-zinc-400">Journal</span>
        </div>
        <p className="mb-3 text-sm font-medium text-zinc-200">
          Thursday, June 11
        </p>
        <div className="space-y-2">
          {JOURNAL_ENTRIES.map((entry, index) => (
            <m.p
              key={entry}
              className="text-xs leading-relaxed text-zinc-300"
              initial={{ opacity: 0, x: -12 }}
              animate={isInView ? { opacity: 1, x: 0 } : { opacity: 0, x: -12 }}
              transition={{ duration: 0.3, ease, delay: 0.2 + index * 0.15 }}
            >
              {entry}
            </m.p>
          ))}
        </div>
      </div>

      <m.div
        className="rounded-2xl bg-zinc-900 p-3"
        initial={{ opacity: 0, y: 12 }}
        animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
        transition={{ duration: 0.35, ease, delay: 0.8 }}
      >
        <div className="mb-1.5 flex items-center gap-1.5">
          <Clock01Icon className="size-3.5 text-indigo-400" />
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
