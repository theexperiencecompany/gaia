import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardHeader, ToolCardShell } from "../primitives";

// -- Types --------------------------------------------------------------------

export interface CalendarDeleteOption {
  event_id?: string;
  title?: string;
  summary?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
  background_color?: string;
  calendar_name?: string;
  description?: string;
  is_all_day?: boolean;
}

type EventStatus = "idle" | "loading" | "completed";

interface CalendarDeleteCardProps {
  data: CalendarDeleteOption[];
  onDelete?: (event: CalendarDeleteOption) => Promise<void>;
  onDeleteAll?: (events: CalendarDeleteOption[]) => Promise<void>;
}

// -- Constants ----------------------------------------------------------------

const DANGER_COLOR = "#ef4444";
const DEFAULT_EVENT_COLOR = "#00bbff";

// -- Helpers ------------------------------------------------------------------

function formatTimeRange(
  start?: { dateTime?: string; date?: string },
  end?: { dateTime?: string; date?: string },
): string {
  if (!start) return "";
  const startRaw = start.dateTime || start.date;
  if (!startRaw) return "";
  const startDate = new Date(startRaw);
  if (Number.isNaN(startDate.getTime())) return startRaw;

  // All-day event
  if (start.date && !start.dateTime) return "All day";

  const startTime = startDate.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  const endRaw = end?.dateTime || end?.date;
  if (!endRaw) return startTime;
  const endDate = new Date(endRaw);
  if (Number.isNaN(endDate.getTime())) return startTime;

  const endTime = endDate.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return `${startTime} – ${endTime}`;
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

function formatDateHeader(dateKey: string): string {
  const date = new Date(`${dateKey}T12:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const diff = target.getTime() - today.getTime();
  const dayMs = 86400000;
  const base = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  if (diff === 0) return `${base} (Today)`;
  if (diff === dayMs) return `${base} (Tomorrow)`;
  if (diff === -dayMs) return `${base} (Yesterday)`;
  return base;
}

// -- Event row ----------------------------------------------------------------

interface EventRowProps {
  event: CalendarDeleteOption;
  status: EventStatus;
  onDelete: () => void;
}

function EventRow({ event, status, onDelete }: EventRowProps) {
  const eventColor = event.background_color || DEFAULT_EVENT_COLOR;
  const isCompleted = status === "completed";
  const isLoading = status === "loading";
  const isDisabled = isCompleted || isLoading;

  const summary = event.title || event.summary;
  const timeDisplay = formatTimeRange(event.start, event.end);

  return (
    <View
      className="relative flex-row items-end gap-2 rounded-2xl p-3 pr-2 pl-5"
      style={{
        backgroundColor: `${eventColor}20`,
        opacity: isCompleted ? 0.5 : 1,
      }}
    >
      {/* Left color bar */}
      <View
        className="absolute left-1 top-0 h-full items-center justify-center"
      >
        <View
          className="w-1 rounded-full"
          style={{ height: "80%", backgroundColor: eventColor }}
        />
      </View>

      {/* Event content */}
      <View className="flex-1 min-w-0">
        <Text className="text-base leading-tight text-white">
          {summary ?? "Untitled Event"}
        </Text>
        {event.description ? (
          <Text className="mt-1 text-xs text-zinc-400">{event.description}</Text>
        ) : null}
        <View className="mt-1">
          <Text className="text-xs text-zinc-400">{timeDisplay}</Text>
        </View>
      </View>

      {/* Action button */}
      <Pressable
        onPress={isDisabled ? undefined : onDelete}
        disabled={isDisabled}
        className="rounded-xl px-3 py-2 flex-row items-center gap-1.5"
        style={{
          backgroundColor: isCompleted
            ? "rgba(255,255,255,0.08)"
            : DANGER_COLOR,
          opacity: isDisabled && !isCompleted ? 0.7 : 1,
        }}
      >
        {isLoading ? (
          <ActivityIndicator size="small" color="#ffffff" />
        ) : isCompleted ? (
          <>
            <AppIcon icon={Tick02Icon} size={14} color="#ffffff" />
            <Text className="text-xs font-medium text-white">Deleted</Text>
          </>
        ) : (
          <Text className="text-xs font-medium text-white">Confirm</Text>
        )}
      </Pressable>
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
  const [isDeletingAll, setIsDeletingAll] = useState(false);

  if (!data?.length) return null;

  const getKey = (event: CalendarDeleteOption, index: number): string =>
    event.event_id ?? `delete-${index}`;

  const handleDelete = async (
    event: CalendarDeleteOption,
    key: string,
  ): Promise<void> => {
    if (!onDelete) return;
    setStatuses((prev) => ({ ...prev, [key]: "loading" }));
    try {
      await onDelete(event);
      setStatuses((prev) => ({ ...prev, [key]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [key]: "idle" }));
    }
  };

  const handleDeleteAll = async (): Promise<void> => {
    if (!onDeleteAll) return;
    setIsDeletingAll(true);
    const pending = data.filter((ev, i) => {
      const key = getKey(ev, i);
      return statuses[key] !== "completed";
    });
    try {
      await onDeleteAll(pending);
      const next: Record<string, EventStatus> = {};
      data.forEach((ev, i) => {
        next[getKey(ev, i)] = "completed";
      });
      setStatuses(next);
    } catch {
      // no-op: individual errors are handled by the caller
    } finally {
      setIsDeletingAll(false);
    }
  };

  const allCompleted = data.every(
    (ev, i) => statuses[getKey(ev, i)] === "completed",
  );
  const someCompleted = data.some(
    (ev, i) => statuses[getKey(ev, i)] === "completed",
  );

  const eventsByDate = groupByDate(data);
  const bulkDisabled = allCompleted || isDeletingAll;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Cancel01Icon}
        iconColor={DANGER_COLOR}
        title={`Event${data.length !== 1 ? "s" : ""} to Delete`}
        count={data.length}
      />

      <ScrollView
        style={{ maxHeight: 400 }}
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
      >
        <View className="gap-3">
          {Object.entries(eventsByDate).map(([dateKey, events]) => (
            <View key={dateKey} className="gap-3">
              {/* Date header with dotted divider lines */}
              <View className="flex-row items-center">
                <View className="flex-1 h-px bg-zinc-700" />
                <Text className="px-3 text-xs text-zinc-500">
                  {formatDateHeader(dateKey)}
                </Text>
                <View className="flex-1 h-px bg-zinc-700" />
              </View>

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
                      onDelete={() => void handleDelete(event, key)}
                    />
                  );
                })}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>

      {/* Bulk delete footer */}
      {data.length > 1 ? (
        <Pressable
          onPress={bulkDisabled ? undefined : () => void handleDeleteAll()}
          disabled={bulkDisabled}
          className="mt-3 rounded-xl py-3 flex-row items-center justify-center gap-2"
          style={{
            backgroundColor: DANGER_COLOR,
            opacity: bulkDisabled ? 0.5 : 1,
          }}
        >
          {isDeletingAll ? (
            <ActivityIndicator size="small" color="#ffffff" />
          ) : allCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={18} color="#ffffff" />
              <Text className="text-sm font-medium text-white">
                All Deleted
              </Text>
            </>
          ) : (
            <Text className="text-sm font-medium text-white">
              {someCompleted ? "Delete Remaining" : "Delete All Events"}
            </Text>
          )}
        </Pressable>
      ) : null}
    </ToolCardShell>
  );
}
