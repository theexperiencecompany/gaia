import { Button } from "@heroui/button";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { useMemo } from "react";
import { toast } from "sonner";

import {
  CalendarAdd01Icon,
  Cancel01Icon,
  PencilEdit02Icon,
  Tick02Icon,
} from "@/components/shared/icons";
import { calendarApi } from "@/features/calendar/api/calendarApi";
import { useCalendarBatchOperations } from "@/features/calendar/hooks/useCalendarBatchOperations";
import {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEvent,
} from "@/types/features/calendarTypes";
import {
  buildAddEventPayload,
  buildDeleteEventPayload,
  buildEditEventPayload,
} from "@/utils/calendar/eventPayloadBuilders";
import { groupEventsByDate } from "@/utils/calendar/eventGrouping";
import {
  getEventAction,
  getEventColor,
  hasEventChanges,
} from "@/utils/calendar/eventHelpers";
import { AnyCalendarEvent } from "@/utils/calendar/eventTypeGuards";
import { formatDateWithRelative } from "@/utils/date/calendarDateUtils";

import { EventCard } from "./CalendarEventCard";
import { EventContent } from "./CalendarEventContent";

type ActionType = "add" | "edit" | "delete";

interface BaseProps {
  actionType: ActionType;
}

interface AddProps extends BaseProps {
  actionType: "add";
  events: CalendarEvent[];
  isDummy?: boolean;
  onDummyAddEvent?: (index: number) => void;
}

interface EditProps extends BaseProps {
  actionType: "edit";
  events: CalendarEditOptions[];
}

interface DeleteProps extends BaseProps {
  actionType: "delete";
  events: CalendarDeleteOptions[];
}

type CalendarActionListCardProps = AddProps | EditProps | DeleteProps;

