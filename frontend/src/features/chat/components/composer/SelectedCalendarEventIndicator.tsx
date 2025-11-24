"use client";

import { AnimatePresence, motion } from "framer-motion";
import React from "react";

import { SelectedCalendarEventData } from "@/features/chat/hooks/useCalendarEventSelection";
import { Cancel01Icon } from "@/icons";

interface SelectedCalendarEventIndicatorProps {
  event: SelectedCalendarEventData | null;
  onRemove?: () => void;
}

const formatEventTime = (
  start: SelectedCalendarEventData["start"],
  end: SelectedCalendarEventData["end"],
  isAllDay?: boolean,
): string => {
  if (isAllDay && start.date) {
    return start.date;
  }

  if (start.dateTime && end.dateTime) {
    const startDate = new Date(start.dateTime);
    const endDate = new Date(end.dateTime);

    const formatTime = (date: Date) => {
      return date.toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      });
    };

    return `${formatTime(startDate)} - ${formatTime(endDate)}`;
  }

  return "Time not specified";
};

export default function SelectedCalendarEventIndicator({
  event,
  onRemove,
}: SelectedCalendarEventIndicatorProps) {
  if (!event) {
    return null;
  }

  const timeDisplay = formatEventTime(event.start, event.end, event.isAllDay);
  const backgroundColor = event.backgroundColor || "#00bbff";

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{
          type: "spring",
          damping: 20,
          stiffness: 300,
          duration: 0.2,
        }}
        className="relative mx-3 mt-2 mb-1 flex w-fit max-w-lg items-center gap-2 overflow-hidden rounded-xl px-2 py-2"
      >
        <div
          className="absolute inset-y-0 left-0 w-1"
          style={{ backgroundColor }}
        />
        <div
          className="absolute inset-0 rounded-xl opacity-20"
          style={{ backgroundColor }}
        />
        <div className="relative z-1 flex min-w-0 flex-1 items-center gap-2 pl-1">
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-light text-zinc-200">
              {event.summary}
            </span>
            <div className="flex items-center gap-1.5">
              <span className="truncate text-xs text-zinc-400">
                {timeDisplay}
              </span>
            </div>
          </div>
        </div>
        {onRemove && (
          <motion.button
            onClick={onRemove}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
            className="relative z-1 flex h-6 w-6 flex-shrink-0 cursor-pointer items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-zinc-600 hover:text-zinc-200"
          >
            <Cancel01Icon size={15} />
          </motion.button>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
