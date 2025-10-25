"use client";

import { useState } from "react";
import { ChevronsDownUp, ChevronsUpDown } from "lucide-react";

import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface AllDayEventsSectionProps {
  allDayEvents: GoogleCalendarEvent[];
  onEventClick?: (event: GoogleCalendarEvent) => void;
  getEventColor: (event: GoogleCalendarEvent) => string;
}

export const AllDayEventsSection: React.FC<AllDayEventsSectionProps> = ({
  allDayEvents,
  onEventClick,
  getEventColor,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div className="flex border-b border-zinc-800">
      {/* Time Label Column - matches the time labels */}
      <div
        className="w-20 flex-shrink-0 cursor-pointer border-r border-zinc-800 transition-colors hover:bg-zinc-800/50"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center justify-end gap-1 py-3 pr-3">
          <span className="text-xs font-medium text-zinc-400">All-day</span>
          {allDayEvents.length > 0 && (
            <span>
              {isExpanded ? (
                <ChevronsDownUp className="h-3 w-3 text-zinc-400" />
              ) : (
                <ChevronsUpDown className="h-3 w-3 text-zinc-400" />
              )}
            </span>
          )}
        </div>
      </div>

      {/* Events Column - matches the calendar events area */}
      <div className="flex-1 px-2 py-2">
        {allDayEvents.length === 0 ? (
          <div className="min-h-[32px]" />
        ) : isExpanded ? (
          <div className="space-y-1">
            {allDayEvents.map((event, index) => {
              const eventColor = getEventColor(event);
              return (
                <div
                  key={`allday-${index}`}
                  className="flex min-h-[32px] cursor-pointer overflow-hidden rounded-lg text-white transition-all duration-200 hover:opacity-80"
                  style={{
                    backgroundColor: `${eventColor}40`,
                  }}
                  onClick={() => onEventClick?.(event)}
                >
                  <div
                    className="w-1 rounded-l-lg"
                    style={{
                      backgroundColor: eventColor,
                    }}
                  />
                  <div className="flex items-center px-3 py-1.5">
                    <div className="line-clamp-1 text-xs font-medium">
                      {event.summary}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex min-h-[32px] items-center text-xs text-zinc-400">
            {allDayEvents.length} event{allDayEvents.length !== 1 ? "s" : ""}
          </div>
        )}
      </div>
    </div>
  );
};
