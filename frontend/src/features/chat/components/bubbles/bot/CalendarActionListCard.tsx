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
import { AnyCalendarEvent } from "@/utils/calendar/eventTypeGuards";
import {
  formatDateWithRelative,
  formatTimeRange,
} from "@/utils/date/calendarDateUtils";

import { EventCard } from "./CalendarEventCard";
import { EventActionCard } from "./EventActionCard";
import { EventDisplayCard } from "./EventDisplayCard";

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

    return configs[actionType];
  }, [actionType]);

  const eventsByDay = useMemo(
    () => groupEventsByDate(events as AnyCalendarEvent[]),
    [events],
  );

  const handleAction = async (
    event: AnyCalendarEvent,
    key: string | number,
  ) => {
    try {
      setEventStatuses((prev) => ({ ...prev, [key]: "loading" as const }));

      if (actionType === "add") {
        await handleAddEvent(event as CalendarEvent, key as number);
      } else if (actionType === "edit") {
        await calendarApi.updateEventByAgent(
          buildEditEventPayload(event as CalendarEditOptions),
        );
      } else {
        await calendarApi.deleteEventByAgent(
          buildDeleteEventPayload(event as CalendarDeleteOptions),
        );
      }

      setEventStatuses((prev) => ({ ...prev, [key]: "completed" as const }));
    } catch (error) {
      console.error(`Error performing ${actionType} action:`, error);
      setEventStatuses((prev) => ({ ...prev, [key]: "idle" as const }));
      toast.error(`Failed to ${actionType} event`);
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
    <div className="w-full max-w-md rounded-3xl bg-zinc-800 p-4 text-white">
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
                const eventColor =
                  ("background_color" in event
                    ? event.background_color
                    : undefined) || "#00bbff";

                if (actionType === "edit") {
                  const editEvent = event as CalendarEditOptions;
                  const hasChanges =
                    editEvent.summary !== undefined ||
                    editEvent.description !== undefined ||
                    editEvent.start !== undefined ||
                    editEvent.end !== undefined ||
                    editEvent.is_all_day !== undefined;

                  return (
                    <div key={key} className="space-y-2">
                      {/* Show old event only when not completed */}
                      {status !== "completed" && (
                        <EventDisplayCard
                          eventColor={eventColor}
                          label="Current Event"
                          opacity={0.6}
                        >
                          <EventCard actionType="edit" event={editEvent} />
                        </EventDisplayCard>
                      )}

                      {hasChanges && (
                        <EventActionCard
                          eventColor={eventColor}
                          status={status}
                          label={
                            status === "completed" ? undefined : "Updated Event"
                          }
                          buttonColor={actionConfig.buttonColor}
                          completedLabel={actionConfig.completedLabel}
                          icon={actionConfig.icon}
                          onAction={() => handleAction(event, key)}
                          isDotted={status !== "completed"}
                        >
                          <div className="text-base leading-tight text-white">
                            {editEvent.summary || editEvent.original_summary}
                          </div>
                          {(editEvent.description !== undefined
                            ? editEvent.description
                            : editEvent.original_description) && (
                            <div className="mt-1 text-xs text-zinc-400">
                              {editEvent.description !== undefined
                                ? editEvent.description
                                : editEvent.original_description}
                            </div>
                          )}
                          <div className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
                            <span>
                              {editEvent.start && editEvent.end
                                ? formatTimeRange(
                                    editEvent.start,
                                    editEvent.end,
                                  )
                                : editEvent.is_all_day !== undefined &&
                                    editEvent.is_all_day
                                  ? "All day"
                                  : editEvent.original_start?.dateTime &&
                                      editEvent.original_end?.dateTime
                                    ? formatTimeRange(
                                        editEvent.original_start.dateTime,
                                        editEvent.original_end.dateTime,
                                      )
                                    : "All day"}
                            </span>
                          </div>
                        </EventActionCard>
                      )}
                    </div>
                  );
                }

                return (
                  <EventActionCard
                    key={key}
                    eventColor={eventColor}
                    status={status}
                    buttonColor={actionConfig.buttonColor}
                    completedLabel={actionConfig.completedLabel}
                    icon={actionConfig.icon}
                    onAction={() => handleAction(event, key)}
                  >
                    {actionType === "add" && (
                      <EventCard
                        actionType="add"
                        event={event as CalendarEvent}
                      />
                    )}
                    {actionType === "delete" && (
                      <EventCard
                        actionType="delete"
                        event={event as CalendarDeleteOptions}
                      />
                    )}
                  </EventActionCard>
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
