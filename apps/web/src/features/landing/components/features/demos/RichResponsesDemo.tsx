"use client";

import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useRef } from "react";

// ─── Bar Chart Card ───────────────────────────────────────────────────────────

const BAR_HEIGHTS = [
  { id: "b1", h: 45 },
  { id: "b2", h: 70 },
  { id: "b3", h: 55 },
  { id: "b4", h: 90 },
  { id: "b5", h: 65 },
];

function BarChartPreview() {
  return (
    <div className="flex h-12 items-end gap-1">
      {BAR_HEIGHTS.map(({ id, h }) => (
        <div
          key={id}
          className="flex-1 rounded-t-sm"
          style={{ height: `${h}%`, backgroundColor: "#00bbff", opacity: 0.85 }}
        />
      ))}
    </div>
  );
}

// ─── Timeline Card ────────────────────────────────────────────────────────────

const TIMELINE_ITEMS = ["Kickoff", "Review", "Ship"];

function TimelinePreview() {
  return (
    <div className="flex flex-col gap-1 w-full">
      {TIMELINE_ITEMS.map((label, i) => (
        <div key={label} className="flex items-center gap-2">
          <div className="flex flex-col items-center">
            <div className="h-2 w-2 rounded-full bg-violet-400 shrink-0" />
            {i < TIMELINE_ITEMS.length - 1 && (
              <div className="h-3 w-px bg-zinc-700" />
            )}
          </div>
          <span className="text-[10px] text-zinc-400">{label}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Status Card Preview ──────────────────────────────────────────────────────

function StatusCardPreview() {
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="h-2 w-2 rounded-full bg-emerald-400 shrink-0" />
      <span className="text-[10px] font-medium text-emerald-400">
        Deployed ✓
      </span>
    </div>
  );
}

// ─── Comparison Table Preview ─────────────────────────────────────────────────

const TABLE_ROWS = [
  { id: "r1", cells: ["A", "12", "↑"] },
  { id: "r2", cells: ["B", "9", "↓"] },
];

function ComparisonTablePreview() {
  return (
    <div className="flex flex-col gap-1 w-full">
      {TABLE_ROWS.map(({ id, cells }) => (
        <div key={id} className="flex gap-1">
          {cells.map((cell) => (
            <div
              key={cell}
              className="flex-1 rounded bg-zinc-800 px-1 py-0.5 text-center text-[10px] text-zinc-400"
            >
              {cell}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ─── Avatar List Preview ──────────────────────────────────────────────────────

const AVATAR_COLORS = [
  { id: "av1", color: "bg-violet-400" },
  { id: "av2", color: "bg-cyan-400" },
  { id: "av3", color: "bg-emerald-400" },
  { id: "av4", color: "bg-amber-400" },
];

function AvatarListPreview() {
  return (
    <div className="flex">
      {AVATAR_COLORS.map(({ id, color }, i) => (
        <div
          key={id}
          className={`h-6 w-6 rounded-full border-2 border-zinc-900 ${color}`}
          style={{ marginLeft: i === 0 ? 0 : -8 }}
        />
      ))}
    </div>
  );
}

// ─── Step List Preview ────────────────────────────────────────────────────────

const STEPS = ["Install", "Configure", "Deploy"];

function StepListPreview() {
  return (
    <div className="flex flex-col gap-1 w-full">
      {STEPS.map((step, i) => (
        <div key={step} className="flex items-center gap-2">
          <div className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-zinc-700">
            <span className="text-[9px] font-semibold text-zinc-300">
              {i + 1}
            </span>
          </div>
          <span className="text-[10px] text-zinc-400">{step}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Cards Config ─────────────────────────────────────────────────────────────

const CARDS = [
  { label: "Bar Chart", preview: <BarChartPreview /> },
  { label: "Timeline", preview: <TimelinePreview /> },
  { label: "Status Card", preview: <StatusCardPreview /> },
  { label: "Table", preview: <ComparisonTablePreview /> },
  { label: "Avatar List", preview: <AvatarListPreview /> },
  { label: "Steps", preview: <StepListPreview /> },
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function RichResponsesDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <div ref={ref} className="grid grid-cols-2 md:grid-cols-3 gap-3 w-full">
      {CARDS.map((card, i) => (
        <m.div
          key={card.label}
          initial={{ opacity: 0, y: 12 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
          transition={{ duration: 0.3, delay: i * 0.08, ease: "easeOut" }}
          className="rounded-xl bg-zinc-800 p-3 flex flex-col gap-2"
        >
          <span className="text-xs font-medium text-zinc-400 mb-1">
            {card.label}
          </span>
          <div className="rounded-lg bg-zinc-900 p-2 flex-1 flex items-center justify-center">
            {card.preview}
          </div>
        </m.div>
      ))}
    </div>
  );
}
