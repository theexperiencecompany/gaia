"use client";

import React, { useEffect, useMemo, useRef } from "react";

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
  useHandleDateChange,
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
    loadCalendars,
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

  useEffect(() => {
    if (!isInitialized && !loading.calendars) {
      loadCalendars();
    }
  }, [isInitialized, loading.calendars, loadCalendars]);

  const getEventColorForGrid = (event: GoogleCalendarEvent) => {
    return getEventColor(event, calendars);
  };

  const visibleDates = useMemo(() => {
    const startIndex = extendedDates.findIndex(
      (date) => date.toDateString() === selectedDate.toDateString(),
    );
    if (startIndex === -1) return [selectedDate];
    return extendedDates.slice(startIndex, startIndex + daysToShow);
  }, [extendedDates, selectedDate, daysToShow]);

  return (
    <div className="flex h-full w-full justify-center p-4 pt-4">
      <div className="flex h-full w-full flex-col px-10">
        <DateStrip
          dates={extendedDates}
          selectedDate={selectedDate}
          onDateSelect={onDateClick}
          daysToShow={daysToShow}
          visibleDates={visibleDates}
        />

        <CalendarGrid
          ref={scrollContainerRef}
          hours={hours}
          dates={visibleDates}
          events={events}
          loading={loading}
          error={error}
          selectedCalendars={selectedCalendars}
          onEventClick={onEventClick}
          getEventColor={getEventColorForGrid}
        />
      </div>
    </div>
  );
};

export default WeeklyCalendarView;
