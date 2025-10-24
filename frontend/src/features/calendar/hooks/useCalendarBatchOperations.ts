import { useState } from "react";
import { toast } from "sonner";

import { calendarApi } from "@/features/calendar/api/calendarApi";
import {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEvent,
} from "@/types/features/calendarTypes";
import {
  buildBatchAddPayloads,
  buildBatchDeletePayloads,
  buildBatchEditPayloads,
} from "@/utils/calendar/eventPayloadBuilders";
import { getEventKey } from "@/utils/calendar/eventExtractors";
import { AnyCalendarEvent } from "@/utils/calendar/eventTypeGuards";

export type EventStatus = {
  [key: string | number]: "idle" | "loading" | "completed";
};

export const useCalendarBatchOperations = () => {
  const [eventStatuses, setEventStatuses] = useState<EventStatus>({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  const handleBatchAdd = async (
    eventsToAdd: CalendarEvent[],
    allEvents: AnyCalendarEvent[],
  ) => {
    const payloads = buildBatchAddPayloads(eventsToAdd);
    const result = await calendarApi.batchCreateEvents(payloads);

    const completedStatuses: EventStatus = {};

    result.successful.forEach((_, idx) => {
      const originalIndex = allEvents.indexOf(eventsToAdd[idx]);
      completedStatuses[originalIndex] = "completed";
    });

    result.failed.forEach((_, idx) => {
      const originalIndex = allEvents.indexOf(
        eventsToAdd[idx + result.successful.length],
      );
      if (originalIndex !== -1) {
        completedStatuses[originalIndex] = "idle";
      }
    });

    setEventStatuses((prev) => ({ ...prev, ...completedStatuses }));
  };

  const handleBatchEdit = async (eventsToEdit: CalendarEditOptions[]) => {
    const payloads = buildBatchEditPayloads(eventsToEdit);
    const result = await calendarApi.batchUpdateEvents(payloads);

    const completedStatuses: EventStatus = {};

    result.successful.forEach((_, idx) => {
      completedStatuses[eventsToEdit[idx].event_id] = "completed";
    });

    result.failed.forEach((failedItem: { event_id: string }) => {
      completedStatuses[failedItem.event_id] = "idle";
    });

    setEventStatuses((prev) => ({ ...prev, ...completedStatuses }));
  };

  const handleBatchDelete = async (eventsToDelete: CalendarDeleteOptions[]) => {
    const payloads = buildBatchDeletePayloads(eventsToDelete);
    const result = await calendarApi.batchDeleteEvents(payloads);

    const completedStatuses: EventStatus = {};

    result.successful.forEach((item: { event_id: string }) => {
      completedStatuses[item.event_id] = "completed";
    });

    result.failed.forEach((failedItem: { event_id: string }) => {
      completedStatuses[failedItem.event_id] = "idle";
    });

    setEventStatuses((prev) => ({ ...prev, ...completedStatuses }));
  };

  const confirmAll = async (
    actionType: "add" | "edit" | "delete",
    events: AnyCalendarEvent[],
  ) => {
    setIsConfirmingAll(true);

    try {
      const pendingEvents = events.filter((event, index) => {
        const key = getEventKey(event, index);
        return eventStatuses[key] !== "completed";
      });

      if (pendingEvents.length === 0) {
        return;
      }

      const loadingStatuses: EventStatus = {};
      pendingEvents.forEach((event) => {
        const key = getEventKey(event, events.indexOf(event));
        loadingStatuses[key] = "loading";
      });
      setEventStatuses((prev) => ({ ...prev, ...loadingStatuses }));

      if (actionType === "add") {
        await handleBatchAdd(pendingEvents as CalendarEvent[], events);
      } else if (actionType === "edit") {
        await handleBatchEdit(pendingEvents as CalendarEditOptions[]);
      } else {
        await handleBatchDelete(pendingEvents as CalendarDeleteOptions[]);
      }
    } catch (error) {
      console.error("Error in batch operation:", error);
      toast.error(`Failed to ${actionType} all events`);
    } finally {
      setIsConfirmingAll(false);
    }
  };

  return {
    eventStatuses,
    setEventStatuses,
    isConfirmingAll,
    confirmAll,
  };
};
