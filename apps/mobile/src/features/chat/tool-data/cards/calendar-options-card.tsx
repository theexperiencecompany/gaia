import { Button } from "heroui-native";
import { useState } from "react";
import { ScrollView, View } from "react-native";
import { AppIcon, Calendar03Icon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

export interface CalendarOptionAttendee {
  email?: string;
  displayName?: string;
}

export interface SameDayEvent {
  id?: string;
  summary?: string;
  start?: { date?: string; dateTime?: string };
  end?: { date?: string; dateTime?: string };
  description?: string;
  location?: string;
  background_color?: string;
  calendarTitle?: string;
}

export interface CalendarOption {
  summary?: string;
  title?: string;
  description?: string;
  start?: string;
  end?: string;
  is_all_day?: boolean;
  location?: string;
  attendees?: Array<CalendarOptionAttendee | string>;
  background_color?: string;
  calendar_id?: string;
  calendar_name?: string;
  same_day_events?: SameDayEvent[];
}

type EventStatus = "idle" | "loading" | "completed";

interface CalendarOptionsCardProps {
  data: CalendarOption[];
  onAdd?: (event: CalendarOption, index: number) => Promise<void>;
  onAddAll?: (events: CalendarOption[]) => Promise<void>;
}

// -- Date formatting ----------------------------------------------------------

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

function formatTimeRange(startTime: string, endTime: string): string {
  const start = new Date(startTime);
  const end = new Date(endTime);

  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return startTime;
  }

  const formatTimeString = (date: Date): string => {
    const hours = date.getHours();
    const minutes = date.getMinutes();
    const ampm = hours >= 12 ? "PM" : "AM";
    const hour12 = hours % 12 || 12;
    const minuteStr = minutes.toString().padStart(2, "0");
    if (minutes === 0) return `${hour12} ${ampm}`;
    return `${hour12}:${minuteStr} ${ampm}`;
  };

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

function formatSingleTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

// -- Event-time helpers -------------------------------------------------------

function getOptionDisplayTime(option: CalendarOption): string {
  if (option.start && option.end) {
    if (option.start.includes("T") && option.end.includes("T")) {
      return formatTimeRange(option.start, option.end);
    }
    return option.is_all_day ? "All day" : option.start;
  }
  if (option.start) {
    if (option.start.includes("T")) return formatSingleTime(option.start);
    return "All day";
  }
  return "Time TBD";
}

function getSameDayDisplayTime(event: SameDayEvent): string {
  const startDt = event.start?.dateTime;
  const endDt = event.end?.dateTime;
  if (startDt && endDt) return formatTimeRange(startDt, endDt);
  if (event.start?.date) return "All day";
  return "No time";
}

function getOptionSortKey(option: CalendarOption): number {
  const raw = option.start;
  if (!raw) return 0;
  const t = new Date(raw).getTime();
  return Number.isNaN(t) ? 0 : t;
}

function getSameDaySortKey(event: SameDayEvent): number {
  const raw = event.start?.dateTime ?? event.start?.date;
  if (!raw) return 0;
  const t = new Date(raw).getTime();
  return Number.isNaN(t) ? 0 : t;
}

function bucketDate(input: string): string {
  const t = new Date(input);
  if (Number.isNaN(t.getTime())) return new Date().toISOString().slice(0, 10);
  return t.toISOString().slice(0, 10);
}

// -- Grouping -----------------------------------------------------------------

interface GroupedEntry {
  type: "option" | "sameDay";
  option?: CalendarOption;
  optionIndex?: number;
  sameDay?: SameDayEvent;
  sortKey: number;
}

function groupEventsByDate(
  options: CalendarOption[],
  sameDayEvents: SameDayEvent[],
): Record<string, GroupedEntry[]> {
  const grouped: Record<string, GroupedEntry[]> = {};

  for (const event of sameDayEvents) {
    const raw =
      event.start?.dateTime ?? event.start?.date ?? new Date().toISOString();
    const dateKey = bucketDate(raw);
    if (!grouped[dateKey]) grouped[dateKey] = [];
    grouped[dateKey].push({
      type: "sameDay",
      sameDay: event,
      sortKey: getSameDaySortKey(event),
    });
  }

  options.forEach((option, index) => {
    const raw = option.start ?? new Date().toISOString();
    const dateKey = bucketDate(raw);
    if (!grouped[dateKey]) grouped[dateKey] = [];
    grouped[dateKey].push({
      type: "option",
      option,
      optionIndex: index,
      sortKey: getOptionSortKey(option),
    });
  });

  for (const day of Object.values(grouped)) {
    day.sort((a, b) => a.sortKey - b.sortKey);
  }

  return grouped;
}

// -- Same-day event row -------------------------------------------------------

function SameDayRow({ event }: { event: SameDayEvent }) {
  const eventColor = event.background_color ?? "#00bbff";
  const timeStr = getSameDayDisplayTime(event);

  return (
    <View
      className="relative flex-row items-start gap-2 rounded-lg p-3 pl-5"
      style={{ backgroundColor: `${eventColor}20` }}
    >
      <View className="absolute top-0 bottom-0 left-1 items-center justify-center">
        <View
          className="w-1 rounded-full"
          style={{ height: "80%", backgroundColor: eventColor }}
        />
      </View>
      <View className="flex-1 min-w-0">
        <Text className="text-base text-foreground" numberOfLines={1}>
          {event.summary ?? "Untitled Event"}
        </Text>
        <View className="mt-1 flex-row items-center gap-2">
          <Text className="text-xs text-muted">{timeStr}</Text>
          {event.calendarTitle ? (
            <>
              <View
                style={{
                  width: 3,
                  height: 3,
                  borderRadius: 1.5,
                  backgroundColor: "#71717a",
                }}
              />
              <Text className="text-xs text-muted" numberOfLines={1}>
                {event.calendarTitle}
              </Text>
            </>
          ) : null}
        </View>
      </View>
    </View>
  );
}

// -- Option (new event) row ---------------------------------------------------

interface OptionRowProps {
  option: CalendarOption;
  status: EventStatus;
  onAdd: () => void;
}

function OptionRow({ option, status, onAdd }: OptionRowProps) {
  const eventColor = option.background_color ?? "#00bbff";
  const summary = option.summary ?? option.title ?? "Untitled Event";
  const description = option.description;
  const timeStr = getOptionDisplayTime(option);
  const isCompleted = status === "completed";
  const isLoading = status === "loading";

  return (
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

      {/* Info */}
      <View className="flex-1 min-w-0">
        <Text className="text-base text-foreground" numberOfLines={2}>
          {summary}
        </Text>
        {description ? (
          <Text className="mt-1 text-xs text-muted" numberOfLines={2}>
            {description}
          </Text>
        ) : null}
        <View className="mt-1 flex-row items-center gap-2">
          <Text className="text-xs text-muted">{timeStr}</Text>
        </View>
      </View>

      {/* Action button */}
      <Button
        size="sm"
        variant={isCompleted ? "secondary" : "primary"}
        isDisabled={isCompleted || isLoading}
        onPress={onAdd}
        className="flex-shrink-0 rounded-xl"
      >
        {isCompleted ? (
          <>
            <AppIcon icon={Tick02Icon} size={14} color="#22c55e" />
            <Button.Label>Added</Button.Label>
          </>
        ) : (
          <Button.Label>{isLoading ? "Adding…" : "Confirm"}</Button.Label>
        )}
      </Button>
    </View>
  );
}

// -- Calendar options card ----------------------------------------------------

const MAX_VISIBLE_HEIGHT = 400;

export function CalendarOptionsCard({
  data,
  onAdd,
  onAddAll,
}: CalendarOptionsCardProps) {
  const [statuses, setStatuses] = useState<Record<number, EventStatus>>({});
  const [isAddingAll, setIsAddingAll] = useState(false);

  const sameDayEvents = data[0]?.same_day_events ?? [];
  const validOptions = data.every(
    (option) => (option.summary ?? option.title) !== undefined,
  );

  if (!validOptions) {
    return (
      <View className="mx-4 my-2 w-full max-w-md rounded-3xl bg-zinc-800 p-4">
        <Text className="text-sm text-red-500">
          Error: Could not add Calendar event. Please try again later.
        </Text>
      </View>
    );
  }

  const eventsByDate = groupEventsByDate(data, sameDayEvents);
  const allCompleted = data.every((_, idx) => statuses[idx] === "completed");
  const someCompleted = data.some((_, idx) => statuses[idx] === "completed");

  const handleAdd = async (
    option: CalendarOption,
    index: number,
  ): Promise<void> => {
    if (!onAdd) return;
    setStatuses((prev) => ({ ...prev, [index]: "loading" }));
    try {
      await onAdd(option, index);
      setStatuses((prev) => ({ ...prev, [index]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [index]: "idle" }));
    }
  };

  const handleAddAll = async (): Promise<void> => {
    if (!onAddAll) return;
    setIsAddingAll(true);
    try {
      const pending = data.filter((_, idx) => statuses[idx] !== "completed");
      await onAddAll(pending);
      const next: Record<number, EventStatus> = { ...statuses };
      data.forEach((_, idx) => {
        next[idx] = "completed";
      });
      setStatuses(next);
    } catch {
      // no-op
    } finally {
      setIsAddingAll(false);
    }
  };

  return (
    <View className="mx-4 my-2 w-full max-w-md rounded-3xl bg-zinc-800 p-4">
      <ScrollView
        style={{ maxHeight: MAX_VISIBLE_HEIGHT }}
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
      >
        <View className="gap-3">
          {Object.entries(eventsByDate).map(([dateKey, entries]) => (
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
                {entries.map((entry, idx) => {
                  if (entry.type === "sameDay" && entry.sameDay) {
                    return (
                      <SameDayRow
                        key={`same-${entry.sameDay.id ?? idx}`}
                        event={entry.sameDay}
                      />
                    );
                  }
                  if (
                    entry.type === "option" &&
                    entry.option &&
                    entry.optionIndex !== undefined
                  ) {
                    const status = statuses[entry.optionIndex] ?? "idle";
                    return (
                      <OptionRow
                        key={`opt-${entry.optionIndex}`}
                        option={entry.option}
                        status={status}
                        onAdd={() =>
                          void handleAdd(entry.option!, entry.optionIndex!)
                        }
                      />
                    );
                  }
                  return null;
                })}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>

      {/* Bulk add footer */}
      {data.length > 1 ? (
        <Button
          variant={allCompleted ? "secondary" : "primary"}
          isDisabled={allCompleted || isAddingAll}
          onPress={() => void handleAddAll()}
          className="mt-3 w-full rounded-xl"
        >
          {allCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={16} color="#22c55e" />
              <Button.Label>All Added</Button.Label>
            </>
          ) : (
            <>
              <AppIcon icon={Calendar03Icon} size={16} color="#ffffff" />
              <Button.Label>
                {someCompleted ? "Add Remaining" : "Add All Events"}
              </Button.Label>
            </>
          )}
        </Button>
      ) : null}
    </View>
  );
}
