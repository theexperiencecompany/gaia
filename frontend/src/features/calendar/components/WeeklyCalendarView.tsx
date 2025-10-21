"use client";

import React, { useEffect, useMemo, useRef } from "react";

import { CalendarGrid } from "@/features/calendar/components/CalendarGrid";
import { DateStrip } from "@/features/calendar/components/DateStrip";
import { useCalendarChunks } from "@/features/calendar/hooks/useCalendarChunks";
import { useCalendarEventPositioning } from "@/features/calendar/hooks/useCalendarEventPositioning";
import { useCalendarNavigation } from "@/features/calendar/hooks/useCalendarNavigation";
import { useCalendarScroll } from "@/features/calendar/hooks/useCalendarScroll";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { getExtendedDates } from "@/features/calendar/utils/dateRangeUtils";
import { getEventColor } from "@/features/calendar/utils/eventColors";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface WeeklyCalendarViewProps {
  onEventClick?: (event: GoogleCalendarEvent) => void;
}

const WeeklyCalendarView: React.FC<WeeklyCalendarViewProps> = ({
  onEventClick,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const {
    selectedDate,
    currentWeek,
    goToPreviousDay,
    goToNextDay,
    goToToday,
    handleDateChange,
  } = useCalendarNavigation();

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

  const dayEvents = useCalendarEventPositioning(events, selectedDate);

  useCalendarScroll({
    scrollContainerRef,
    dayEvents,
    selectedDate,
  });

  useEffect(() => {
    if (!isInitialized && !loading.calendars) {
      loadCalendars();
    }
  }, [isInitialized, loading.calendars, loadCalendars]);

  const getEventColorForGrid = (event: GoogleCalendarEvent) => {
    return getEventColor(event, calendars);
  };

  return (
    <div className="flex h-full w-full justify-center p-4 pt-0">
      <div className="flex h-full w-full max-w-2xl flex-col">
        <DateStrip
          dates={extendedDates}
          selectedDate={selectedDate}
          onDateSelect={handleDateChange}
        />

        <CalendarGrid
          ref={scrollContainerRef}
          hours={hours}
          dayEvents={dayEvents}
          loading={loading}
          error={error}
          selectedCalendars={selectedCalendars}
          selectedDate={selectedDate}
          onEventClick={onEventClick}
          getEventColor={getEventColorForGrid}
        />
      </div>
    </div>
  );
};

export default WeeklyCalendarView;
