"use client";

import { Spinner } from "@heroui/react";
import React from "react";

interface DateStripProps {
  dates: Date[];
  selectedDate: Date;
  onDateSelect?: (date: Date) => void;
  daysToShow?: number;
  columnWidth: number;
  isLoadingPast?: boolean;
  isLoadingFuture?: boolean;
}

export const DateStrip: React.FC<DateStripProps> = ({
  dates,
  selectedDate,
  onDateSelect,
  daysToShow = 1,
  columnWidth,
  isLoadingPast = false,
  isLoadingFuture = false,
}) => {
  return (
    <div className="sticky top-0 z-[30] flex min-w-fit flex-shrink-0 border-b border-zinc-800 bg-[#1a1a1a]">
      {/* Time Label Column */}
      <div className="sticky left-0 z-[11] w-20 flex-shrink-0 border-r border-zinc-800 bg-[#1a1a1a]" />

      {/* Date Headers */}
      {dates.map((date, index) => {
        const isSelected = date.toDateString() === selectedDate.toDateString();
        const isToday = date.toDateString() === new Date().toDateString();
        const isWeekend = date.getDay() === 0 || date.getDay() === 6;
        const dayLabel = date
          .toLocaleDateString("en-US", { weekday: "short" })
          .toUpperCase();
        const dayNumber = date.getDate();

        return (
          <button
            key={index}
            onClick={() => onDateSelect?.(date)}
            className={`flex min-h-9 flex-shrink-0 cursor-pointer flex-row items-center justify-center gap-1 border-r border-zinc-800 py-1 font-light transition-all duration-200 last:border-r-0 ${
              isToday
                ? "hover:bg-zinc-700/40"
                : isSelected
                  ? "bg-zinc-800 text-white hover:bg-zinc-700/40"
                  : isWeekend
                    ? "hover:bg-zinc- bg-zinc-900 text-zinc-400"
                    : "bg-[#1a1a1a] text-zinc-400 hover:bg-zinc-800"
            }`}
            style={{ width: `${columnWidth}px` }}
          >
            <div className="text-sm font-light tracking-wide uppercase">
              {dayLabel}
            </div>
            <div
              className={`rounded-lg text-sm font-medium ${
                isToday ? "bg-primary p-1 px-2 text-black" : ""
              }`}
            >
              {dayNumber}
            </div>
          </button>
        );
      })}
    </div>
  );
};
