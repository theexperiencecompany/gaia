import { Button } from "heroui-native";
import { useState } from "react";
import { ScrollView, View } from "react-native";
import { AppIcon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

export interface CalendarDeleteOption {
  event_id?: string;
  summary?: string;
  description?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
  background_color?: string;
  calendar_id?: string;
  calendar_name?: string;
  action?: "delete";
  original_query?: string;
}

type EventStatus = "idle" | "loading" | "completed";

interface CalendarDeleteCardProps {
  data: CalendarDeleteOption[];
  onDelete?: (event: CalendarDeleteOption) => Promise<void>;
  onDeleteAll?: (events: CalendarDeleteOption[]) => Promise<void>;
}

// -- Helpers ------------------------------------------------------------------

function formatTimeRange(startTime: string, endTime: string): string {
  const start = new Date(startTime);
  const end = new Date(endTime);

  const fmt = (d: Date): string => {
    const hours = d.getHours();
    const minutes = d.getMinutes();
    const ampm = hours >= 12 ? "PM" : "AM";
    const hour12 = hours % 12 || 12;
    const minuteStr = minutes.toString().padStart(2, "0");
    if (minutes === 0) return `${hour12} ${ampm}`;
    return `${hour12}:${minuteStr} ${ampm}`;
  };

  const startStr = fmt(start);
  const endStr = fmt(end);

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
  const date = new Date(`${dateString}T12:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const target = new Date(date);
  target.setHours(0, 0, 0, 0);

  const full = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  const dayMs = 86_400_000;
  const diff = target.getTime() - today.getTime();
  if (diff === 0) return `${full} (Today)`;
  if (diff === dayMs) return `${full} (Tomorrow)`;
  if (diff === -dayMs) return `${full} (Yesterday)`;
  return full;
}

function getEventTimeDisplay(event: CalendarDeleteOption): string {
  if (event.start?.dateTime && event.end?.dateTime) {
    return formatTimeRange(event.start.dateTime, event.end.dateTime);
  }
  return "All day";
}

function groupByDate(
  events: CalendarDeleteOption[],
): Record<string, CalendarDeleteOption[]> {
  const groups: Record<string, CalendarDeleteOption[]> = {};
  for (const event of events) {
    const raw =
      event.start?.dateTime || event.start?.date || new Date().toISOString();
    const dateKey = new Date(raw).toISOString().slice(0, 10);
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(event);
  }
  return groups;
}

// -- Event card ---------------------------------------------------------------

interface EventCardProps {
  event: CalendarDeleteOption;
  status: EventStatus;
  onDelete: () => void;
}

function EventCard({ event, status, onDelete }: EventCardProps) {
  const eventColor = event.background_color || "#00bbff";
  const isCompleted = status === "completed";
  const isLoading = status === "loading";
  const timeDisplay = getEventTimeDisplay(event);

  return (
    <View
      className="relative flex-row items-end gap-2 rounded-lg py-3 pr-2 pl-5"
      style={{
        backgroundColor: `${eventColor}20`,
        opacity: isCompleted ? 0.5 : 1,
      }}
    >
      {/* Vertical color bar */}
      <View
        className="absolute left-1 top-0 bottom-0 items-center justify-center"
        pointerEvents="none"
      >
        <View
          className="w-1 rounded-full"
          style={{ backgroundColor: eventColor, height: "80%" }}
        />
      </View>

      {/* Content */}
      <View className="flex-1 min-w-0">
        <Text className="text-base leading-tight text-white" numberOfLines={2}>
          {event.summary}
        </Text>
        {event.description ? (
          <Text className="mt-1 text-xs text-zinc-400" numberOfLines={3}>
            {event.description}
          </Text>
        ) : null}
        <View className="mt-1 flex-row items-center gap-2">
          <Text className="text-xs text-zinc-400">{timeDisplay}</Text>
        </View>
      </View>

      {/* Action button */}
      <Button
        size="sm"
        variant={isCompleted ? "secondary" : "danger"}
        isDisabled={isCompleted || isLoading}
        onPress={onDelete}
        className="flex-shrink-0"
      >
        {isCompleted ? (
          <>
            <AppIcon icon={Tick02Icon} size={16} color="#fff" />
            <Button.Label>Deleted</Button.Label>
          </>
        ) : (
          <Button.Label>Confirm</Button.Label>
        )}
      </Button>
    </View>
  );
}

// -- Calendar delete card -----------------------------------------------------

export function CalendarDeleteCard({
  data,
  onDelete,
  onDeleteAll,
}: CalendarDeleteCardProps) {
  const [statuses, setStatuses] = useState<Record<string, EventStatus>>({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  if (!data?.length) return null;

  const getKey = (event: CalendarDeleteOption, index: number): string =>
    event.event_id ?? `delete-${index}`;

  const handleDelete = async (
    event: CalendarDeleteOption,
    key: string,
  ): Promise<void> => {
    if (!onDelete) {
      setStatuses((prev) => ({ ...prev, [key]: "completed" }));
      return;
    }
    setStatuses((prev) => ({ ...prev, [key]: "loading" }));
    try {
      await onDelete(event);
      setStatuses((prev) => ({ ...prev, [key]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [key]: "idle" }));
    }
  };

  const handleDeleteAll = async (): Promise<void> => {
    setIsConfirmingAll(true);
    const pending = data.filter((ev, i) => {
      const key = getKey(ev, i);
      return statuses[key] !== "completed";
    });
    try {
      if (onDeleteAll) {
        await onDeleteAll(pending);
      } else {
        await Promise.all(
          pending.map((ev) => {
            const idx = data.indexOf(ev);
            return handleDelete(ev, getKey(ev, idx));
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
      setIsConfirmingAll(false);
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
    <View className="mx-4 my-1 w-full max-w-md rounded-3xl bg-zinc-800 p-4">
      <ScrollView
        style={{ maxHeight: 400 }}
        className="mt-2"
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
      >
        {Object.entries(eventsByDate).map(([dateKey, events], groupIdx) => (
          <View
            key={dateKey}
            className="gap-3"
            style={{ marginTop: groupIdx === 0 ? 0 : 12 }}
          >
            {/* Date separator */}
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
                  <EventCard
                    key={key}
                    event={event}
                    status={status}
                    onDelete={() => void handleDelete(event, key)}
                  />
                );
              })}
            </View>
          </View>
        ))}
      </ScrollView>

      {data.length > 1 ? (
        <Button
          variant="danger"
          isDisabled={allCompleted || isConfirmingAll}
          onPress={() => void handleDeleteAll()}
          className="mt-3 w-full"
        >
          {allCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={18} color="#fff" />
              <Button.Label>All Deleted</Button.Label>
            </>
          ) : (
            <Button.Label>
              {someCompleted ? "Delete Remaining" : "Delete All Events"}
            </Button.Label>
          )}
        </Button>
      ) : null}
    </View>
  );
}
