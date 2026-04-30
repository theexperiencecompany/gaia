import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import { AppIcon, Calendar03Icon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

// Matches the backend `calendar_options` tool output — mirrors the web
// `CalendarOptions` shape from `@/types/features/convoTypes` so the same
// payload renders identically on both platforms.
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
  recurrence?: string[];
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
          className="text-base leading-tight text-zinc-100"
          numberOfLines={2}
        >
          {event.summary}
        </Text>
        {event.description ? (
          <Text className="mt-1 text-xs text-zinc-400" numberOfLines={3}>
            {event.description}
          </Text>
        ) : null}
        <Text className="mt-1 text-xs text-zinc-400">{timeDisplay}</Text>
      </View>

      {/* Action */}
      {onConfirm ? (
        <Pressable
          onPress={isCompleted || isLoading ? undefined : onConfirm}
          className="flex-shrink-0 rounded-lg px-3 py-1.5 items-center justify-center flex-row gap-1"
          style={{
            backgroundColor: isCompleted
              ? "rgba(34,197,94,0.15)"
              : "rgba(0,187,255,0.15)",
            opacity: isCompleted || isLoading ? 0.85 : 1,
          }}
        >
          {isLoading ? (
            <ActivityIndicator size="small" color={DEFAULT_COLOR} />
          ) : isCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={14} color="#22c55e" />
              <Text className="text-xs font-semibold text-[#22c55e]">
                Added
              </Text>
            </>
          ) : (
            <Text className="text-xs font-semibold text-primary">Confirm</Text>
          )}
        </Pressable>
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
    if (!onConfirm) {
      setStatuses((prev) => ({ ...prev, [index]: "completed" }));
      return;
    }
    setStatuses((prev) => ({ ...prev, [index]: "loading" }));
    try {
      await onConfirm(event, index);
      setStatuses((prev) => ({ ...prev, [index]: "completed" }));
    } catch {
      setStatuses((prev) => ({ ...prev, [index]: "idle" }));
    }
  };

  const handleConfirmAll = async (): Promise<void> => {
    setIsConfirmingAll(true);
    const pending = data.filter((_, i) => statuses[i] !== "completed");
    try {
      if (onConfirmAll) {
        await onConfirmAll(pending);
      } else if (onConfirm) {
        await Promise.all(
          pending.map((ev) => {
            const idx = data.indexOf(ev);
            return handleConfirm(ev, idx);
          }),
        );
      }
      const next: Record<number, EventStatus> = { ...statuses };
      data.forEach((_, i) => {
        next[i] = "completed";
      });
      setStatuses(next);
    } catch {
      // individual errors handled per-row
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
                <Text className="px-3 text-xs text-zinc-500">
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
                    onConfirm={() => void handleConfirm(event, index)}
                  />
                ))}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>

      {data.length > 1 ? (
        <Pressable
          onPress={
            allCompleted || isConfirmingAll
              ? undefined
              : () => void handleConfirmAll()
          }
          className="mt-3 w-full rounded-xl py-2.5 items-center justify-center flex-row gap-2"
          style={{
            backgroundColor: allCompleted
              ? "rgba(34,197,94,0.15)"
              : "rgba(0,187,255,0.18)",
            opacity: allCompleted || isConfirmingAll ? 0.85 : 1,
          }}
        >
          {isConfirmingAll ? (
            <ActivityIndicator size="small" color={DEFAULT_COLOR} />
          ) : allCompleted ? (
            <>
              <AppIcon icon={Tick02Icon} size={16} color="#22c55e" />
              <Text className="text-sm font-semibold text-[#22c55e]">
                All Added
              </Text>
            </>
          ) : (
            <Text className="text-sm font-semibold text-primary">
              {someCompleted ? "Add Remaining" : "Add All Events"}
            </Text>
          )}
        </Pressable>
      ) : null}
    </ToolCardShell>
  );
}
