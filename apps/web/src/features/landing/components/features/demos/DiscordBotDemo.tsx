"use client";

import { m, useInView } from "motion/react";
import { useRef } from "react";

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
      className="rounded-2xl overflow-hidden flex"
      style={{ height: 300, background: "#313338" }}
    >
      {/* Discord Sidebar */}
      <div
        className="flex shrink-0"
        style={{ background: "#2b2d31", width: 144 }}
      >
        {/* Server icon column */}
        <div
          className="flex flex-col items-center gap-2 py-3 px-2"
          style={{ background: "#1e1f22", width: 52 }}
        >
          <div
            className="w-10 h-10 rounded-[12px] flex items-center justify-center shrink-0"
            style={{ background: "#5865F2" }}
          >
            <span className="text-xs font-bold text-white">G</span>
          </div>
          <div
            className="w-0.5 h-4 rounded-full"
            style={{ background: "#4e5058" }}
          />
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center"
            style={{ background: "#3ba55c" }}
          >
            <span className="text-xs font-bold text-white">D</span>
          </div>
        </div>

        {/* Channel list */}
        <div className="flex-1 py-3 px-1.5 overflow-hidden">
          <p
            className="text-[10px] font-semibold uppercase tracking-wide px-2 mb-1.5"
            style={{ color: "#949ba4" }}
          >
            Text Channels
          </p>
          {CHANNELS.map((channel) => (
            <div
              key={channel.name}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md cursor-default mb-0.5"
              style={{
                background: channel.active
                  ? "rgba(255,255,255,0.1)"
                  : "transparent",
              }}
            >
              <span style={{ color: "#949ba4" }} className="text-sm">
                #
              </span>
              <span
                className="text-xs truncate"
                style={{
                  color: channel.active ? "#ffffff" : "#949ba4",
                  fontWeight: channel.active ? 500 : 400,
                }}
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
        <div
          className="flex items-center gap-2 px-4 py-2.5 shrink-0"
          style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
        >
          <span style={{ color: "#949ba4" }} className="text-base">
            #
          </span>
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
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
              style={{ background: "#5865F2" }}
            >
              <span className="text-[11px] font-bold text-white">JS</span>
            </div>
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-semibold text-white">jake_s</span>
                <span className="text-[10px]" style={{ color: "#949ba4" }}>
                  Today at 9:41 AM
                </span>
              </div>
              <p className="text-sm" style={{ color: "#dbdee1" }}>
                /gaia summarize open PRs
              </p>
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
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
              style={{ background: "#00bbff33", border: "1px solid #00bbff55" }}
            >
              <span
                className="text-[11px] font-bold"
                style={{ color: "#00bbff" }}
              >
                G
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2 mb-1">
                <span
                  className="text-sm font-semibold"
                  style={{ color: "#00bbff" }}
                >
                  GAIA
                </span>
                <span
                  className="text-[10px] rounded px-1"
                  style={{ background: "#5865F2", color: "white", fontSize: 9 }}
                >
                  BOT
                </span>
                <span className="text-[10px]" style={{ color: "#949ba4" }}>
                  Today at 9:41 AM
                </span>
              </div>
              {/* Discord embed */}
              <div
                className="rounded-sm pl-3 pr-3 py-3"
                style={{
                  background: "#2b2d31",
                  borderLeft: "4px solid #00bbff",
                }}
              >
                <p className="text-sm font-semibold text-white mb-2">
                  Open Pull Requests · 3
                </p>
                <div className="space-y-2">
                  {PR_FIELDS.map((field) => (
                    <div key={field.pr} className="flex items-center gap-2">
                      <span
                        className="text-[10px] rounded px-1.5 py-0.5 font-medium shrink-0"
                        style={{
                          background: field.open ? "#3ba55c22" : "#72767d22",
                          color: field.open ? "#3ba55c" : "#72767d",
                          border: `1px solid ${field.open ? "#3ba55c44" : "#72767d44"}`,
                        }}
                      >
                        {field.open ? "Open" : "Closed"}
                      </span>
                      <span
                        className="text-xs font-medium"
                        style={{ color: "#00bbff" }}
                      >
                        {field.pr}
                      </span>
                      <span
                        className="text-xs truncate"
                        style={{ color: "#dbdee1" }}
                      >
                        {field.title}
                      </span>
                      <span
                        className="text-xs shrink-0"
                        style={{ color: "#949ba4" }}
                      >
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
          <div
            className="rounded-lg px-4 py-2.5 text-xs"
            style={{ background: "#383a40", color: "#949ba4" }}
          >
            Message #engineering
          </div>
        </div>
      </div>
    </div>
  );
}
