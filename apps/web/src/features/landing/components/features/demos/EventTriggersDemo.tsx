"use client";

import { ArrowRight02Icon } from "@icons";
import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

const TRIGGERS = [
  {
    id: "t1",
    event: "New email received",
    source: "gmail",
    action: "Create task + summarize",
    status: "active",
  },
  {
    id: "t2",
    event: "PR opened or updated",
    source: "github",
    action: "Post summary to Slack",
    status: "active",
  },
  {
    id: "t3",
    event: "Payment succeeded",
    source: "stripe",
    action: "Update CRM contact",
    status: "active",
  },
  {
    id: "t4",
    event: "Linear issue created",
    source: "linear",
    action: "Notify team channel",
    status: "paused",
  },
];

export default function EventTriggersDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });

  return (
    <div ref={ref} className="space-y-2">
      {TRIGGERS.map((trigger, index) => (
        <m.div
          key={trigger.id}
          initial={{ opacity: 0, y: 12 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
          transition={{
            duration: 0.35,
            delay: index * 0.1,
            ease: [0.22, 1, 0.36, 1],
          }}
          className="rounded-2xl bg-zinc-800 p-3 flex items-center gap-3"
        >
          {/* Source icon */}
          <div className="shrink-0">
            {getToolCategoryIcon(trigger.source, { width: 20, height: 20 })}
          </div>

          {/* Event + action */}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-zinc-200 truncate">
              {trigger.event}
            </p>
            <p className="text-xs text-zinc-500 truncate flex items-center gap-1">
              <ArrowRight02Icon className="size-3 shrink-0" />
              {trigger.action}
            </p>
          </div>

          {/* Status badge */}
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
              trigger.status === "active"
                ? "bg-emerald-400/10 text-emerald-400"
                : "bg-zinc-700/50 text-zinc-400"
            }`}
          >
            {trigger.status === "active" ? "Active" : "Paused"}
          </span>
        </m.div>
      ))}
    </div>
  );
}
