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
import { formatDateWithRelative } from "@/utils/date/calendarDateUtils";

import { EventCard } from "./CalendarEventCard";

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

  const Icon = actionConfig.icon;

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

                return (
                  <div
                    key={key}
                    className="relative flex items-start gap-2 rounded-lg p-3 pr-2 pl-5 transition-colors"
                    style={{
                      backgroundColor: `${eventColor}20`,
                      opacity: status === "completed" ? 0.5 : 1,
                    }}
                  >
                    <div className="absolute top-0 left-1 flex h-full items-center">
                      <div
                        className="h-[80%] w-1 flex-shrink-0 rounded-full"
                        style={{
                          backgroundColor: eventColor,
                        }}
                      />
                    </div>

                    <div className="min-w-0 flex-1">
                      {actionType === "add" && (
                        <EventCard
                          actionType="add"
                          event={event as CalendarEvent}
                        />
                      )}
                      {actionType === "edit" && (
                        <EventCard
                          actionType="edit"
                          event={event as CalendarEditOptions}
                        />
                      )}
                      {actionType === "delete" && (
                        <EventCard
                          actionType="delete"
                          event={event as CalendarDeleteOptions}
                        />
                      )}
                    </div>

                    <Button
                      color={actionConfig.buttonColor}
                      size="sm"
                      isDisabled={status === "completed"}
                      isLoading={status === "loading"}
                      onPress={() => handleAction(event, key)}
                    >
                      {status === "loading" ? (
                        "Confirm"
                      ) : status === "completed" ? (
                        <>
                          <Tick02Icon width={18} color={undefined} />
                          {actionConfig.completedLabel}
                        </>
                      ) : (
                        <>
                          <Icon width={18} color={undefined} />
                          Confirm
                        </>
                      )}
                    </Button>
                  </div>
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
