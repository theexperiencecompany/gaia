"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";

import { EventSidebar } from "@/features/calendar/components/EventSidebar";
import WeeklyCalendarView from "@/features/calendar/components/WeeklyCalendarView";
import { useEventSidebar } from "@/features/calendar/hooks/useEventSidebar";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { useSetCreateEventAction } from "@/stores/calendarStore";
import { useRightSidebar } from "@/stores/rightSidebarStore";

export default function Calendar() {
  const searchParams = useSearchParams();
  const { loadEvents } = useSharedCalendar();
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
    isSaving,
    setIsAllDay,
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
      loadEvents();
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
          isOpen={isOpen}
          isCreating={isCreating}
          selectedEvent={selectedEvent}
          summary={summary}
          description={description}
          startDate={startDate}
          endDate={endDate}
          isAllDay={isAllDay}
          isSaving={isSaving}
          onSummaryChange={handleSummaryChange}
          onDescriptionChange={handleDescriptionChange}
          onStartDateChange={(value) => handleDateChange("start", value)}
          onEndDateChange={(value) => handleDateChange("end", value)}
          onAllDayChange={setIsAllDay}
          onCreate={handleCreate}
          onDelete={handleDelete}
          onClose={handleClose}
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
    isSaving,
    handleSummaryChange,
    handleDescriptionChange,
    handleDateChange,
    setIsAllDay,
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

  return <WeeklyCalendarView onEventClick={openForEvent} />;
}
