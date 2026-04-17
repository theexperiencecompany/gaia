import { useMemo } from "react";
import { Linking, Pressable, View } from "react-native";
import { Calendar03Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  SectionLabel,
  ToolCardHeader,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Types --------------------------------------------------------------------

export interface CalendarFetchItem {
  summary?: string;
  title?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
  location?: string;
  attendees?: Array<{ email?: string; displayName?: string }>;
  calendar_source?: string;
  calendar_name?: string;
  background_color?: string;
  organizer?: { email?: string; displayName?: string };
}

interface CalendarFetchCardProps {
  data: CalendarFetchItem[];
  onEventPress?: (event: CalendarFetchItem, index: number) => void;
}

// -- Helpers ------------------------------------------------------------------

function getStartRaw(ev: CalendarFetchItem): string | undefined {
  return ev.start?.dateTime ?? ev.start?.date;
}

function getEndRaw(ev: CalendarFetchItem): string | undefined {
  return ev.end?.dateTime ?? ev.end?.date;
}

function isAllDay(ev: CalendarFetchItem): boolean {
  return !!ev.start?.date && !ev.start?.dateTime;
}

function formatDayHeader(dateStr: string): string {
  const date = new Date(dateStr);
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);

  if (date.toDateString() === today.toDateString()) return "TODAY";
  if (date.toDateString() === tomorrow.toDateString()) return "TOMORROW";

  return date
    .toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    })
    .toUpperCase();
}

function formatTimeRange(ev: CalendarFetchItem): string {
  if (isAllDay(ev)) return "All day";
  const start = getStartRaw(ev);
  if (!start) return "";
  const startDate = new Date(start);
  if (Number.isNaN(startDate.getTime())) return "";
  const startTime = startDate.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  const end = getEndRaw(ev);
  if (!end) return startTime;
  const endDate = new Date(end);
  if (Number.isNaN(endDate.getTime())) return startTime;
  const endTime = endDate.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${startTime} – ${endTime}`;
}

// -- Calendar fetch card ------------------------------------------------------

export function CalendarFetchCard({
  data,
  onEventPress,
}: CalendarFetchCardProps) {
  const grouped = useMemo(() => {
    const map = new Map<string, CalendarFetchItem[]>();
    for (const ev of data) {
      const raw = getStartRaw(ev);
      if (!raw) {
        const fallbackKey = "Unscheduled";
        if (!map.has(fallbackKey)) map.set(fallbackKey, []);
        map.get(fallbackKey)?.push(ev);
        continue;
      }
      const date = new Date(raw);
      const key = Number.isNaN(date.getTime())
        ? "Unscheduled"
        : date.toDateString();
      if (!map.has(key)) map.set(key, []);
      map.get(key)?.push(ev);
    }
    return Array.from(map.entries());
  }, [data]);

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Calendar03Icon}
        title="Calendar"
        count={data.length}
      />

      {data.length === 0 ? (
        <Text className="text-zinc-500 text-sm">No events found</Text>
      ) : (
        grouped.map(([date, events], groupIdx) => (
          <View key={date}>
            {groupIdx > 0 && <View className="h-px bg-zinc-700 my-2" />}
            <SectionLabel>
              {date === "Unscheduled" ? "UNSCHEDULED" : formatDayHeader(date)}
            </SectionLabel>
            <View className="gap-1.5">
              {events.map((ev, evIdx) => {
                const title = ev.summary ?? ev.title ?? "Untitled Event";
                const timeLabel = formatTimeRange(ev);
                const calendarLabel = ev.calendar_name ?? ev.calendar_source;
                const accent = ev.background_color ?? "#00bbff";
                const tinted = `${accent}20`;
                const key = `${date}-${title}-${evIdx}`;

                const onPress = onEventPress
                  ? () => onEventPress(ev, evIdx)
                  : undefined;

                const content = (
                  <View className="flex-row items-start gap-3">
                    <View
                      className="w-1 rounded-full self-stretch"
                      style={{ backgroundColor: accent }}
                    />
                    <View className="flex-1 min-w-0">
                      <Text
                        className="text-zinc-200 text-sm font-medium leading-tight"
                        numberOfLines={2}
                      >
                        {title}
                      </Text>
                      <View className="flex-row items-center gap-1.5 mt-0.5">
                        {timeLabel ? (
                          <Text
                            className="text-zinc-400 text-xs"
                            numberOfLines={1}
                          >
                            {timeLabel}
                          </Text>
                        ) : null}
                        {timeLabel && calendarLabel ? (
                          <View className="w-0.5 h-0.5 rounded-full bg-zinc-500" />
                        ) : null}
                        {calendarLabel ? (
                          <Text
                            className="text-zinc-400 text-xs"
                            numberOfLines={1}
                          >
                            {calendarLabel}
                          </Text>
                        ) : null}
                      </View>
                    </View>
                  </View>
                );

                if (onPress) {
                  return (
                    <Pressable
                      key={key}
                      onPress={onPress}
                      className="rounded-xl p-3"
                      style={{ backgroundColor: tinted }}
                      android_ripple={{ color: "rgba(255,255,255,0.05)" }}
                    >
                      {content}
                    </Pressable>
                  );
                }

                return (
                  <View
                    key={key}
                    className="rounded-xl p-3"
                    style={{ backgroundColor: tinted }}
                  >
                    {content}
                  </View>
                );
              })}
            </View>
          </View>
        ))
      )}

      <Pressable
        onPress={() => Linking.openURL("googlecalendar://")}
        className="rounded-xl bg-primary/15 py-2.5 items-center mt-3"
      >
        <Text className="text-primary text-sm font-semibold">
          Open Calendar
        </Text>
      </Pressable>
    </ToolCardShell>
  );
}
