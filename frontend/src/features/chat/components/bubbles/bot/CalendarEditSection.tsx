import { Button } from "@heroui/button";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { useState } from "react";
import { toast } from "sonner";

import { calendarApi } from "@/features/calendar/api/calendarApi";
import { CalendarCheckIn01Icon, Tick02Icon } from "@/icons";
import { CalendarEditOptions } from "@/types/features/calendarTypes";
import { hasEventChanges } from "@/utils/calendar/eventHelpers";
import { buildEditEventPayload } from "@/utils/calendar/eventPayloadBuilders";
import { formatDateWithRelative } from "@/utils/date/calendarDateUtils";

import { EventCard } from "./CalendarEventCard";
import { EventContent } from "./CalendarEventContent";

interface CalendarEditSectionProps {
  calendar_edit_options: CalendarEditOptions[];
}

type EventStatus = "idle" | "loading" | "completed";

export function CalendarEditSection({
  calendar_edit_options,
}: CalendarEditSectionProps) {
  const [eventStatuses, setEventStatuses] = useState<
    Record<string, EventStatus>
  >({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  if (!calendar_edit_options?.length) return null;

  const handleEdit = async (event: CalendarEditOptions) => {
    const key = event.event_id;
    try {
      setEventStatuses((prev) => ({ ...prev, [key]: "loading" }));
      await calendarApi.updateEventByAgent(buildEditEventPayload(event));
      setEventStatuses((prev) => ({ ...prev, [key]: "completed" }));
    } catch (error) {
      console.error("Error updating event:", error);
      setEventStatuses((prev) => ({ ...prev, [key]: "idle" }));
      toast.error("Failed to update event");
    }
  };

  const handleEditAll = async () => {
    setIsConfirmingAll(true);
    const pendingEvents = calendar_edit_options.filter(
      (event) => eventStatuses[event.event_id] !== "completed",
    );

    try {
      await Promise.all(pendingEvents.map((event) => handleEdit(event)));
    } catch (error) {
      console.error("Error updating events:", error);
      toast.error("Failed to update all events");
    } finally {
      setIsConfirmingAll(false);
    }
  };

  const allCompleted = calendar_edit_options.every(
    (event) => eventStatuses[event.event_id] === "completed",
  );

  const hasCompletedEvents = calendar_edit_options.some(
    (event) => eventStatuses[event.event_id] === "completed",
  );

  // Group by date
  const eventsByDate: Record<string, CalendarEditOptions[]> = {};
  calendar_edit_options.forEach((event) => {
    const dateStr =
      event.original_start?.dateTime ||
      event.original_start?.date ||
      new Date().toISOString();
    const date = new Date(dateStr).toISOString().slice(0, 10);
    if (!eventsByDate[date]) eventsByDate[date] = [];
    eventsByDate[date].push(event);
  });

  return (
    <div className="w-full max-w-md rounded-3xl bg-zinc-800 p-4 text-white">
      <ScrollShadow className="mt-2 max-h-[400px] space-y-3">
        {Object.entries(eventsByDate).map(([dateString, events]) => (
          <div key={dateString} className="space-y-3">
            <div className="relative flex items-center">
              <div className="flex-1 border-t border-zinc-700" />
              <span className="px-3 text-xs text-zinc-500">
                {formatDateWithRelative(dateString)}
              </span>
              <div className="flex-1 border-t border-zinc-700" />
            </div>

            <div className="space-y-2">
              {events.map((event) => {
                const status = eventStatuses[event.event_id] || "idle";
                const eventColor = event.background_color || "#00bbff";
                const showChanges = hasEventChanges(event);

                return (
                  <div key={event.event_id} className="space-y-2">
                    {status !== "completed" && showChanges && (
                      <EventCard
                        eventColor={eventColor}
                        label="Current Event"
                        variant="display"
                        opacity={0.6}
                      >
                        <EventContent event={event} showOriginal />
                      </EventCard>
                    )}

                    <EventCard
                      eventColor={eventColor}
                      status={status}
                      label={
                        status === "completed" ? undefined : "Updated Event"
                      }
                      variant="action"
                      buttonColor="primary"
                      completedLabel="Updated"
                      icon={CalendarCheckIn01Icon}
                      onAction={() => handleEdit(event)}
                      isDotted={showChanges && status !== "completed"}
                    >
                      <EventContent event={event} />
                    </EventCard>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </ScrollShadow>

      {calendar_edit_options.length > 1 && (
        <Button
          className="mt-3"
          color="primary"
          variant="solid"
          fullWidth
          isDisabled={allCompleted}
          isLoading={isConfirmingAll}
          onPress={handleEditAll}
        >
          {allCompleted ? (
            <>
              <Tick02Icon width={22} />
              All Updated
            </>
          ) : hasCompletedEvents ? (
            "Update Remaining"
          ) : (
            "Update All Events"
          )}
        </Button>
      )}
    </div>
  );
}
