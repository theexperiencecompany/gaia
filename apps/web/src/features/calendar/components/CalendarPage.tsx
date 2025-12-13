"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo } from "react";

import { EventSidebar } from "@/components/layout/sidebar/right-variants/CalendarRightSidebar";
import WeeklyCalendarView from "@/features/calendar/components/WeeklyCalendarView";
import { useEventSidebar } from "@/features/calendar/hooks/useEventSidebar";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { useSetCreateEventAction } from "@/stores/calendarStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function Calendar() {
  const searchParams = useSearchParams();
  const setCreateEventAction = useSetCreateEventAction();
  const { calendars } = useSharedCalendar();

  // Use selectors to get only the functions, not subscribe to state changes
  const setRightSidebarContent = useRightSidebar((state) => state.setContent);
  const closeRightSidebar = useRightSidebar((state) => state.close);
  const openRightSidebar = useRightSidebar((state) => state.open);
  const setRightSidebarVariant = useRightSidebar((state) => state.setVariant);

  // Set sidebar to sheet mode to prevent calendar jitter
  useEffect(() => {
    setRightSidebarVariant("sheet");
  }, [setRightSidebarVariant]);

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

  // Memoize the sidebar content to prevent unnecessary recreations
  const sidebarContent = useMemo(
    () => (
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
    ),
    [
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
      calendars,
      handleSummaryChange,
      handleDescriptionChange,
      handleDateChange,
      setIsAllDay,
      setSelectedCalendarId,
      setRecurrenceType,
      setCustomRecurrenceDays,
      handleCreate,
      handleDelete,
    ],
  );

  // Handle opening/closing the right sidebar - only trigger on isOpen changes
  useEffect(() => {
    if (isOpen) {
      setRightSidebarContent(sidebarContent);
      openRightSidebar("sheet");
    } else {
      closeRightSidebar();
    }
  }, [
    isOpen,
    sidebarContent,
    setRightSidebarContent,
    openRightSidebar,
    closeRightSidebar,
  ]);

  // Sync close action from right sidebar to event sidebar
  useEffect(() => {
    const unsubscribe = useRightSidebar.subscribe((state, prevState) => {
      // If right sidebar was closed externally (e.g., close button), close event sidebar too
      if (prevState.isOpen && !state.isOpen && isOpen) {
        close();
      }
    });
    return unsubscribe;
  }, [isOpen, close]);

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
