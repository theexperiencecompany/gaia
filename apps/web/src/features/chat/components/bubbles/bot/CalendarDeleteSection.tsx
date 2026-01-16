import { Button } from "@heroui/button";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { useState } from "react";
import { toast } from "sonner";

import { calendarApi } from "@/features/calendar/api/calendarApi";
import { Cancel01Icon, Tick02Icon } from "@/icons";
import type { CalendarDeleteOptions } from "@/types/features/calendarTypes";
import { buildDeleteEventPayload } from "@/utils/calendar/eventPayloadBuilders";
import { formatDateWithRelative } from "@/utils/date/calendarDateUtils";

import { EventCard } from "./CalendarEventCard";
import { EventContent } from "./CalendarEventContent";

interface CalendarDeleteSectionProps {
  calendar_delete_options: CalendarDeleteOptions[];
}

type EventStatus = "idle" | "loading" | "completed";

export function CalendarDeleteSection({
  calendar_delete_options,
}: CalendarDeleteSectionProps) {
  const [eventStatuses, setEventStatuses] = useState<
    Record<string, EventStatus>
  >({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  if (!calendar_delete_options?.length) return null;

  const handleDelete = async (event: CalendarDeleteOptions) => {
    const key = event.event_id;
    try {
      setEventStatuses((prev) => ({ ...prev, [key]: "loading" }));
      await calendarApi.deleteEventByAgent(buildDeleteEventPayload(event));
      setEventStatuses((prev) => ({ ...prev, [key]: "completed" }));
    } catch (error) {
      console.error("Error deleting event:", error);
      setEventStatuses((prev) => ({ ...prev, [key]: "idle" }));
      toast.error("Failed to delete event");
    }
  };

  const handleDeleteAll = async () => {
    setIsConfirmingAll(true);
    const pendingEvents = calendar_delete_options.filter(
      (event) => eventStatuses[event.event_id] !== "completed",
    );

    try {
      await Promise.all(pendingEvents.map((event) => handleDelete(event)));
    } catch (error) {
      console.error("Error deleting events:", error);
      toast.error("Failed to delete all events");
    } finally {
      setIsConfirmingAll(false);
    }
  };

  const allCompleted = calendar_delete_options.every(
    (event) => eventStatuses[event.event_id] === "completed",
  );

  const hasCompletedEvents = calendar_delete_options.some(
    (event) => eventStatuses[event.event_id] === "completed",
  );

  // Group by date
  const eventsByDate: Record<string, CalendarDeleteOptions[]> = {};
  calendar_delete_options.forEach((event) => {
    const dateStr =
      event.start?.dateTime || event.start?.date || new Date().toISOString();
    const date = new Date(dateStr).toISOString().slice(0, 10);
    if (!eventsByDate[date]) eventsByDate[date] = [];
    eventsByDate[date].push(event);
  });

  return (
    <div className="w-full max-w-md rounded-3xl bg-surface-200 p-4 text-white">
      <ScrollShadow className="mt-2 max-h-[400px] space-y-3">
        {Object.entries(eventsByDate).map(([dateString, events]) => (
          <div key={dateString} className="space-y-3">
            <div className="relative flex items-center">
              <div className="flex-1 border-t border-surface-300" />
              <span className="px-3 text-xs text-foreground-500">
                {formatDateWithRelative(dateString)}
              </span>
              <div className="flex-1 border-t border-surface-300" />
            </div>

            <div className="space-y-2">
              {events.map((event) => {
                const status = eventStatuses[event.event_id] || "idle";
                const eventColor = event.background_color || "#00bbff";

                return (
                  <EventCard
                    key={event.event_id}
                    eventColor={eventColor}
                    status={status}
                    variant="action"
                    buttonColor="danger"
                    completedLabel="Deleted"
                    icon={Cancel01Icon}
                    onAction={() => handleDelete(event)}
                  >
                    <EventContent event={event} />
                  </EventCard>
                );
              })}
            </div>
          </div>
        ))}
      </ScrollShadow>

      {calendar_delete_options.length > 1 && (
        <Button
          className="mt-3"
          color="danger"
          variant="solid"
          fullWidth
          isDisabled={allCompleted}
          isLoading={isConfirmingAll}
          onPress={handleDeleteAll}
        >
          {allCompleted ? (
            <>
              <Tick02Icon width={22} />
              All Deleted
            </>
          ) : hasCompletedEvents ? (
            "Delete Remaining"
          ) : (
            "Delete All Events"
          )}
        </Button>
      )}
    </div>
  );
}
