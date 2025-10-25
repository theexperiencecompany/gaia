"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";

import { EventSidebar } from "@/components/layout/sidebar/right-variants/EventSidebar";
import WeeklyCalendarView from "@/features/calendar/components/WeeklyCalendarView";
import { useEventSidebar } from "@/features/calendar/hooks/useEventSidebar";
import { useSetCreateEventAction } from "@/stores/calendarStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function Calendar() {
  const searchParams = useSearchParams();
  const setCreateEventAction = useSetCreateEventAction();

  // Use selectors to get only the functions, not subscribe to state changes
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);

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

  // Memoize the close handler to prevent infinite loops
  const handleClose = useCallback(() => {
    close();
    closeRightSidebar();
  }, [close, closeRightSidebar]);

  // Sync event sidebar state with right sidebar
  useEffect(() => {
    if (isOpen) {
      setRightSidebarContent(
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
        />,
      );
    } else {
      setRightSidebarContent(null);
    }
  }, [
    isOpen,
    isCreating,
    selectedEvent,
    summary,
    description,
    startDate,
    endDate,
    isAllDay,
    selectedCalendarId,
    isSaving,
    recurrenceType,
    customRecurrenceDays,
    handleSummaryChange,
    handleDescriptionChange,
    handleDateChange,
    setIsAllDay,
    setSelectedCalendarId,
    setRecurrenceType,
    setCustomRecurrenceDays,
    handleCreate,
    handleDelete,
    handleClose,
    setRightSidebarContent,
  ]);

  // Set the create event action so the header can trigger it
  useEffect(() => {
    setCreateEventAction(openForCreate);
    return () => {
      setCreateEventAction(null);
    };
  }, [setCreateEventAction, openForCreate]);

  // Cleanup right sidebar on unmount
  useEffect(() => {
    return () => {
      closeRightSidebar();
    };
  }, [closeRightSidebar]);

  useEffect(() => {
    if (searchParams?.get("create") === "true") {
      openForCreate();
    }
  }, [searchParams, openForCreate]);

  const handleDateClick = useCallback(
    (date: Date) => {
      openForCreate(date);
    },
    [openForCreate],
  );

  return (
    <WeeklyCalendarView
      onEventClick={openForEvent}
      onDateClick={handleDateClick}
    />
  );
}
