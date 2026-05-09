import { Button } from "heroui-native";
import { useState } from "react";
import { ScrollView, View } from "react-native";
import { AppIcon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

// Local alias — matches CalendarEditOptions from @gaia/shared
export interface CalendarEditOption {
  event_id?: string;
  action?: "edit";
  calendar_id?: string;
  calendar_name?: string;
  background_color?: string;
  original_summary?: string;
  original_description?: string;
  original_start?: { dateTime?: string; date?: string };
  original_end?: { dateTime?: string; date?: string };
  original_query?: string;
  summary?: string;
  description?: string;
  start?: string;
  end?: string;
  is_all_day?: boolean;
  timezone?: string;
}

type EventStatus = "idle" | "loading" | "completed";

interface CalendarEditCardProps {
  data: CalendarEditOption[];
  onEdit?: (event: CalendarEditOption) => Promise<void>;
  onEditAll?: (events: CalendarEditOption[]) => Promise<void>;
}

// -- Date helpers (mirrors web utils/date/calendarDateUtils.ts) --------------

function formatTimeString(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? "PM" : "AM";
  const hour12 = hours % 12 || 12;
  const minuteStr = minutes.toString().padStart(2, "0");
  if (minutes === 0) return `${hour12} ${ampm}`;
  return `${hour12}:${minuteStr} ${ampm}`;
}

function formatTimeRange(startTime: string, endTime: string): string {
  const start = new Date(startTime);
  const end = new Date(endTime);

  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return startTime;
  }

  const startStr = formatTimeString(start);
  const endStr = formatTimeString(end);

  if (start.getHours() < 12 && end.getHours() >= 12) {
    return `${startStr} – ${endStr}`;
  }
  if (start.getHours() >= 12 && end.getHours() >= 12) {
    return `${startStr.replace(" PM", "")} – ${endStr}`;
  }
  if (start.getHours() < 12 && end.getHours() < 12) {
    return `${startStr.replace(" AM", "")} – ${endStr}`;
  }
  return `${startStr} – ${endStr}`;
}

function formatDateWithRelative(dateString: string): string {
  const date = new Date(dateString);
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const compareDate = new Date(date);
  compareDate.setHours(0, 0, 0, 0);

  const fullDate = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  if (compareDate.getTime() === today.getTime()) return `${fullDate} (Today)`;
  if (compareDate.getTime() === tomorrow.getTime())
    return `${fullDate} (Tomorrow)`;
  if (compareDate.getTime() === yesterday.getTime())
    return `${fullDate} (Yesterday)`;
  return fullDate;
}

// -- Edit-event helpers (mirrors web utils/calendar/eventHelpers.ts) ----------

function hasEventChanges(event: CalendarEditOption): boolean {
  return !!(
    (event.summary && event.summary !== event.original_summary) ||
    event.description !== undefined ||
    event.start ||
    event.end ||
    event.is_all_day !== undefined
  );
}

function getUpdatedTimeDisplay(event: CalendarEditOption): string {
  if (event.start && event.end) {
    return formatTimeRange(event.start, event.end);
  }
  if (event.is_all_day) return "All day";
  if (event.original_start?.dateTime && event.original_end?.dateTime) {
    return formatTimeRange(
      event.original_start.dateTime,
      event.original_end.dateTime,
    );
  }
  return "All day";
}

function getOriginalTimeDisplay(event: CalendarEditOption): string {
  if (event.original_start?.dateTime && event.original_end?.dateTime) {
    return formatTimeRange(
      event.original_start.dateTime,
      event.original_end.dateTime,
    );
  }
  return "All day";
}

function groupByDate(
  events: CalendarEditOption[],
): Record<string, CalendarEditOption[]> {
  const groups: Record<string, CalendarEditOption[]> = {};
  for (const event of events) {
    const raw =
      event.original_start?.dateTime ||
      event.original_start?.date ||
      new Date().toISOString();
    const dateKey = new Date(raw).toISOString().slice(0, 10);
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(event);
  }
  return groups;
}

// -- Event row ----------------------------------------------------------------

interface EventRowProps {
  event: CalendarEditOption;
  status: EventStatus;
  onEdit: () => void;
}

