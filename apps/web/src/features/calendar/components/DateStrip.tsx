"use client";

import type { Virtualizer } from "@tanstack/react-virtual";
import type React from "react";
import { useSyncExternalStore } from "react";

import { formatWeekdayShort } from "@/features/calendar/utils/calendarUtils";

// Today's date read through `useSyncExternalStore`: a wall-clock value can't
// be rendered server-side without risking a hydration mismatch, and resolving
// one in a mount effect flashes stale content after the first paint. The
// server snapshot matches no day, so nothing is highlighted during SSR and
// hydration; React re-reads the client snapshot right after mounting. A no-op
// subscribe suffices — snapshots are value-compared strings, and the strip
// re-renders on every scroll/virtualization update anyway.
const noopUnsubscribe = (): void => {
  // Intentional no-op: today's date has no live source to subscribe to.
};
const subscribeToToday = (): (() => void) => noopUnsubscribe;
const getServerToday = (): string => "";
const getTodaySnapshot = (): string => new Date().toDateString();

interface DateStripProps {
  dates: Date[];
  selectedDate: Date;
  onDateSelect?: (date: Date) => void;
  daysToShow?: number;
  columnVirtualizer: Virtualizer<HTMLDivElement, Element>;
  isLoadingPast?: boolean;
  isLoadingFuture?: boolean;
}

export const DateStrip: React.FC<DateStripProps> = ({
  dates,
  selectedDate,
  onDateSelect,
  columnVirtualizer,
}) => {
  // Resolved via useSyncExternalStore (see note above the helpers) so no
  // `new Date()` runs during render and nothing flashes in after paint.
  const today = useSyncExternalStore(
    subscribeToToday,
    getTodaySnapshot,
    getServerToday,
  );

  return (
    <div className="sticky top-0 z-[30] flex min-h-9 min-w-fit flex-shrink-0 border-b border-zinc-800 bg-primary-bg">
      {/* Time Label Column */}
      <div className="sticky left-0 z-[11] w-20 flex-shrink-0 border-r border-zinc-800 bg-primary-bg" />

      {/* Date Headers - Virtualized */}
      <div className="relative min-h-9 flex-1 overflow-hidden">
        <div
          className="relative"
          style={{
            width: `${columnVirtualizer.getTotalSize()}px`,
            minHeight: "36px",
          }}
        >
          {columnVirtualizer.getVirtualItems().map((virtualColumn) => {
            const index = virtualColumn.index;
            const date = dates[index];

            if (!date) return null;

            const isSelected =
              date.toDateString() === selectedDate.toDateString();
            const isToday = today !== "" && date.toDateString() === today;
            const isWeekend = date.getDay() === 0 || date.getDay() === 6;
            const dayLabel = formatWeekdayShort(date).toUpperCase();
            const dayNumber = date.getDate();

            return (
              <button
                type="button"
                key={virtualColumn.key}
                onClick={() => onDateSelect?.(date)}
                className={`absolute top-0 left-0 flex min-h-9 flex-shrink-0 cursor-pointer flex-row items-center justify-center gap-1 border-r border-zinc-800 py-1 font-light transition-all duration-200 ${
                  isToday
                    ? "hover:bg-zinc-700/40"
                    : isSelected
                      ? "bg-zinc-800 text-white hover:bg-zinc-700/40"
                      : isWeekend
                        ? "hover:bg-zinc- bg-zinc-900 text-zinc-400"
                        : "bg-primary-bg text-zinc-400 hover:bg-zinc-800"
                }`}
                style={{
                  width: `${virtualColumn.size}px`,
                  transform: `translateX(${virtualColumn.start}px)`,
                  scrollSnapAlign: "start",
                }}
              >
                <div className="text-sm font-light tracking-wide uppercase">
                  {dayLabel}
                </div>
                <div
                  className={`rounded-lg text-sm font-medium ${isToday ? "bg-primary p-1 px-2 text-black" : ""}`}
                >
                  {dayNumber}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};
