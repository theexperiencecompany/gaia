import { Button } from "heroui-native";
import { useMemo, useState } from "react";
import { ActivityIndicator, ScrollView, View } from "react-native";
import { AppIcon, Calendar03Icon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

// Matches `CalendarOptions` from @gaia/shared, the shape emitted by the backend
// for the `calendar_options` tool. The local alias is kept so renderers.tsx
// continues to compile against `CalendarOption[]`.
export interface CalendarOption {
  summary: string;
  description?: string;
  start?: string;
  end?: string;
  calendar_id?: string;
  calendar_name?: string;
  background_color?: string;
  is_all_day?: boolean;
  attendees?: string[];
  create_meeting_room?: boolean;
}

interface CalendarOptionsCardProps {
  data: CalendarOption[];
  onConfirm?: (event: CalendarOption, index: number) => Promise<void>;
  onConfirmAll?: (events: CalendarOption[]) => Promise<void>;
}

type EventStatus = "idle" | "loading" | "completed";

// -- Helpers ------------------------------------------------------------------

const DEFAULT_COLOR = "#00bbff";

function formatTimeString(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? "PM" : "AM";
  const hour12 = hours % 12 || 12;
  if (minutes === 0) return `${hour12} ${ampm}`;
  return `${hour12}:${minutes.toString().padStart(2, "0")} ${ampm}`;
}

function formatTimeRange(startISO?: string, endISO?: string): string {
  if (!startISO) return "All day";
  if (!startISO.includes("T")) return "All day";
  const start = new Date(startISO);
  if (Number.isNaN(start.getTime())) return "All day";
  if (!endISO || !endISO.includes("T")) return formatTimeString(start);
  const end = new Date(endISO);
  if (Number.isNaN(end.getTime())) return formatTimeString(start);
  return `${formatTimeString(start)} – ${formatTimeString(end)}`;
}

function formatDateWithRelative(dateKey: string): string {
  const date = new Date(`${dateKey}T12:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const dayMs = 86_400_000;
  const diff = target.getTime() - today.getTime();
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

function groupByDate(events: CalendarOption[]): Array<{
  dateKey: string;
  events: Array<{ event: CalendarOption; index: number }>;
}> {
  const grouped: Record<
    string,
    Array<{ event: CalendarOption; index: number }>
  > = {};
  events.forEach((event, index) => {
    const raw = event.start ?? new Date().toISOString();
    const date = new Date(raw);
    const key = Number.isNaN(date.getTime())
      ? new Date().toISOString().slice(0, 10)
      : date.toISOString().slice(0, 10);
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push({ event, index });
  });

  // Sort events within each day by start time
  Object.values(grouped).forEach((items) => {
    items.sort((a, b) => {
      const aTime = a.event.start ? new Date(a.event.start).getTime() : 0;
      const bTime = b.event.start ? new Date(b.event.start).getTime() : 0;
      return aTime - bTime;
    });
  });

  return Object.entries(grouped).map(([dateKey, items]) => ({
    dateKey,
    events: items,
  }));
}

// -- Event row ----------------------------------------------------------------

interface EventRowProps {
  event: CalendarOption;
  status: EventStatus;
  onConfirm?: () => void;
}

function EventRow({ event, status, onConfirm }: EventRowProps) {
  const color = event.background_color ?? DEFAULT_COLOR;
  const timeDisplay = formatTimeRange(event.start, event.end);
  const isCompleted = status === "completed";
  const isLoading = status === "loading";

  return (
    <View
      className="relative flex-row items-end rounded-lg py-3 pl-5 pr-2"
      style={{
        backgroundColor: `${color}20`,
        opacity: isCompleted ? 0.5 : 1,
      }}
    >
      {/* Vertical color bar */}
      <View className="absolute left-1 top-0 bottom-0 items-center justify-center">
        <View
          className="w-1 rounded-full"
          style={{ backgroundColor: color, height: "80%" }}
        />
      </View>

      {/* Content */}
      <View className="flex-1 min-w-0">
        <Text
          className="text-zinc-100 text-base leading-tight"
          numberOfLines={2}
        >
          {event.summary}
        </Text>
        {event.description ? (
          <Text className="text-zinc-400 text-xs mt-1" numberOfLines={3}>
            {event.description}
          </Text>
        ) : null}
        <Text className="text-zinc-400 text-xs mt-1">{timeDisplay}</Text>
      </View>

      {/* Action */}
      {onConfirm ? (
        <Button
          size="sm"
          variant={isCompleted ? "secondary" : "primary"}
          isDisabled={isCompleted || isLoading}
          onPress={onConfirm}
          className="flex-shrink-0"
        >
          {isLoading ? (
            <ActivityIndicator size="small" color="#ffffff" />
          ) : isCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={16} color="#ffffff" />
              <Button.Label>Added</Button.Label>
            </>
          ) : (
            <Button.Label>Confirm</Button.Label>
          )}
        </Button>
      ) : null}
    </View>
  );
}

// -- Calendar options card ----------------------------------------------------

export function CalendarOptionsCard({
  data,
  onConfirm,
  onConfirmAll,
}: CalendarOptionsCardProps) {
  const [statuses, setStatuses] = useState<Record<number, EventStatus>>({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  const eventsByDate = useMemo(() => groupByDate(data), [data]);

  if (!data.every((option) => option.summary)) {
    return (
      <ToolCardShell>
        <Text className="text-red-400 text-sm">
          Error: Could not add Calendar event. Please try again later.
        </Text>
      </ToolCardShell>
    );
  }

  const handleConfirm = async (
    event: CalendarOption,
    index: number,
  ): Promise<void> => {
    if (!onConfirm) return;
    setStatuses((prev) => ({ ...prev, [index]: "loading" }));
    try {
      await onConfirm(event, index);
      setStatuses((prev) => ({ ...prev, [index]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [index]: "idle" }));
    }
  };

  const handleConfirmAll = async (): Promise<void> => {
    if (!onConfirmAll) return;
    setIsConfirmingAll(true);
    const pending = data.filter((_, i) => statuses[i] !== "completed");
    try {
      await onConfirmAll(pending);
      const next: Record<number, EventStatus> = {};
      data.forEach((_, i) => {
        next[i] = "completed";
      });
      setStatuses(next);
    } catch {
      // leave existing statuses untouched
    } finally {
      setIsConfirmingAll(false);
    }
  };

  const allCompleted = data.every((_, i) => statuses[i] === "completed");
  const someCompleted = data.some((_, i) => statuses[i] === "completed");

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Calendar03Icon}
        title="Add to Calendar"
        count={data.length}
      />

      <ScrollView
        style={{ maxHeight: 400 }}
        nestedScrollEnabled
        showsVerticalScrollIndicator={false}
      >
        <View className="gap-3">
          {eventsByDate.map(({ dateKey, events }) => (
            <View key={dateKey} className="gap-3">
              {/* Date rail */}
              <View className="flex-row items-center">
                <View className="flex-1 h-px bg-zinc-700" />
                <Text className="text-zinc-500 text-xs px-3">
                  {formatDateWithRelative(dateKey)}
                </Text>
                <View className="flex-1 h-px bg-zinc-700" />
              </View>

              {/* Events */}
              <View className="gap-2">
                {events.map(({ event, index }) => (
                  <EventRow
                    key={`${dateKey}-${index}`}
                    event={event}
                    status={statuses[index] ?? "idle"}
                    onConfirm={
                      onConfirm
                        ? () => void handleConfirm(event, index)
                        : undefined
                    }
                  />
                ))}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>

      {data.length > 1 && onConfirmAll ? (
        <Button
          variant={allCompleted ? "secondary" : "primary"}
          isDisabled={allCompleted || isConfirmingAll}
          onPress={() => void handleConfirmAll()}
          className="w-full mt-3"
        >
          {isConfirmingAll ? (
            <ActivityIndicator size="small" color="#ffffff" />
          ) : allCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={16} color="#ffffff" />
              <Button.Label>All Added</Button.Label>
            </>
          ) : (
            <Button.Label>
              {someCompleted ? "Add Remaining" : "Add All Events"}
            </Button.Label>
          )}
        </Button>
      ) : null}
    </ToolCardShell>
  );
}
