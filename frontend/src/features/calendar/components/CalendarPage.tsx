"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { EventSidebar } from "@/features/calendar/components/EventSidebar";
import WeeklyCalendarView from "@/features/calendar/components/WeeklyCalendarView";
import { useEventSidebar } from "@/features/calendar/hooks/useEventSidebar";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { useSetCreateEventAction } from "@/stores/calendarStore";

export default function Calendar() {
  const searchParams = useSearchParams();
  const { loadEvents } = useSharedCalendar();
  const setCreateEventAction = useSetCreateEventAction();

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

  // Set the create event action so the header can trigger it
  useEffect(() => {
    setCreateEventAction(openForCreate);
    return () => setCreateEventAction(null);
  }, [setCreateEventAction, openForCreate]);

  useEffect(() => {
    if (searchParams?.get("create") === "true") {
      openForCreate();
    }
  }, [searchParams, openForCreate]);

  return (
    <>
      <div className="relative flex h-full w-full">
        <WeeklyCalendarView onEventClick={openForEvent} />
      </div>

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
        onClose={close}
      />
    </>
  );
}
