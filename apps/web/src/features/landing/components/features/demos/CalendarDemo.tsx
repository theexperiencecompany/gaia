"use client";

import { m, useInView } from "motion/react";
import { useRef } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CalendarEvent {
  id: string;
  title: string;
  colorClass: string;
  textClass: string;
}

interface TimeSlot {
  label: string;
  hour: number;
}

interface DayColumn {
  day: string;
  date: number;
  colIndex: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const DAYS: DayColumn[] = [
  { day: "Mon", date: 24, colIndex: 0 },
  { day: "Tue", date: 25, colIndex: 1 },
  { day: "Wed", date: 26, colIndex: 2 },
  { day: "Thu", date: 27, colIndex: 3 },
  { day: "Fri", date: 28, colIndex: 4 },
];

const TIME_SLOTS: TimeSlot[] = [
  { label: "9am", hour: 9 },
  { label: "10am", hour: 10 },
  { label: "11am", hour: 11 },
  { label: "2pm", hour: 14 },
];

interface StaticEvent {
  id: string;
  colIndex: number;
  hour: number;
  event: CalendarEvent;
}

const STATIC_EVENTS: StaticEvent[] = [
  {
    id: "standup",
    colIndex: 0,
    hour: 9,
    event: {
      id: "standup",
      title: "Standup",
      colorClass: "bg-blue-400/15",
      textClass: "text-blue-300",
    },
  },
  {
    id: "one-on-one",
    colIndex: 1,
    hour: 14,
    event: {
      id: "one-on-one",
      title: "1:1 with Sam",
      colorClass: "bg-purple-400/15",
      textClass: "text-purple-300",
    },
  },
  {
    id: "sprint-review",
    colIndex: 3,
    hour: 10,
    event: {
      id: "sprint-review",
      title: "Sprint Review",
      colorClass: "bg-emerald-400/15",
      textClass: "text-emerald-300",
    },
  },
];

// ─── Component ────────────────────────────────────────────────────────────────

export default function CalendarDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const isInView = useInView(ref, { once: true, margin: "-60px" });

  return (
    <div ref={ref} className="rounded-2xl bg-zinc-900 p-4 w-full select-none">
      {/* Week header */}
      <div className="grid grid-cols-[40px_repeat(5,1fr)] mb-2">
        <div />
        {DAYS.map(({ day, date }) => (
          <div key={day} className="text-center">
            <span className="text-xs text-zinc-500 font-medium">
              {day} <span className="text-zinc-600">{date}</span>
            </span>
          </div>
        ))}
      </div>

      {/* Time grid */}
      <div className="space-y-px">
        {TIME_SLOTS.map(({ label, hour }) => (
          <div
            key={label}
            className="grid grid-cols-[40px_repeat(5,1fr)] border-t border-zinc-800"
          >
            {/* Time label */}
            <div className="py-2 pr-2 text-right">
              <span className="text-[10px] text-zinc-600 leading-none">
                {label}
              </span>
            </div>

            {/* Day cells */}
            {DAYS.map(({ colIndex }) => {
              const staticEvent = STATIC_EVENTS.find(
                (e) => e.colIndex === colIndex && e.hour === hour,
              );

              // New animated event: Wed (colIndex 2) 2pm (hour 14)
              const isNewEvent = colIndex === 2 && hour === 14;

              return (
                <div
                  key={colIndex}
                  className="py-1 px-0.5 min-h-[36px] relative"
                >
                  {staticEvent && (
                    <div
                      className={`rounded-md px-2 py-1 text-xs font-medium ${staticEvent.event.colorClass} ${staticEvent.event.textClass} truncate`}
                    >
                      {staticEvent.event.title}
                    </div>
                  )}

                  {isNewEvent && (
                    <m.div
                      initial={{ opacity: 0, y: 8 }}
                      animate={
                        isInView ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }
                      }
                      transition={{
                        duration: 0.3,
                        ease: [0.32, 0.72, 0, 1],
                        delay: 0.4,
                      }}
                      className="rounded-md px-2 py-1 bg-cyan-400/10 border border-cyan-400/30 absolute inset-x-0.5"
                    >
                      <p className="text-[10px] font-semibold text-cyan-300 truncate leading-tight">
                        Product Review
                      </p>
                      <p className="text-[9px] text-cyan-400/70 truncate leading-tight mt-0.5">
                        Alex, Sam, Jordan · 2:00 PM
                      </p>
                    </m.div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
