import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
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

// -- Date / time helpers ------------------------------------------------------

function formatTimeString(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? "PM" : "AM";
  const hour12 = hours % 12 || 12;
  if (minutes === 0) return `${hour12} ${ampm}`;
  return `${hour12}:${minutes.toString().padStart(2, "0")} ${ampm}`;
}

function formatTimeRange(startTime: string, endTime: string): string {
  const start = new Date(startTime);
  const end = new Date(endTime);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "All day";
  }
  return `${formatTimeString(start)} – ${formatTimeString(end)}`;
}

function formatDateWithRelative(dateString: string): string {
  const date = new Date(`${dateString}T12:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const dayMs = 86_400_000;
  const diff = target.getTime() - today.getTime();
  const full = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
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

function bucketDate(input: string): string {
  const t = new Date(input);
  if (Number.isNaN(t.getTime())) return new Date().toISOString().slice(0, 10);
  return t.toISOString().slice(0, 10);
}

function groupByDate(
  events: CalendarDeleteOption[],
): Record<string, CalendarDeleteOption[]> {
  const groups: Record<string, CalendarDeleteOption[]> = {};
  for (const event of events) {
    const raw =
      event.start?.dateTime || event.start?.date || new Date().toISOString();
    const dateKey = bucketDate(raw);
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(event);
  }
  return groups;
}

// -- Event card (action variant) ---------------------------------------------

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
      className="relative flex-row items-end gap-2 rounded-lg p-3 pr-2 pl-5"
      style={{
        backgroundColor: `${eventColor}20`,
        opacity: isCompleted ? 0.5 : 1,
      }}
    >
      {/* Vertical color bar */}
      <View className="absolute left-1 top-0 bottom-0 items-center justify-center">
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

      {/* Action button — HeroUI `color="danger" size="sm"` equivalent */}
      <Pressable
        onPress={isCompleted || isLoading ? undefined : onDelete}
        disabled={isCompleted || isLoading}
        className="flex-shrink-0 rounded-xl px-3 py-1.5 items-center justify-center flex-row gap-1"
        style={{
          backgroundColor: isCompleted ? "#3f3f46" : "#ef4444",
          opacity: isCompleted ? 0.6 : 1,
        }}
      >
        {isLoading ? (
          <ActivityIndicator size="small" color="#ffffff" />
        ) : isCompleted ? (
          <>
            <AppIcon icon={Tick02Icon} size={14} color="#a1a1aa" />
            <Text className="text-xs font-semibold text-zinc-300">Deleted</Text>
          </>
        ) : (
          <Text className="text-xs font-semibold text-white">Confirm</Text>
        )}
      </Pressable>
    </View>
  );
}

// -- Calendar delete card -----------------------------------------------------

const MAX_VISIBLE_HEIGHT = 400;

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
        style={{ maxHeight: MAX_VISIBLE_HEIGHT }}
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
      >
        <View className="gap-3">
          {Object.entries(eventsByDate).map(([dateKey, events]) => (
            <View key={dateKey} className="gap-3">
              {/* Date rail */}
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
        </View>
      </ScrollView>

      {/* Bulk delete footer — full-width solid danger button */}
      {data.length > 1 ? (
        <Pressable
          onPress={
            allCompleted || isConfirmingAll
              ? undefined
              : () => void handleDeleteAll()
          }
          disabled={allCompleted || isConfirmingAll}
          className="mt-3 w-full rounded-xl py-2.5 items-center justify-center flex-row gap-2"
          style={{
            backgroundColor: allCompleted ? "#3f3f46" : "#ef4444",
            opacity: allCompleted ? 0.6 : 1,
          }}
        >
          {isConfirmingAll ? (
            <ActivityIndicator size="small" color="#ffffff" />
          ) : allCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={18} color="#a1a1aa" />
              <Text className="text-sm font-semibold text-zinc-300">
                All Deleted
              </Text>
            </>
          ) : (
            <Text className="text-sm font-semibold text-white">
              {someCompleted ? "Delete Remaining" : "Delete All Events"}
            </Text>
          )}
        </Pressable>
      ) : null}
    </View>
  );
}
