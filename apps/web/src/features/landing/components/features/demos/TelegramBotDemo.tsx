"use client";

import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";

export default function TelegramBotDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div
      ref={ref}
      className="rounded-2xl overflow-hidden flex flex-col"
      style={{ height: 300, background: "#17212b" }}
    >
      {/* Telegram-style header */}
      <div
        className="flex items-center gap-3 px-4 py-3 shrink-0"
        style={{
          background: "#232e3c",
          borderBottom: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
          style={{ background: "#2196F3" }}
        >
          <span className="text-sm font-bold text-white">G</span>
        </div>
        <div>
          <p className="text-sm font-semibold text-white leading-none">
            GAIA Bot
          </p>
          <p className="text-[11px] mt-0.5" style={{ color: "#64b5f6" }}>
            online
          </p>
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 px-3 py-3 flex flex-col gap-3 overflow-hidden">
        {/* User message */}
        <m.div
          className="flex justify-end"
          initial={{ opacity: 0, y: 8 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1], delay: 0.1 }}
        >
          <div
            className="max-w-[75%] rounded-2xl rounded-br-sm px-3 py-2"
            style={{ background: "#2b5278" }}
          >
            <p className="text-sm text-white">
              /todo Prepare Q2 investor update by Friday p1
            </p>
            <p
              className="text-[10px] mt-1 text-right"
              style={{ color: "#8ba4bf" }}
            >
              9:42 AM ✓✓
            </p>
          </div>
        </m.div>

        {/* Bot response */}
        <m.div
          className="flex gap-2 items-end"
          initial={{ opacity: 0, y: 8 }}
          animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
          transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1], delay: 0.7 }}
        >
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
            style={{ background: "#2196F3" }}
          >
            <span className="text-[10px] font-bold text-white">G</span>
          </div>
          <div
            className="max-w-[75%] rounded-2xl rounded-bl-sm px-3 py-2"
            style={{ background: "#182533" }}
          >
            <p
              className="text-xs font-semibold mb-2"
              style={{ color: "#2196F3" }}
            >
              GAIA
            </p>
            <div className="space-y-1.5">
              {[
                { label: "Title", value: "Q2 investor update" },
                { label: "Due", value: "Friday, Mar 28" },
                { label: "Priority", value: "High" },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-2">
                  <span
                    className="text-[11px] w-12 shrink-0"
                    style={{ color: "#8ba4bf" }}
                  >
                    {item.label}
                  </span>
                  <span className="text-xs text-white">{item.value}</span>
                </div>
              ))}
            </div>
            <p className="text-xs mt-2" style={{ color: "#4caf50" }}>
              ✓ Task created
            </p>
            <p
              className="text-[10px] mt-1.5 text-right"
              style={{ color: "#8ba4bf" }}
            >
              9:42 AM
            </p>
          </div>
        </m.div>
      </div>

      {/* Input bar */}
      <div
        className="flex items-center gap-2 px-3 py-2.5 shrink-0"
        style={{
          background: "#232e3c",
          borderTop: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <div
          className="flex-1 rounded-full px-4 py-2 text-xs"
          style={{ background: "#17212b", color: "#8ba4bf" }}
        >
          Message
        </div>
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center"
          style={{ background: "#2196F3" }}
        >
          <span className="text-white text-xs">→</span>
        </div>
      </div>
    </div>
  );
}
