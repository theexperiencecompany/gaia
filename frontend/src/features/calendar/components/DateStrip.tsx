"use client";

import React, { useEffect, useRef } from "react";

interface DateStripProps {
  dates: Date[];
  selectedDate: Date;
  onDateSelect?: (date: Date) => void;
  daysToShow?: number;
  visibleDates?: Date[];
}

export const DateStrip: React.FC<DateStripProps> = ({
  dates,
  selectedDate,
  onDateSelect,
  daysToShow = 1,
  visibleDates,
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

  const displayDates =
    daysToShow > 1 && visibleDates ? visibleDates : [selectedDate];

  return (
    <div className="border-b border-zinc-800 pb-2">
      <div className="flex">
        <div className="w-20 flex-shrink-0" />
        <div
          className="grid w-full gap-1"
          style={{ gridTemplateColumns: `repeat(${daysToShow}, 1fr)` }}
        >
          {displayDates.map((date, index) => {
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
                key={index}
                onClick={() => onDateSelect?.(date)}
                className={`flex min-h-9 w-[98%] cursor-pointer flex-row items-center justify-center gap-1 rounded-md py-1 font-light transition-all duration-200 ${
                  isToday
                    ? "hover:bg-zinc-700/40"
                    : isSelected
                      ? "bg-zinc-800 text-white hover:bg-zinc-700/40"
                      : isWeekend
                        ? "bg-zinc-800/60 text-zinc-400 hover:bg-zinc-800"
                        : "text-zinc-400 hover:bg-zinc-800"
                }`}
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
      </div>
    </div>
  );
};
