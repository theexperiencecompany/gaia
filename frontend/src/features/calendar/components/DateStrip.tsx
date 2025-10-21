"use client";

import React, { useEffect, useRef } from "react";

interface DateStripProps {
  dates: Date[];
  selectedDate: Date;
  onDateSelect: (date: Date) => void;
}

export const DateStrip: React.FC<DateStripProps> = ({
  dates,
  selectedDate,
  onDateSelect,
}) => {
  const dateStripRef = useRef<HTMLDivElement>(null);

  // Auto-scroll date strip to center the selected date
  useEffect(() => {
    if (dateStripRef.current) {
      const selectedIndex = dates.findIndex(
        (date) => date.toDateString() === selectedDate.toDateString(),
      );

      if (selectedIndex !== -1) {
        const container = dateStripRef.current;
        const buttons = container.querySelectorAll("button");

        if (buttons[selectedIndex]) {
          const selectedButton = buttons[selectedIndex];
          const containerRect = container.getBoundingClientRect();
          const buttonRect = selectedButton.getBoundingClientRect();

          // Calculate the position to center the button
          const scrollLeft = container.scrollLeft;
          const buttonCenter =
            buttonRect.left -
            containerRect.left +
            scrollLeft +
            buttonRect.width / 2;
          const containerCenter = containerRect.width / 2;
          const targetScrollLeft = buttonCenter - containerCenter;

          container.scrollTo({
            left: Math.max(0, targetScrollLeft),
            behavior: "smooth",
          });
        }
      }
    }
  }, [selectedDate, dates]);

  return (
    <div className="border-b border-zinc-800 pb-2">
      <div
        ref={dateStripRef}
        className="flex gap-2 overflow-x-auto px-4"
        style={{
          scrollbarWidth: "none",
          msOverflowStyle: "none",
        }}
      >
        {dates.map((date, index) => {
          const isSelected =
            date.toDateString() === selectedDate.toDateString();
          const isToday = date.toDateString() === new Date().toDateString();
          const isWeekend = date.getDay() === 0 || date.getDay() === 6; // Sunday or Saturday
          const isFirstDayOfWeek = date.getDay() === 1; // Monday
          const dayLabel = date
            .toLocaleDateString("en-US", { weekday: "short" })
            .toUpperCase();
          const dayNumber = date.getDate();

          return (
            <div key={index} className="flex items-center">
              {/* Week separator line - show before each Monday (except the first one) */}
              {isFirstDayOfWeek && index > 0 && (
                <div className="mr-2 h-12 w-px flex-shrink-0 bg-zinc-700" />
              )}

              <button
                onClick={() => onDateSelect(date)}
                className={`flex min-w-[60px] flex-col items-center rounded-2xl px-3 py-2 transition-all duration-200 ${
                  isSelected
                    ? "bg-primary text-black"
                    : isToday
                      ? "bg-zinc-700/50 text-white"
                      : isWeekend
                        ? "bg-zinc-800/20 text-zinc-500 hover:bg-zinc-800"
                        : "text-zinc-400 hover:bg-zinc-800"
                }`}
              >
                <div className="text-xs">{dayLabel}</div>
                <div
                  className={`text-lg font-semibold ${
                    isSelected
                      ? "text-black"
                      : isToday
                        ? "text-white"
                        : isWeekend
                          ? "text-zinc-400"
                          : "text-zinc-300"
                  }`}
                >
                  {dayNumber}
                </div>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};
