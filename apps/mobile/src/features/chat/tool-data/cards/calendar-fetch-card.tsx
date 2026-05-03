import { useRouter } from "expo-router";
import { Card, Chip, PressableFeedback } from "heroui-native";
import { useMemo } from "react";
import { ScrollView, View } from "react-native";
import { AppIcon, Calendar03Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";

// -- Types --------------------------------------------------------------------

export interface CalendarFetchItem {
  summary: string;
  start_time: string;
  end_time: string;
  calendar_name: string;
  background_color: string;
}

interface CalendarFetchCardProps {
  data: CalendarFetchItem[];
}

// -- Date helpers (mirrors web utils/date/calendarDateUtils.ts) --------------

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

  if (compareDate.getTime() === today.getTime()) {
    return `${fullDate} (Today)`;
  }
  if (compareDate.getTime() === tomorrow.getTime()) {
    return `${fullDate} (Tomorrow)`;
  }
  if (compareDate.getTime() === yesterday.getTime()) {
    return `${fullDate} (Yesterday)`;
  }
  return fullDate;
}

function formatTimeString(date: Date): string {
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const ampm = hours >= 12 ? "PM" : "AM";
  const hour12 = hours % 12 || 12;
  const minuteStr = minutes.toString().padStart(2, "0");

  if (minutes === 0) {
    return `${hour12} ${ampm}`;
  }
  return `${hour12}:${minuteStr} ${ampm}`;
}

function formatTimeRange(startTime: string, endTime: string): string {
  const start = new Date(startTime);
  const end = new Date(endTime);

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

// -- Grouping helpers (mirrors web utils/calendar/eventGrouping.ts) ----------

function extractDateFromFetchData(event: CalendarFetchItem): string {
  if (event.start_time?.includes("T")) {
    return new Date(event.start_time).toISOString().slice(0, 10);
  }
  return event.start_time ?? new Date().toISOString().slice(0, 10);
}

function extractTimestampFromFetchData(event: CalendarFetchItem): number {
  return new Date(event.start_time).getTime();
}

function groupFetchDataByDate(
  events: CalendarFetchItem[],
): Record<string, CalendarFetchItem[]> {
  const grouped: Record<string, CalendarFetchItem[]> = {};

  for (const event of events) {
    const eventDate = extractDateFromFetchData(event);
    if (!grouped[eventDate]) {
      grouped[eventDate] = [];
    }
    grouped[eventDate].push(event);
  }

  for (const dayEvents of Object.values(grouped)) {
    dayEvents.sort(
      (a, b) =>
        extractTimestampFromFetchData(a) - extractTimestampFromFetchData(b),
    );
  }

  return grouped;
}

// -- Event row ---------------------------------------------------------------

interface EventRowProps {
  event: CalendarFetchItem;
}

function EventRow({ event }: EventRowProps) {
  const eventColor = event.background_color || "#00bbff";
  const isTimed = !!event.start_time?.includes("T") && !!event.end_time;

  return (
    <View
      className="relative flex-row items-start gap-2 rounded-lg p-3 pl-5"
      style={{ backgroundColor: `${eventColor}20` }}
    >
      {/* Colored left border pill */}
      <View
        pointerEvents="none"
        style={{
          position: "absolute",
          top: 0,
          left: 4,
          height: "100%",
          justifyContent: "center",
        }}
      >
        <View
          style={{
            width: 4,
            height: "80%",
            borderRadius: 999,
            backgroundColor: eventColor,
          }}
        />
      </View>

      {/* Event details */}
      <View className="flex-1 min-w-0">
        <Text className="text-base text-foreground" numberOfLines={2}>
          {event.summary}
        </Text>

        <View className="mt-1 flex-row items-center gap-2">
          <Text className="text-xs text-muted">
            {isTimed
              ? formatTimeRange(event.start_time, event.end_time)
              : "All day"}
          </Text>
          {event.calendar_name ? (
            <>
              <View
                style={{
                  width: 2,
                  height: 2,
                  borderRadius: 1,
                  backgroundColor: "#71717a",
                }}
              />
              <Text className="text-xs text-muted" numberOfLines={1}>
                {event.calendar_name}
              </Text>
            </>
          ) : null}
        </View>
      </View>
    </View>
  );
}

// -- Calendar fetch card -----------------------------------------------------

export function CalendarFetchCard({ data }: CalendarFetchCardProps) {
  const router = useRouter();

  const eventsByDay = useMemo(() => {
    if (!data || data.length === 0) return {};
    return groupFetchDataByDate(data);
  }, [data]);

  const dayEntries = Object.entries(eventsByDay);

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-7 h-7 rounded-xl bg-[#00bbff]/15 items-center justify-center">
            <AppIcon icon={Calendar03Icon} size={14} color="#00bbff" />
          </View>
          <View className="flex-1 min-w-0">
            <Text className="text-sm font-semibold text-foreground">
              {data.length} Event{data.length !== 1 ? "s" : ""}
            </Text>
          </View>
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>Calendar</Chip.Label>
          </Chip>
        </View>

        {data.length === 0 ? (
          <Text className="text-muted text-sm">No events found</Text>
        ) : (
          <>
            <ScrollView
              style={{ maxHeight: 400 }}
              nestedScrollEnabled
              showsVerticalScrollIndicator={false}
            >
              {dayEntries.map(([dateString, dayEvents]) => (
                <View key={dateString} className="mb-3">
                  {/* Date divider */}
                  <View className="flex-row items-center mb-2">
                    <View className="flex-1 h-px bg-white/8" />
                    <Text className="px-3 text-xs text-muted">
                      {formatDateWithRelative(dateString)}
                    </Text>
                    <View className="flex-1 h-px bg-white/8" />
                  </View>

                  {/* Events for this day */}
                  <View className="gap-2">
                    {dayEvents.map((event, index) => (
                      <EventRow
                        key={`${dateString}-${event.summary}-${index}`}
                        event={event}
                      />
                    ))}
                  </View>
                </View>
              ))}
            </ScrollView>

            {/* Open Calendar button */}
            <PressableFeedback
              onPress={() => router.push("/(app)/calendar")}
              className="mt-2 rounded-xl bg-[#00bbff]/15 py-2.5 items-center"
            >
              <Text className="text-sm font-medium text-[#00bbff]">
                Open Calendar
              </Text>
            </PressableFeedback>
          </>
        )}
      </Card.Body>
    </Card>
  );
}
