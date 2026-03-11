import { Button, Card } from "heroui-native";
import { useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarOption {
  summary?: string;
  description?: string;
  start?: string;
  end?: string;
  is_all_day?: boolean;
  background_color?: string;
  calendar_id?: string;
  attendees?: string[];
}

type EventStatus = "idle" | "loading" | "completed";

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

export function CalendarOptionsCard({ data }: { data: CalendarOption[] }) {
  const [eventStatuses, setEventStatuses] = useState<
    Record<number, EventStatus>
  >({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  if (!data.every((option) => option.summary)) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <Text className="text-xs text-red-500">
            Error: Could not add Calendar event. Please try again later.
          </Text>
        </Card.Body>
      </Card>
    );
  }

  const handleAdd = (index: number) => {
    setEventStatuses((prev) => ({ ...prev, [index]: "loading" }));
    setTimeout(() => {
      setEventStatuses((prev) => ({ ...prev, [index]: "completed" }));
    }, 600);
  };

  const handleAddAll = async () => {
    setIsConfirmingAll(true);
    const pending = data
      .map((_, index) => index)
      .filter((index) => eventStatuses[index] !== "completed");
    for (const index of pending) {
      handleAdd(index);
    }
    setTimeout(() => setIsConfirmingAll(false), 800);
  };

  const allCompleted = data.every(
    (_, index) => eventStatuses[index] === "completed",
  );
  const hasCompleted = data.some(
    (_, index) => eventStatuses[index] === "completed",
  );

  const eventsByDate: Record<
    string,
    Array<{ event: CalendarOption; index: number }>
  > = {};
  data.forEach((event, index) => {
    const dateStr = event.start || new Date().toISOString();
    const date = new Date(dateStr).toISOString().slice(0, 10);
    if (!eventsByDate[date]) eventsByDate[date] = [];
    eventsByDate[date].push({ event, index });
  });

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {Object.entries(eventsByDate).map(([dateString, entries]) => (
          <View key={dateString} className="mb-3">
            <View className="flex-row items-center mb-2">
              <View className="flex-1 h-px bg-zinc-700" />
              <Text className="px-3 text-xs text-[#8e8e93]">
                {formatDateRelative(dateString)}
              </Text>
              <View className="flex-1 h-px bg-zinc-700" />
            </View>

            {entries.map(({ event, index }) => {
              const eventColor = event.background_color || "#00bbff";
              const summary = event.summary || "Untitled Event";
              const status = eventStatuses[index] || "idle";
              const timeDisplay = event.is_all_day
                ? "All day"
                : event.start && event.end
                  ? formatTimeRange(event.start, event.end)
                  : event.start
                    ? new Date(event.start).toLocaleTimeString("en-US", {
                        hour: "numeric",
                        minute: "2-digit",
                        hour12: true,
                      })
                    : "No time";

              return (
                <View
                  key={`event-${summary}-${index}`}
                  className="relative rounded-lg p-3 pr-2 pl-5 mb-2 flex-row items-end gap-2"
                  style={{
                    backgroundColor: `${eventColor}20`,
                    opacity: status === "completed" ? 0.5 : 1,
                  }}
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
                  <View className="flex-1">
                    <Text className="text-sm leading-tight text-white">
                      {summary}
                    </Text>
                    {event.description && (
                      <Text className="text-xs text-[#8e8e93] mt-1">
                        {event.description}
                      </Text>
                    )}
                    <Text className="text-xs text-[#8e8e93] mt-1">
                      {timeDisplay}
                    </Text>
                  </View>
                  <Button
                    size="sm"
                    variant={status === "completed" ? "secondary" : "primary"}
                    isDisabled={status === "completed" || status === "loading"}
                    onPress={() => handleAdd(index)}
                  >
                    <Button.Label>
                      {status === "loading"
                        ? "..."
                        : status === "completed"
                          ? "Added"
                          : "Confirm"}
                    </Button.Label>
                  </Button>
                </View>
              );
            })}
          </View>
        ))}

        {data.length > 1 && (
          <Button
            variant="primary"
            className="mt-1 w-full"
            isDisabled={allCompleted || isConfirmingAll}
            onPress={handleAddAll}
          >
            <Button.Label>
              {allCompleted
                ? "All Added"
                : hasCompleted
                  ? "Add Remaining"
                  : "Add All Events"}
            </Button.Label>
          </Button>
        )}
      </Card.Body>
    </Card>
  );
}
