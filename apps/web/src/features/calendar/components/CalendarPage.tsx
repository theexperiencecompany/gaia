"use client";

import { useCallback, useEffect } from "react";

import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import { EventSidebar } from "@/components/layout/sidebar/right-variants/CalendarRightSidebar";
import WeeklyCalendarView from "@/features/calendar/components/WeeklyCalendarView";
import { useEventSidebar } from "@/features/calendar/hooks/useEventSidebar";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { useSetCreateEventAction } from "@/stores/calendarStore";

export default function Calendar() {
  const setCreateEventAction = useSetCreateEventAction();
  const { calendars } = useSharedCalendar();

  const {
    isOpen,
    selectedEvent,
    isCreating,
    summary,
    description,
    startDate,
    endDate,
    isAllDay,
    selectedCalendarId,
    isSaving,
    recurrenceType,
    customRecurrenceDays,
    setIsAllDay,
    setSelectedCalendarId,
    setRecurrenceType,
    setCustomRecurrenceDays,
    handleSummaryChange,
    handleDescriptionChange,
    handleDateChange,
    handleCreate,
    handleDelete,
    openForEvent,
    openForCreate,
    close,
  } = useEventSidebar({
    onEventUpdate: () => {
      // Optional: trigger a background refresh without resetting the view
    },
  });

  // Set the create event action so the header can trigger it
  useEffect(() => {
    setCreateEventAction(openForCreate);
    return () => {
      setCreateEventAction(null);
    };
  }, [setCreateEventAction, openForCreate]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("create") === "true") {
      openForCreate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDateClick = useCallback(
    (date: Date) => {
      openForCreate(date);
    },
    [openForCreate],
  );

  return (
    <>
      {/* Sheet mode prevents the calendar grid from jittering as it opens. */}
      {isOpen && (
        <RightSidebarPanel mode="sheet" onClose={close}>
          <EventSidebar
            isCreating={isCreating}
            selectedEvent={selectedEvent}
            summary={summary}
            description={description}
            startDate={startDate}
            endDate={endDate}
            isAllDay={isAllDay}
            selectedCalendarId={selectedCalendarId}
            isSaving={isSaving}
            recurrenceType={recurrenceType}
            customRecurrenceDays={customRecurrenceDays}
            calendars={calendars}
            onSummaryChange={handleSummaryChange}
            onDescriptionChange={handleDescriptionChange}
            onStartDateChange={(value) => handleDateChange("start", value)}
            onEndDateChange={(value) => handleDateChange("end", value)}
            onAllDayChange={setIsAllDay}
            onCalendarChange={setSelectedCalendarId}
            onRecurrenceTypeChange={setRecurrenceType}
            onCustomRecurrenceDaysChange={setCustomRecurrenceDays}
            onCreate={handleCreate}
            onDelete={handleDelete}
          />
        </RightSidebarPanel>
      )}
      <WeeklyCalendarView
        onEventClick={openForEvent}
        onDateClick={handleDateClick}
      />
    </>
  );
}
