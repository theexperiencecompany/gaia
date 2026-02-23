"use client";

import type { Virtualizer } from "@tanstack/react-virtual";
import type React from "react";

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
  return (
    <div className="sticky top-0 z-[30] flex min-h-9 min-w-fit flex-shrink-0 border-b border-border-surface-800 bg-primary-bg">
      {/* Time Label Column */}
      <div className="sticky left-0 z-[11] w-20 flex-shrink-0 border-r border-border-surface-800 bg-primary-bg" />

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
            const isToday = date.toDateString() === new Date().toDateString();
            const isWeekend = date.getDay() === 0 || date.getDay() === 6;
            const dayLabel = date
              .toLocaleDateString("en-US", { weekday: "short" })
              .toUpperCase();
            const dayNumber = date.getDate();

            return (
              <button
                type="button"
                key={virtualColumn.key}
                onClick={() => onDateSelect?.(date)}
                className={`absolute top-0 left-0 flex min-h-9 flex-shrink-0 cursor-pointer flex-row items-center justify-center gap-1 border-r border-border-surface-800 py-1 font-light transition-all duration-200 ${
                  isToday
                    ? "hover:bg-surface-700/40"
                    : isSelected
                      ? "bg-surface-200 text-white hover:bg-surface-700/40"
                      : isWeekend
                        ? "hover:bg-surface-200 bg-surface-100 text-foreground-400"
                        : "bg-primary-bg text-foreground-400 hover:bg-surface-200"
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
                  className={`rounded-lg text-sm font-medium ${
                    isToday ? "bg-primary p-1 px-2 text-primary-foreground" : ""
                  }`}
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
