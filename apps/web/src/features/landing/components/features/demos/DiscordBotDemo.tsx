"use client";

import { m, useInView } from "motion/react";
import { useRef } from "react";

const CHANNELS = [
  { name: "general", active: false },
  { name: "engineering", active: true },
  { name: "random", active: false },
];

const SERVER_COLORS = ["bg-indigo-500", "bg-emerald-500", "bg-rose-500"];

const PR_FIELDS = [
  { pr: "#47", title: "feat: add voice mode", author: "@sarah_k" },
  { pr: "#45", title: "fix: token refresh race", author: "@dev_mike" },
  { pr: "#43", title: "chore: upgrade deps", author: "@alex_t" },
];

export default function DiscordBotDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div ref={ref} className="rounded-2xl overflow-hidden flex h-64">
      {/* Sidebar */}
      <div className="bg-zinc-900 rounded-l-2xl w-36 flex flex-col py-3 px-2 shrink-0">
        {/* Server icons */}
        <div className="flex gap-1.5 mb-4 px-1">
          {SERVER_COLORS.map((color) => (
            <div
              key={color}
              className={`w-5 h-5 rounded-md ${color} shrink-0`}
              aria-hidden="true"
            />
          ))}
        </div>

        {/* Channel list */}
        <div className="space-y-0.5">
          {CHANNELS.map((channel) => (
            <div
              key={channel.name}
              className={`flex items-center gap-1.5 px-2 py-1 rounded-md cursor-default ${
                channel.active ? "bg-zinc-700/50" : ""
              }`}
            >
              <span className="text-zinc-500 text-xs">#</span>
              <span
                className={`text-xs truncate ${
                  channel.active ? "text-zinc-100 font-medium" : "text-zinc-400"
                }`}
              >
                {channel.name}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Message area */}
      <div className="bg-zinc-800 rounded-r-2xl flex-1 p-4 overflow-hidden flex flex-col gap-4">
        {/* User message */}
        <m.div
          className="flex items-start gap-2.5"
          initial={{ opacity: 0, y: 8 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1], delay: 0.1 }}
        >
          <div className="w-7 h-7 rounded-full bg-indigo-500 flex items-center justify-center shrink-0">
            <span className="text-[10px] font-bold text-white">JS</span>
          </div>
          <div>
            <p className="text-sm font-medium text-zinc-200 leading-none mb-1">
              jake_s
            </p>
            <p className="text-sm text-zinc-300">/gaia summarize open PRs</p>
          </div>
        </m.div>

        {/* GAIA response */}
        <m.div
          className="flex items-start gap-2.5"
          initial={{ opacity: 0, y: 8 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1], delay: 0.6 }}
        >
          <div className="w-7 h-7 rounded-full bg-[#00bbff]/20 border border-[#00bbff]/30 flex items-center justify-center shrink-0">
            <span className="text-[10px] font-bold text-[#00bbff]">G</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-[#00bbff] leading-none mb-1.5">
              GAIA
            </p>
            {/* Discord embed */}
            <div className="rounded-lg border-l-4 border-[#00bbff] bg-zinc-900 p-3 mt-1">
              <p className="text-sm font-semibold text-zinc-100 mb-2">
                Open Pull Requests (3)
              </p>
              <div className="space-y-1.5">
                {PR_FIELDS.map((field) => (
                  <div key={field.pr} className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-zinc-400 shrink-0">
                      {field.pr}
                    </span>
                    <span className="text-xs text-zinc-300 truncate">
                      {field.title}
                    </span>
                    <span className="text-xs text-zinc-500 shrink-0">
                      {field.author}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </m.div>
      </div>
    </div>
  );
}