function EventRow({ event, status, onEdit }: EventRowProps) {
  const eventColor = event.background_color || "#00bbff";
  const isCompleted = status === "completed";
  const isLoading = status === "loading";
  const showChanges = hasEventChanges(event);
  const updatedSummary = event.summary || event.original_summary;
  const updatedDescription =
    event.description !== undefined
      ? event.description
      : event.original_description;
  const updatedTime = getUpdatedTimeDisplay(event);
  const originalTime = getOriginalTimeDisplay(event);

  return (
    <View className="gap-2">
      {/* Current event (dimmed, dashed border) — only when changes exist and not yet completed */}
      {showChanges && !isCompleted ? (
        <View
          className="relative flex-row items-start gap-2 rounded-lg p-3 pl-5 pr-2 border-2 border-dashed"
          style={{
            backgroundColor: `${eventColor}10`,
            borderColor: `${eventColor}80`,
            opacity: 0.6,
          }}
        >
          <View className="absolute top-0 bottom-0 left-1 items-center justify-center">
            <View
              className="w-1 rounded-full"
              style={{ height: "80%", backgroundColor: eventColor }}
            />
          </View>

          <View className="flex-1 min-w-0">
            <Text className="mb-1 text-xs font-medium text-[#00bbff]">
              Current Event
            </Text>
            <Text className="text-base text-foreground" numberOfLines={2}>
              {event.original_summary}
            </Text>
            {event.original_description ? (
              <Text className="mt-1 text-xs text-muted" numberOfLines={2}>
                {event.original_description}
              </Text>
            ) : null}
            <View className="mt-1 flex-row items-center gap-2">
              <Text className="text-xs text-muted">{originalTime}</Text>
            </View>
          </View>
        </View>
      ) : null}

      {/* Updated event (action row) */}
      <View
        className="relative flex-row items-end gap-2 rounded-lg p-3 pl-5 pr-2"
        style={{
          backgroundColor: `${eventColor}20`,
          opacity: isCompleted ? 0.5 : 1,
        }}
      >
        <View className="absolute top-0 bottom-0 left-1 items-center justify-center">
          <View
            className="w-1 rounded-full"
            style={{ height: "80%", backgroundColor: eventColor }}
          />
        </View>

        <View className="flex-1 min-w-0">
          {showChanges && !isCompleted ? (
            <Text className="mb-1 text-xs font-medium text-zinc-500">
              Updated Event
            </Text>
          ) : null}
          <Text className="text-base text-foreground" numberOfLines={2}>
            {updatedSummary}
          </Text>
          {updatedDescription ? (
            <Text className="mt-1 text-xs text-muted" numberOfLines={2}>
              {updatedDescription}
            </Text>
          ) : null}
          <View className="mt-1 flex-row items-center gap-2">
            <Text className="text-xs text-muted">{updatedTime}</Text>
          </View>
        </View>

        <Button
          size="sm"
          variant={isCompleted ? "secondary" : "primary"}
          isDisabled={isCompleted || isLoading}
          onPress={onEdit}
          className="flex-shrink-0 rounded-xl"
        >
          {isCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={14} color="#22c55e" />
              <Button.Label>Updated</Button.Label>
            </>
          ) : (
            <Button.Label>{isLoading ? "Updating…" : "Confirm"}</Button.Label>
          )}
        </Button>
      </View>
    </View>
  );
}

// -- Calendar edit card -------------------------------------------------------

const MAX_VISIBLE_HEIGHT = 400;

export function CalendarEditCard({
  data,
  onEdit,
  onEditAll,
}: CalendarEditCardProps) {
  const [statuses, setStatuses] = useState<Record<string, EventStatus>>({});
  const [isUpdatingAll, setIsUpdatingAll] = useState(false);

  if (!data?.length) return null;

  const getKey = (event: CalendarEditOption, index: number): string =>
    event.event_id ?? `edit-${index}`;

  const handleEdit = async (
    event: CalendarEditOption,
    key: string,
  ): Promise<void> => {
    if (!onEdit) {
      setStatuses((prev) => ({ ...prev, [key]: "completed" }));
      return;
    }
    setStatuses((prev) => ({ ...prev, [key]: "loading" }));
    try {
      await onEdit(event);
      setStatuses((prev) => ({ ...prev, [key]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [key]: "idle" }));
    }
  };

  const handleEditAll = async (): Promise<void> => {
    setIsUpdatingAll(true);
    const pending = data.filter((ev, i) => {
      const key = getKey(ev, i);
      return statuses[key] !== "completed";
    });
    try {
      if (onEditAll) {
        await onEditAll(pending);
      } else {
        await Promise.all(
          pending.map((ev) => {
            const idx = data.indexOf(ev);
            return handleEdit(ev, getKey(ev, idx));
          }),
        );
      }
      const next: Record<string, EventStatus> = { ...statuses };
      data.forEach((ev, i) => {
        next[getKey(ev, i)] = "completed";
      });
      setStatuses(next);
    } catch {
      // individual errors handled per-row
    } finally {
      setIsUpdatingAll(false);
    }
  };

  const allCompleted = data.every(
    (ev, i) => statuses[getKey(ev, i)] === "completed",
  );
  const someCompleted = data.some(
    (ev, i) => statuses[getKey(ev, i)] === "completed",
  );

  const eventsByDate = groupByDate(data);

  return (
    <View className="mx-4 my-2 w-full max-w-md rounded-3xl bg-zinc-800 p-4">
      <ScrollView
        style={{ maxHeight: MAX_VISIBLE_HEIGHT }}
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
      >
        <View className="gap-3">
          {Object.entries(eventsByDate).map(([dateKey, events]) => (
            <View key={dateKey} className="gap-3">
              {/* Date divider */}
              <View className="flex-row items-center">
                <View className="flex-1 h-px bg-zinc-700" />
                <Text className="px-3 text-xs text-zinc-500">
                  {formatDateWithRelative(dateKey)}
                </Text>
                <View className="flex-1 h-px bg-zinc-700" />
              </View>

              {/* Events */}
              <View className="gap-2">
                {events.map((event) => {
                  const globalIdx = data.indexOf(event);
                  const key = getKey(event, globalIdx);
                  const status = statuses[key] ?? "idle";
                  return (
                    <EventRow
                      key={key}
                      event={event}
                      status={status}
                      onEdit={() => void handleEdit(event, key)}
                    />
                  );
                })}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>

      {/* Bulk update footer */}
      {data.length > 1 ? (
        <Button
          variant={allCompleted ? "secondary" : "primary"}
          isDisabled={allCompleted || isUpdatingAll}
          onPress={() => void handleEditAll()}
          className="mt-3 w-full rounded-xl"
        >
          {allCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={16} color="#22c55e" />
              <Button.Label>All Updated</Button.Label>
            </>
          ) : (
            <Button.Label>
              {someCompleted ? "Update Remaining" : "Update All Events"}
            </Button.Label>
          )}
        </Button>
      ) : null}
    </View>
  );
}
