"use client";

import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";
import { cn } from "@/lib/utils";

const CHANNELS = [
  { name: "general", active: false },
  { name: "engineering", active: true },
  { name: "random", active: false },
];

const PR_FIELDS = [
  { pr: "#47", title: "feat: add voice mode", author: "@sarah_k", open: true },
  {
    pr: "#45",
    title: "fix: token refresh race",
    author: "@dev_mike",
    open: true,
  },
  { pr: "#43", title: "chore: upgrade deps", author: "@alex_t", open: false },
];

export default function DiscordBotDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div
      ref={ref}
      className="rounded-2xl overflow-hidden flex h-[300px] bg-zinc-800"
    >
      {/* Discord Sidebar */}
      <div className="flex shrink-0 bg-zinc-900 w-36">
        {/* Server icon column */}
        <div className="flex flex-col items-center gap-2 py-3 px-2 bg-zinc-950 w-[52px]">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 bg-primary">
            <span className="text-xs font-bold text-white">G</span>
          </div>
          <div className="w-0.5 h-4 rounded-full bg-zinc-600" />
          <div className="w-10 h-10 rounded-full flex items-center justify-center bg-emerald-500">
            <span className="text-xs font-bold text-white">D</span>
          </div>
        </div>

        {/* Channel list */}
        <div className="flex-1 py-3 px-1.5 overflow-hidden">
          <p className="text-xs font-semibold uppercase tracking-wide px-2 mb-1.5 text-zinc-400">
            Text Channels
          </p>
          {CHANNELS.map((channel) => (
            <div
              key={channel.name}
              className={cn(
                "flex items-center gap-1.5 px-2 py-1 rounded-md cursor-default mb-0.5",
                channel.active ? "bg-white/10" : "bg-transparent",
              )}
            >
              <span className="text-sm text-zinc-400">#</span>
              <span
                className={cn(
                  "text-xs truncate",
                  channel.active
                    ? "text-white font-medium"
                    : "text-zinc-400 font-normal",
                )}
              >
                {channel.name}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Channel header */}
        <div className="flex items-center gap-2 px-4 py-2.5 shrink-0 border-b border-white/5">
          <span className="text-base text-zinc-400">#</span>
          <span className="text-sm font-semibold text-white">engineering</span>
        </div>

        {/* Messages */}
        <div className="flex-1 px-4 py-3 flex flex-col gap-4 overflow-hidden">
          {/* User message */}
          <m.div
            className="flex items-start gap-3"
            initial={{ opacity: 0, y: 8 }}
            animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
            transition={{
              duration: 0.3,
              ease: [0.25, 0.1, 0.25, 1],
              delay: 0.1,
            }}
          >
            <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 bg-primary">
              <span className="text-xs font-bold text-white">JS</span>
            </div>
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-semibold text-white">jake_s</span>
                <span className="text-xs text-zinc-400">Today at 9:41 AM</span>
              </div>
              <p className="text-sm text-zinc-200">/gaia summarize open PRs</p>
            </div>
          </m.div>

          {/* GAIA Bot response */}
          <m.div
            className="flex items-start gap-3"
            initial={{ opacity: 0, y: 8 }}
            animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
            transition={{
              duration: 0.3,
              ease: [0.25, 0.1, 0.25, 1],
              delay: 0.7,
            }}
          >
            <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 bg-primary/10 border border-primary/30">
              <span className="text-xs font-bold text-primary">G</span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2 mb-1">
                <span className="text-sm font-semibold text-primary">GAIA</span>
                <span className="text-xs rounded-sm px-1 bg-primary text-white">
                  BOT
                </span>
                <span className="text-xs text-zinc-400">Today at 9:41 AM</span>
              </div>
              {/* Discord embed */}
              <div className="rounded-sm pl-3 pr-3 py-3 bg-zinc-900 border-l-4 border-primary">
                <p className="text-sm font-semibold text-white mb-2">
                  Open Pull Requests · 3
                </p>
                <div className="space-y-2">
                  {PR_FIELDS.map((field) => (
                    <div key={field.pr} className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-xs rounded px-1.5 py-0.5 font-medium shrink-0",
                          field.open
                            ? "bg-emerald-400/10 text-emerald-400"
                            : "bg-zinc-500/10 text-zinc-400",
                        )}
                      >
                        {field.open ? "Open" : "Closed"}
                      </span>
                      <span className="text-xs font-medium text-primary">
                        {field.pr}
                      </span>
                      <span className="text-xs truncate text-zinc-200">
                        {field.title}
                      </span>
                      <span className="text-xs shrink-0 text-zinc-400">
                        {field.author}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </m.div>
        </div>

        {/* Message input */}
        <div className="px-4 py-3 shrink-0">
          <div className="rounded-xl px-4 py-2.5 text-xs bg-zinc-700 text-zinc-400">
            Message #engineering
          </div>
        </div>
      </div>
    </div>
  );
}
