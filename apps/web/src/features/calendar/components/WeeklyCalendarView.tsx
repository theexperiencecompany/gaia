"use client";

import { Button } from "@heroui/react";
import {
  CONNECT_ACTION_LABEL,
  integrationConnectionState,
} from "@shared/utils";
import type React from "react";
import { useMemo } from "react";

import { GoogleCalendarIcon } from "@/components/shared/icons";
import { CalendarGrid } from "@/features/calendar/components/CalendarGrid";
import { DateStrip } from "@/features/calendar/components/DateStrip";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { useWeeklyCalendarScroll } from "@/features/calendar/hooks/useWeeklyCalendarScroll";
import { getEventColor } from "@/features/calendar/utils/eventColors";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useCalendarSelectedDate, useDaysToShow } from "@/stores/calendarStore";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface WeeklyCalendarViewProps {
  onEventClick?: (event: GoogleCalendarEvent) => void;
  onDateClick?: (date: Date) => void;
}

const WeeklyCalendarView: React.FC<WeeklyCalendarViewProps> = ({
  onEventClick,
  onDateClick,
}) => {
  // Hooks
  const {
    events,
    loading,
    error,
    calendars,
    selectedCalendars,
    isInitialized,
    loadEvents,
  } = useSharedCalendar();

  const { getIntegrationStatus, connectIntegration } = useIntegrations();
  const calendarState = integrationConnectionState(
    getIntegrationStatus("googlecalendar")?.status,
  );
  const isCalendarConnected = calendarState === "connected";
  const connectLabel = CONNECT_ACTION_LABEL[calendarState];

  // Store selectors (render-only; scroll state lives in
  // useWeeklyCalendarScroll)
  const selectedDate = useCalendarSelectedDate();
  const daysToShow = useDaysToShow();

  // Memoized values
  const hours = useMemo(() => Array.from({ length: 24 }, (_, i) => i), []);

  // Scrolling, virtualization, date-range and infinite-loading machinery
  const {
    containerRef,
    scrollContainerRef,
    columnVirtualizer,
    extendedDates,
    isLoadingPast,
    isLoadingFuture,
  } = useWeeklyCalendarScroll({ selectedCalendars, isInitialized, loadEvents });

  return (
    <div className="flex h-full w-full justify-center p-4 pt-4">
      <div
        ref={containerRef}
        className="flex h-full w-full flex-col overflow-hidden"
      >
        {!isCalendarConnected ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2">
            <GoogleCalendarIcon className="h-12 w-12 text-zinc-600" />
            <h2 className="text-xl font-semibold text-zinc-300 mt-2">
              {connectLabel} Google Calendar
            </h2>
            <p className="text-sm text-zinc-500 text-center max-w-lg">
              View and manage your events in GAIA.
            </p>
            <Button
              color="primary"
              className="mt-4"
              onPress={() => connectIntegration("googlecalendar")}
            >
              {connectLabel} Calendar
            </Button>
          </div>
        ) : (
          <div
            ref={scrollContainerRef}
            data-calendar-scroll
            className="relative flex h-full w-full flex-col overflow-auto"
            style={{
              scrollSnapType: "x proximity",
              scrollPaddingLeft: "80px",
            }}
          >
            <DateStrip
              dates={extendedDates}
              selectedDate={selectedDate}
              onDateSelect={onDateClick}
              daysToShow={daysToShow}
              columnVirtualizer={columnVirtualizer}
              isLoadingPast={isLoadingPast}
              isLoadingFuture={isLoadingFuture}
            />

            <CalendarGrid
              hours={hours}
              dates={extendedDates}
              events={events}
              loading={loading}
              error={error}
              selectedCalendars={selectedCalendars}
              onEventClick={onEventClick}
              getEventColor={(event) => getEventColor(event, calendars)}
              columnVirtualizer={columnVirtualizer}
              isLoadingPast={isLoadingPast}
              isLoadingFuture={isLoadingFuture}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default WeeklyCalendarView;
