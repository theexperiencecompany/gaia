"use client";

import { useMemo } from "react";
import {
  DAY_START_HOUR,
  DEMO_CALENDARS,
  DEMO_EVENTS,
  getDemoWeekDates,
  HOURS,
  PX_PER_HOUR,
  PX_PER_MINUTE,
} from "./calendarDemoConstants";

function formatHour(hour: number): string {
  if (hour === 0) return "12 AM";
  if (hour < 12) return `${hour} AM`;
  if (hour === 12) return "12 PM";
  return `${hour - 12} PM`;
}

function formatTime12(date: Date): string {
  const h = date.getHours();
  const m = date.getMinutes();
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return m === 0
    ? `${h12} ${ampm}`
    : `${h12}:${m.toString().padStart(2, "0")} ${ampm}`;
}

export default function DemoCalendarView() {
  const dates = useMemo(() => getDemoWeekDates(), []);
  const today = new Date();
  const todayStr = today.toDateString();

  // Current time position
  const currentHour = today.getHours();
  const currentMinute = today.getMinutes();
  const currentTimeTop =
    (currentHour - DAY_START_HOUR) * PX_PER_HOUR +
    currentMinute * PX_PER_MINUTE;

  // Group events by date
  const eventsByDate = useMemo(() => {
    const map: Record<string, typeof DEMO_EVENTS> = {};
    for (const event of DEMO_EVENTS) {
      const dateStr = event.start.dateTime.slice(0, 10);
      if (!map[dateStr]) map[dateStr] = [];
      map[dateStr].push(event);
    }
    return map;
  }, []);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Date Strip Header */}
      <div className="sticky top-0 z-[30] flex border-b border-zinc-800">
        {/* Time column spacer */}
        <div className="w-16 shrink-0 border-r border-zinc-800" />
        {/* Date columns */}
        <div className="flex flex-1">
          {dates.map((date) => {
            const isToday = date.toDateString() === todayStr;
            const dayLabel = date
              .toLocaleDateString("en-US", { weekday: "short" })
              .toUpperCase();
            const dayNum = date.getDate();

            return (
              <div
                key={date.toISOString()}
                className="flex flex-1 flex-col items-center py-2"
                style={{
                  backgroundColor: isToday ? "transparent" : "#111111",
                }}
              >
                <span
                  className={`text-[10px] font-medium ${isToday ? "text-primary" : "text-zinc-500"}`}
                >
                  {dayLabel}
                </span>
                <span
                  className={`mt-0.5 flex h-7 w-7 items-center justify-center rounded-full text-sm font-medium ${
                    isToday ? "bg-primary text-black" : "text-zinc-400"
                  }`}
                >
                  {dayNum}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Calendar Grid */}
      <div className="relative flex flex-1 overflow-y-auto overflow-x-hidden">
        {/* Time labels column */}
        <div
          className="sticky left-0 z-[11] w-16 shrink-0 border-r border-zinc-800"
          style={{ backgroundColor: "#111111" }}
        >
          {HOURS.map((hour) => (
            <div
              key={hour}
              className="relative flex items-start justify-end pr-2"
              style={{ height: PX_PER_HOUR }}
            >
              <span className="relative -top-2 text-[10px] text-zinc-500">
                {formatHour(hour)}
              </span>
            </div>
          ))}
        </div>

        {/* Day columns */}
        <div className="relative flex flex-1">
          {/* Hour dividers */}
          {HOURS.map((hour) => (
            <div
              key={`divider-${hour}`}
              className="pointer-events-none absolute left-0 right-0 border-t border-zinc-800/60"
              style={{ top: hour * PX_PER_HOUR }}
            />
          ))}

          {/* Current time line */}
          <div
            className="pointer-events-none absolute left-0 right-0 z-[5]"
            style={{ top: currentTimeTop }}
          >
            <div className="flex items-center">
              <div className="h-2.5 w-2.5 rounded-full bg-primary" />
              <div className="h-[2px] flex-1 bg-primary/50" />
            </div>
          </div>

          {/* Day columns with events */}
          {dates.map((date) => {
            const dateStr = date.toISOString().slice(0, 10);
            const events = eventsByDate[dateStr] || [];

            return (
              <div
                key={date.toISOString()}
                className="relative flex-1 border-r border-zinc-800/40"
                style={{ height: 24 * PX_PER_HOUR }}
              >
                {events.map((event) => {
                  const startDate = new Date(event.start.dateTime);
                  const endDate = new Date(event.end.dateTime);
                  const startMinutes =
                    startDate.getHours() * 60 + startDate.getMinutes();
                  const endMinutes =
                    endDate.getHours() * 60 + endDate.getMinutes();
                  const top =
                    (startMinutes - DAY_START_HOUR * 60) * PX_PER_MINUTE;
                  const height = (endMinutes - startMinutes) * PX_PER_MINUTE;
                  const color =
                    DEMO_CALENDARS.find((c) => c.id === event.calendarId)
                      ?.backgroundColor || "#00bbff";

                  return (
                    <div
                      key={event.id}
                      className="absolute left-0.5 right-0.5 cursor-pointer overflow-hidden rounded-lg backdrop-blur-3xl transition-all hover:brightness-110"
                      style={{
                        top,
                        height: Math.max(height, 20),
                        backgroundColor: `${color}40`,
                      }}
                    >
                      {/* Left accent bar */}
                      <div
                        className="absolute left-0 top-0 h-full w-1 rounded-l-lg"
                        style={{ backgroundColor: color }}
                      />
                      <div className="pl-2.5 pr-1 py-1">
                        <div className="text-xs font-medium text-white line-clamp-2">
                          {event.summary}
                        </div>
                        {height > 30 && (
                          <div className="text-[10px] text-zinc-400">
                            {formatTime12(startDate)} – {formatTime12(endDate)}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