export function CalendarActionListCard(props: CalendarActionListCardProps) {
  const { actionType, events } = props;
  const { eventStatuses, setEventStatuses, isConfirmingAll, confirmAll } =
    useCalendarBatchOperations();

  // Get first event to infer action if not explicitly provided
  const inferredActionType =
    events.length > 0 ? getEventAction(events[0]) : actionType;

  const actionConfig = useMemo(() => {
    const configs = {
      add: {
        buttonColor: "primary" as const,
        completedLabel: "Added",
        confirmAllLabel: "Add All Events",
        confirmRemainingLabel: "Add Remaining",
        allCompletedLabel: "All Added",
        icon: CalendarAdd01Icon,
      },
      edit: {
        buttonColor: "primary" as const,
        completedLabel: "Updated",
        confirmAllLabel: "Update All Events",
        confirmRemainingLabel: "Update Remaining",
        allCompletedLabel: "All Updated",
        icon: PencilEdit02Icon,
      },
      delete: {
        buttonColor: "danger" as const,
        completedLabel: "Deleted",
        confirmAllLabel: "Delete All Events",
        confirmRemainingLabel: "Delete Remaining",
        allCompletedLabel: "All Deleted",
        icon: Cancel01Icon,
      },
    };

    return configs[inferredActionType];
  }, [inferredActionType]);

  const eventsByDay = useMemo(
    () => groupEventsByDate(events as AnyCalendarEvent[]),
    [events],
  );

  const handleAction = async (
    event: AnyCalendarEvent,
    key: string | number,
  ) => {
    const action = getEventAction(event);

    try {
      setEventStatuses((prev) => ({ ...prev, [key]: "loading" as const }));

      if (action === "add") {
        await handleAddEvent(event as CalendarEvent, key as number);
      } else if (action === "edit") {
        await calendarApi.updateEventByAgent(
          buildEditEventPayload(event as CalendarEditOptions),
        );
      } else if (action === "delete") {
        await calendarApi.deleteEventByAgent(
          buildDeleteEventPayload(event as CalendarDeleteOptions),
        );
      }

      setEventStatuses((prev) => ({ ...prev, [key]: "completed" as const }));
    } catch (error) {
      console.error(`Error performing ${action} action:`, error);
      setEventStatuses((prev) => ({ ...prev, [key]: "idle" as const }));
      toast.error(`Failed to ${action} event`);
    }
  };

  const handleAddEvent = async (event: CalendarEvent, index: number) => {
    if ("isDummy" in props && props.isDummy) {
      await new Promise((resolve) => setTimeout(resolve, 300));
      toast.success(`Event '${event.summary}' added!`, {
        description: event.description,
      });
      props.onDummyAddEvent?.(index);
      return;
    }

    await calendarApi.createEventDefault(buildAddEventPayload(event));
  };

  const allCompleted = Object.entries(eventsByDay).every(([_, dayEvents]) =>
    dayEvents.every(({ key }) => eventStatuses[key] === "completed"),
  );

  const hasCompletedEvents = Object.entries(eventsByDay).some(
    ([_, dayEvents]) =>
      dayEvents.some(({ key }) => eventStatuses[key] === "completed"),
  );

  if (!events.length) return null;

  return (
    <div className="w-full max-w-sm rounded-3xl bg-zinc-800 p-4 text-white">
      <ScrollShadow className="max-h-[400px] space-y-3">
        {Object.entries(eventsByDay).map(([dateString, dayEvents]) => (
          <div key={dateString} className="space-y-3">
            <div className="relative flex items-center">
              <div className="flex-1 border-t border-zinc-700" />
              <span className="px-3 text-xs text-zinc-500">
                {formatDateWithRelative(dateString)}
              </span>
              <div className="flex-1 border-t border-zinc-700" />
            </div>
            <div className="space-y-2">
              {dayEvents.map(({ event, key }) => {
                const status = eventStatuses[key] || "idle";
                const action = getEventAction(event);
                const eventColor = getEventColor(event);
                const showChanges = hasEventChanges(event);

                // Edit events show comparison
                if (action === "edit" && showChanges) {
                  return (
                    <div key={key} className="space-y-2">
                      {/* Show old event only when not completed */}
                      {status !== "completed" && (
                        <EventCard
                          eventColor={eventColor}
                          label="Current Event"
                          variant="display"
                          opacity={0.6}
                        >
                          <EventContent event={event} showOriginal />
                        </EventCard>
                      )}

                      {/* Show new event */}
                      <EventCard
                        eventColor={eventColor}
                        status={status}
                        label={
                          status === "completed" ? undefined : "Updated Event"
                        }
                        variant="action"
                        buttonColor={actionConfig.buttonColor}
                        completedLabel={actionConfig.completedLabel}
                        icon={actionConfig.icon}
                        onAction={() => handleAction(event, key)}
                        isDotted={status !== "completed"}
                      >
                        <EventContent event={event} />
                      </EventCard>
                    </div>
                  );
                }

                // Add and delete events show single card
                return (
                  <EventCard
                    key={key}
                    eventColor={eventColor}
                    status={status}
                    variant="action"
                    buttonColor={actionConfig.buttonColor}
                    completedLabel={actionConfig.completedLabel}
                    icon={actionConfig.icon}
                    onAction={() => handleAction(event, key)}
                  >
                    <EventContent event={event} />
                  </EventCard>
                );
              })}
            </div>
          </div>
        ))}
      </ScrollShadow>

      {events.length > 1 && (
        <Button
          className="mt-3"
          color={actionConfig.buttonColor}
          variant="solid"
          fullWidth
          isDisabled={allCompleted}
          isLoading={isConfirmingAll}
          onPress={() => confirmAll(actionType, events as AnyCalendarEvent[])}
        >
          {allCompleted ? (
            <>
              <Tick02Icon width={22} />
              {actionConfig.allCompletedLabel}
            </>
          ) : hasCompletedEvents ? (
            actionConfig.confirmRemainingLabel
          ) : (
            actionConfig.confirmAllLabel
          )}
        </Button>
      )}
    </div>
  );
}
