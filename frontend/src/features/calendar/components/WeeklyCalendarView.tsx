"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";

import { CalendarGrid } from "@/features/calendar/components/CalendarGrid";
import { DateStrip } from "@/features/calendar/components/DateStrip";
import { useCalendarChunks } from "@/features/calendar/hooks/useCalendarChunks";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { getExtendedDates } from "@/features/calendar/utils/dateRangeUtils";
import { getEventColor } from "@/features/calendar/utils/eventColors";
import {
  useCalendarCurrentWeek,
  useCalendarSelectedDate,
  useDaysToShow,
} from "@/stores/calendarStore";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface WeeklyCalendarViewProps {
  onEventClick?: (event: GoogleCalendarEvent) => void;
  onDateClick?: (date: Date) => void;
}

const WeeklyCalendarView: React.FC<WeeklyCalendarViewProps> = ({
  onEventClick,
  onDateClick,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [columnWidth, setColumnWidth] = useState(150);

  const selectedDate = useCalendarSelectedDate();
  const currentWeek = useCalendarCurrentWeek();
  const daysToShow = useDaysToShow();

  const {
    events,
    loading,
    error,
    calendars,
    selectedCalendars,
    isInitialized,
    loadEvents,
  } = useSharedCalendar();

  const hours = useMemo(() => Array.from({ length: 24 }, (_, i) => i), []);

  const extendedDates = useMemo(
    () => getExtendedDates(currentWeek, 2),
    [currentWeek],
  );

  useCalendarChunks({
    extendedDates,
    selectedCalendars,
    isInitialized,
    loadEvents,
  });

  const getEventColorForGrid = (event: GoogleCalendarEvent) => {
    return getEventColor(event, calendars);
  };

  // Current time calculation (updates every minute)
  const [now, setNow] = React.useState<Date>(new Date());
  useEffect(() => {
    const interval = setInterval(() => {
      setNow(new Date());
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const currentHour = now.getHours();
  const currentMinute = now.getMinutes();
  const currentTimeLabel = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const PX_PER_MINUTE = 64 / 60;
  const currentTimeTop = (currentHour * 60 + currentMinute) * PX_PER_MINUTE;

  // Calculate dynamic column width based on container size
  useEffect(() => {
    const updateColumnWidth = () => {
      if (containerRef.current) {
        const containerWidth = containerRef.current.offsetWidth;
        const timeColumnWidth = 80; // w-20
        const availableWidth = containerWidth - timeColumnWidth;
        const calculatedWidth = Math.floor(availableWidth / daysToShow);
        setColumnWidth(Math.max(calculatedWidth, 120)); // min 120px per column
      }
    };

    updateColumnWidth();

    const resizeObserver = new ResizeObserver(updateColumnWidth);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      resizeObserver.disconnect();
    };
  }, [daysToShow]);

  // Auto-scroll to selected date when it changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      const selectedIndex = extendedDates.findIndex(
        (date) => date.toDateString() === selectedDate.toDateString(),
      );

      if (selectedIndex !== -1) {
        const scrollLeft = selectedIndex * columnWidth;

        scrollContainerRef.current.scrollTo({
          left: scrollLeft,
          behavior: "smooth",
        });
      }
    }
  }, [selectedDate, extendedDates]); // Removed columnWidth dependency

  return (
    <div className="flex h-full w-full justify-center p-4 pt-4">
      <div
        ref={containerRef}
        className="flex h-full w-full flex-col overflow-hidden"
      >
        <div
          ref={scrollContainerRef}
          className="relative flex h-full w-full flex-col overflow-auto"
        >
          <DateStrip
            dates={extendedDates}
            selectedDate={selectedDate}
            onDateSelect={onDateClick}
            daysToShow={daysToShow}
            columnWidth={columnWidth}
          />

          <CalendarGrid
            hours={hours}
            dates={extendedDates}
            events={events}
            loading={loading}
            error={error}
            selectedCalendars={selectedCalendars}
            onEventClick={onEventClick}
            getEventColor={getEventColorForGrid}
            currentTimeTop={currentTimeTop}
            currentTimeLabel={currentTimeLabel}
            columnWidth={columnWidth}
          />
        </div>
      </div>
    </div>
  );
};

export default WeeklyCalendarView;
