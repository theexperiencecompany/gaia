import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { groupEventsByDate } from "@gaia/shared/tool-utils";

export interface CalendarFetchItem {
  summary: string;
  start_time: string;
  end_time: string;
  calendar_name?: string;
  background_color?: string;
}

function formatTimeRange(start: string, end: string): string {
  const opts: Intl.DateTimeFormatOptions = {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  };
  return `${new Date(start).toLocaleTimeString("en-US", opts)} - ${new Date(end).toLocaleTimeString("en-US", opts)}`;
}

function formatDateRelative(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffDays = Math.floor(
    (date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24),
  );
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Tomorrow";
  if (diffDays === -1) return "Yesterday";
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function CalendarFetchCard({ data }: { data: CalendarFetchItem[] }) {
  const eventsByDate = groupEventsByDate(data);

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {Object.entries(eventsByDate).map(([dateString, events]) => (
          <View key={dateString} className="mb-3">
            <View className="flex-row items-center mb-2">
              <View className="flex-1 h-px bg-zinc-700" />
              <Text className="px-3 text-xs text-[#8e8e93]">
                {formatDateRelative(dateString)}
              </Text>
              <View className="flex-1 h-px bg-zinc-700" />
            </View>

            {events.map((event, index) => {
              const eventColor = event.background_color || "#00bbff";
              const timeDisplay =
                event.start_time?.includes("T") && event.end_time
                  ? formatTimeRange(event.start_time, event.end_time)
                  : "All day";

              return (
                <View
                  key={`fetch-${event.summary}-${index}`}
                  className="relative rounded-lg p-3 pl-5 mb-2"
                  style={{ backgroundColor: `${eventColor}20` }}
                >
                  <View className="absolute left-1 top-0 h-full justify-center">
                    <View
                      className="w-1 rounded-full"
                      style={{
                        backgroundColor: eventColor,
                        height: "80%",
                      }}
                    />
                  </View>
                  <Text className="text-sm leading-tight text-white">
                    {event.summary || "Untitled Event"}
                  </Text>
                  <View className="flex-row items-center gap-2 mt-1">
                    <Text className="text-xs text-[#8e8e93]">
                      {timeDisplay}
                    </Text>
                    {event.calendar_name && (
                      <>
                        <Text className="text-xs text-[#8e8e93]">•</Text>
                        <Text className="text-xs text-[#8e8e93]">
                          {event.calendar_name}
                        </Text>
                      </>
                    )}
                  </View>
                </View>
              );
            })}
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}
