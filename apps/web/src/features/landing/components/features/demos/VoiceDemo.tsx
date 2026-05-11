"use client";

import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";

// ─── Constants ─────────────────────────────────────────────────────────────────

const BAR_HEIGHTS = [
  { id: "w1", h: 16 },
  { id: "w2", h: 24 },
  { id: "w3", h: 32 },
  { id: "w4", h: 40 },
  { id: "w5", h: 48 },
  { id: "w6", h: 40 },
  { id: "w7", h: 32 },
  { id: "w8", h: 24 },
  { id: "w9", h: 16 },
];

const TRANSCRIPT_LINES = [
  { id: "t1", role: "user", text: "What's on my calendar today?" },
  {
    id: "t2",
    role: "gaia",
    text: "You have standup at 10am and a product demo at 3pm. Want me to prep notes?",
  },
  { id: "t3", role: "user", text: "Yes, prep notes for the demo." },
  {
    id: "t4",
    role: "gaia",
    text: "Notes ready. Pulling attendees, agenda, and related emails now.",
  },
];

const BAR_KEYFRAMES = [
  [0.3, 1, 0.4, 0.8, 0.3],
  [0.5, 0.3, 1, 0.5, 0.4],
  [0.4, 0.8, 0.3, 1, 0.5],
  [1, 0.4, 0.7, 0.3, 0.9],
  [0.6, 1, 0.3, 0.8, 0.5],
  [0.3, 0.7, 1, 0.4, 0.6],
  [0.8, 0.3, 0.5, 1, 0.4],
  [0.4, 0.6, 0.8, 0.3, 1],
  [0.7, 1, 0.4, 0.6, 0.3],
];

const BAR_DURATIONS = [0.9, 0.75, 1.1, 0.85, 0.7, 0.95, 0.8, 1.05, 0.75];

// ─── Component ─────────────────────────────────────────────────────────────────

export default function VoiceDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-50px" });

  return (
    <div ref={ref} className="w-full select-none">
      {/* Waveform */}
      <m.div
        className="rounded-2xl bg-zinc-800/50 py-4 px-6 flex items-center justify-center gap-1 mb-4"
        initial={{ opacity: 0, y: 12 }}
        animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
      >
        {BAR_HEIGHTS.map(({ id, h }, i) => (
          <m.div
            key={id}
            className="rounded-full bg-[#00bbff] w-1"
            style={{ height: h }}
            animate={
              isInView
                ? {
                    scaleY: BAR_KEYFRAMES[i],
                  }
                : { scaleY: 0.3 }
            }
            transition={
              isInView
                ? {
                    duration: BAR_DURATIONS[i],
                    repeat: Number.POSITIVE_INFINITY,
                    repeatType: "mirror",
                    ease: "easeInOut",
                    delay: i * 0.06,
                  }
                : {}
            }
          />
        ))}
      </m.div>

      {/* Transcript */}
      <div className="flex flex-col gap-2">
        {TRANSCRIPT_LINES.map((line, i) => (
          <m.div
            key={line.id}
            className={`flex ${line.role === "user" ? "justify-end" : "justify-start"}`}
            initial={{ opacity: 0, y: 8 }}
            animate={isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
            transition={{
              duration: 0.3,
              ease: "easeOut",
              delay: 0.4 + i * 0.3,
            }}
          >
            <span
              className={
                line.role === "user"
                  ? "text-[#00bbff] bg-[#00bbff]/10 rounded-xl px-3 py-2 text-xs max-w-[80%]"
                  : "text-zinc-300 bg-zinc-800 rounded-xl px-3 py-2 text-xs max-w-[80%]"
              }
            >
              {line.text}
            </span>
          </m.div>
        ))}
      </div>
    </div>
  );
}
