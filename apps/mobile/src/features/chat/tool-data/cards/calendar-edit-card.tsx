import { Button, Card } from "heroui-native";
import { useState } from "react";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface CalendarEditOption {
  event_id?: string;
  summary?: string;
  original_summary?: string;
  description?: string;
  original_description?: string;
  start?: string;
  end?: string;
  original_start?: { dateTime?: string; date?: string };
  original_end?: { dateTime?: string; date?: string };
  is_all_day?: boolean;
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

function hasChanges(event: CalendarEditOption): boolean {
  if (
    event.summary &&
    event.original_summary &&
    event.summary !== event.original_summary
  )
    return true;
  if (
    event.description !== undefined &&
    event.original_description !== undefined &&
    event.description !== event.original_description
  )
    return true;
  if (event.start || event.end) return true;
  return false;
}

export function CalendarEditCard({ data }: { data: CalendarEditOption[] }) {
  const [eventStatuses, setEventStatuses] = useState<
    Record<string, EventStatus>
  >({});
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  if (!data?.length) return null;

  const handleEdit = (event: CalendarEditOption) => {
    const key = event.event_id || "";
    setEventStatuses((prev) => ({ ...prev, [key]: "loading" }));
    setTimeout(() => {
      setEventStatuses((prev) => ({ ...prev, [key]: "completed" }));
    }, 600);
  };

  const handleEditAll = () => {
    setIsConfirmingAll(true);
    const pending = data.filter(
      (event) => eventStatuses[event.event_id || ""] !== "completed",
    );
    for (const event of pending) {
      handleEdit(event);
    }
    setTimeout(() => setIsConfirmingAll(false), 800);
  };

  const allCompleted = data.every(
    (event) => eventStatuses[event.event_id || ""] === "completed",
  );
  const hasCompleted = data.some(
    (event) => eventStatuses[event.event_id || ""] === "completed",
  );

  const eventsByDate: Record<string, CalendarEditOption[]> = {};
  data.forEach((event) => {
    const dateStr =
      event.original_start?.dateTime ||
      event.original_start?.date ||
      new Date().toISOString();
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

            {events.map((event) => {
              const eventColor = event.background_color || "#00bbff";
              const showChanges = hasChanges(event);
              const status = eventStatuses[event.event_id || ""] || "idle";
              const summary =
                event.summary || event.original_summary || "Untitled Event";

              let timeDisplay = "All day";
              if (event.start && event.end) {
                timeDisplay = formatTimeRange(event.start, event.end);
              } else if (
                event.original_start?.dateTime &&
                event.original_end?.dateTime
              ) {
                timeDisplay = formatTimeRange(
                  event.original_start.dateTime,
                  event.original_end.dateTime,
                );
              }

              let originalTimeDisplay = "All day";
              if (
                event.original_start?.dateTime &&
                event.original_end?.dateTime
              ) {
                originalTimeDisplay = formatTimeRange(
                  event.original_start.dateTime,
                  event.original_end.dateTime,
                );
              }

              return (
                <View key={event.event_id || summary} className="mb-2">
                  {status !== "completed" && showChanges && (
                    <View
                      className="relative rounded-lg p-3 pl-5 mb-1"
                      style={{
                        backgroundColor: `${eventColor}20`,
                        opacity: 0.6,
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
                      <Text className="text-[10px] text-[#8e8e93] mb-1">
                        Current Event
                      </Text>
                      <Text className="text-sm leading-tight text-white">
                        {event.original_summary || "Untitled Event"}
                      </Text>
                      {event.original_description && (
                        <Text className="text-xs text-[#8e8e93] mt-1">
                          {event.original_description}
                        </Text>
                      )}
                      <Text className="text-xs text-[#8e8e93] mt-1">
                        {originalTimeDisplay}
                      </Text>
                    </View>
                  )}

                  <View
                    className="relative rounded-lg p-3 pr-2 pl-5 flex-row items-end gap-2"
                    style={{
                      backgroundColor: `${eventColor}${showChanges && status !== "completed" ? "10" : "20"}`,
                      borderWidth:
                        showChanges && status !== "completed" ? 2 : 0,
                      borderStyle: "dashed",
                      borderColor:
                        showChanges && status !== "completed"
                          ? `${eventColor}80`
                          : "transparent",
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
                      {showChanges && status !== "completed" && (
                        <Text className="text-[10px] text-[#00bbff] mb-1">
                          Updated Event
                        </Text>
                      )}
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
                      isDisabled={
                        status === "completed" || status === "loading"
                      }
                      onPress={() => handleEdit(event)}
                    >
                      <Button.Label>
                        {status === "loading"
                          ? "..."
                          : status === "completed"
                            ? "Updated"
                            : "Confirm"}
                      </Button.Label>
                    </Button>
                  </View>
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
            onPress={handleEditAll}
          >
            <Button.Label>
              {allCompleted
                ? "All Updated"
                : hasCompleted
                  ? "Update Remaining"
                  : "Update All Events"}
            </Button.Label>
          </Button>
        )}
      </Card.Body>
    </Card>
  );
}
