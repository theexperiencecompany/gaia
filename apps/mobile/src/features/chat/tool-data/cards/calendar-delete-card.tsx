import { Button, Card } from "heroui-native";
import { useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarDeleteOption {
  event_id?: string;
  summary?: string;
  description?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
  background_color?: string;
  calendar_id?: string;
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

export function CalendarDeleteCard({ data }: { data: CalendarDeleteOption[] }) {
  const [eventStatuses, setEventStatuses] = useState<
    Record<string, EventStatus>
  >({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  if (!data?.length) return null;

  const handleDelete = (event: CalendarDeleteOption) => {
    const key = event.event_id || "";
    setEventStatuses((prev) => ({ ...prev, [key]: "loading" }));
    setTimeout(() => {
      setEventStatuses((prev) => ({ ...prev, [key]: "completed" }));
    }, 600);
  };

  const handleDeleteAll = () => {
    setIsConfirmingAll(true);
    const pending = data.filter(
      (event) => eventStatuses[event.event_id || ""] !== "completed",
    );
    for (const event of pending) {
      handleDelete(event);
    }
    setTimeout(() => setIsConfirmingAll(false), 800);
  };

  const allCompleted = data.every(
    (event) => eventStatuses[event.event_id || ""] === "completed",
  );
  const hasCompleted = data.some(
    (event) => eventStatuses[event.event_id || ""] === "completed",
  );

  const eventsByDate: Record<string, CalendarDeleteOption[]> = {};
  data.forEach((event) => {
    const dateStr =
      event.start?.dateTime || event.start?.date || new Date().toISOString();
    const date = new Date(dateStr).toISOString().slice(0, 10);
    if (!eventsByDate[date]) eventsByDate[date] = [];
    eventsByDate[date].push(event);
  });

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
              const summary = event.summary || "Untitled Event";
              const status = eventStatuses[event.event_id || ""] || "idle";
              const hasTime = event.start?.dateTime && event.end?.dateTime;
              const timeDisplay = hasTime
                ? formatTimeRange(event.start!.dateTime!, event.end!.dateTime!)
                : "All day";

              return (
                <View
                  key={event.event_id || `delete-${index}`}
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
                    variant={status === "completed" ? "secondary" : "danger"}
                    isDisabled={status === "completed" || status === "loading"}
                    onPress={() => handleDelete(event)}
                  >
                    <Button.Label>
                      {status === "loading"
                        ? "..."
                        : status === "completed"
                          ? "Deleted"
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
            variant="danger"
            className="mt-1 w-full"
            isDisabled={allCompleted || isConfirmingAll}
            onPress={handleDeleteAll}
          >
            <Button.Label>
              {allCompleted
                ? "All Deleted"
                : hasCompleted
                  ? "Delete Remaining"
                  : "Delete All Events"}
            </Button.Label>
          </Button>
        )}
      </Card.Body>
    </Card>
  );
}
