"use client";

import { m, useInView } from "motion/react";
import { useRef } from "react";

const COMMANDS = [
  { cmd: "/gaia", desc: "Ask anything" },
  { cmd: "/todo", desc: "Create a task" },
  { cmd: "/workflow", desc: "Run a workflow" },
];

const TASK_ITEMS = [
  { label: "Title", value: "Prepare Q2 investor update" },
  { label: "Due", value: "Friday, Mar 28" },
  { label: "Priority", value: "High" },
];

export default function TelegramBotDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div ref={ref} className="rounded-2xl overflow-hidden flex h-64">
      {/* Sidebar */}
      <div className="bg-zinc-900 rounded-l-2xl w-32 flex flex-col py-3 px-2 shrink-0">
        <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wide px-1 mb-2">
          Commands
        </p>
        <div className="space-y-0.5">
          {COMMANDS.map((item) => (
            <div
              key={item.cmd}
              className="px-2 py-1.5 rounded-md cursor-default"
            >
              <p className="text-xs font-medium text-cyan-400 truncate">
                {item.cmd}
              </p>
              <p className="text-[10px] text-zinc-500 truncate">{item.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Message area */}
      <div className="bg-zinc-800 rounded-r-2xl flex-1 p-4 overflow-hidden flex flex-col gap-4">
        {/* User message */}
        <m.div
          className="flex justify-end"
          initial={{ opacity: 0, y: 8 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1], delay: 0.1 }}
        >
          <div className="max-w-[70%] rounded-2xl rounded-br-sm bg-cyan-500/20 px-3 py-2">
            <p className="text-sm text-zinc-200">
              /todo Prepare Q2 investor update by Friday p1
            </p>
          </div>
        </m.div>

        {/* GAIA response */}
        <m.div
          className="flex gap-2.5 items-start"
          initial={{ opacity: 0, y: 8 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1], delay: 0.6 }}
        >
          <div className="w-7 h-7 rounded-full bg-cyan-400/20 border border-cyan-400/30 flex items-center justify-center shrink-0">
            <span className="text-[10px] font-bold text-cyan-400">G</span>
          </div>
          <div className="rounded-2xl rounded-bl-sm bg-zinc-900 px-3 py-2 flex-1 min-w-0">
            <p className="text-xs font-semibold text-cyan-400 mb-1.5">GAIA</p>
            <div className="space-y-1">
              {TASK_ITEMS.map((item) => (
                <div key={item.label} className="flex items-center gap-2">
                  <span className="text-[11px] text-zinc-500 w-10 shrink-0">
                    {item.label}
                  </span>
                  <span className="text-xs text-zinc-300 truncate">
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-xs text-emerald-400 mt-2">Task created ✓</p>
          </div>
        </m.div>
      </div>
    </div>
  );
}
